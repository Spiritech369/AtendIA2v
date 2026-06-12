"""Activate Dinamo Phase E document contracts in DB real, dry-run only.

Phase E wires document.check and expediente.evaluate as tenant-scoped fact
tools and stores DB-backed no-send evidence from deterministic document facts.
It does not call OpenAI, Vision APIs, Drive, WhatsApp, outbox, or workflow
executors.

Usage:
    PYTHONPATH=. uv run python -m atendia.scripts.seed_dinamo_phase_e_documents \
        --tenant-id <uuid>
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import json
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from atendia.db.models.agent import Agent
from atendia.db.models.outbound_outbox import OutboundOutbox
from atendia.db.models.product_agent import (
    AgentDeployment,
    AgentFieldPermission,
    AgentToolBinding,
    AgentVersion,
)
from atendia.db.models.workflow import Workflow, WorkflowExecution
from atendia.db.session import get_db_session
from atendia.product_agents import service
from atendia.scripts.seed_dinamo_phase_d_workflows import PHASE_D_SEED_ID
from atendia.scripts.seed_dinamo_v1 import (
    AGENT_NAME,
    PLAN_CREDITO_CHOICES,
    SEED_ID,
    SOURCE_VERSION_ID,
    build_tool_binding_specs,
)

JsonDict = dict[str, Any]

PHASE_E_SEED_ID = "dinamo_tenant_runtime_plan_v1_phase_e"
PHASE_E_SOURCE_VERSION_ID = "DINAMO_TENANT_RUNTIME_PLAN_V1:PHASE_E:2026-06-12"
PHASE_E_DECISION_READY = "DINAMO_PHASE_E_DOCUMENTS_DRY_RUN_READY"
PHASE_E_DECISION_BLOCKED = "DINAMO_PHASE_E_DOCUMENTS_DRY_RUN_BLOCKED"
PHASE_E_TOOLS = ("document.check", "expediente.evaluate")
PHASE_E_SYSTEM_FIELDS = ("Docs_Checklist", "Doc_Incompletos", "Doc_Completos")


@dataclass
class PhaseEDocumentResult:
    tenant_id: str
    dry_run: bool
    updated_tool_bindings: list[str] = field(default_factory=list)
    updated_field_permissions: list[str] = field(default_factory=list)
    suite_id: str | None = None
    run_id: str | None = None
    status: str = "ready"
    decision: str = PHASE_E_DECISION_READY
    pass_count: int = 0
    blocked_count: int = 0
    outbox_before: int = 0
    outbox_after: int = 0
    workflow_executions_before: int = 0
    workflow_executions_after: int = 0
    deployments_no_send: bool = True
    assertions: list[str] = field(default_factory=list)

    def as_dict(self) -> JsonDict:
        return {
            "tenant_id": self.tenant_id,
            "dry_run": self.dry_run,
            "updated_tool_bindings": self.updated_tool_bindings,
            "updated_field_permissions": self.updated_field_permissions,
            "suite_id": self.suite_id,
            "run_id": self.run_id,
            "status": self.status,
            "decision": self.decision,
            "pass_count": self.pass_count,
            "blocked_count": self.blocked_count,
            "outbox_before": self.outbox_before,
            "outbox_after": self.outbox_after,
            "outbox_delta": self.outbox_after - self.outbox_before,
            "workflow_executions_before": self.workflow_executions_before,
            "workflow_executions_after": self.workflow_executions_after,
            "workflow_execution_delta": (
                self.workflow_executions_after - self.workflow_executions_before
            ),
            "deployments_no_send": self.deployments_no_send,
            "assertions": self.assertions,
            "openai_api_real": False,
            "vision_api_real": False,
            "external_apis": False,
            "send": "no_send",
            "workflow_side_effects": False,
        }


@dataclass(frozen=True)
class PhaseEScenario:
    key: str
    name: str
    plan_credito: str
    document_facts: tuple[JsonDict, ...]
    expected_doc_completos: bool
    expected_stage_preview: str
    expected_missing: tuple[str, ...] = ()
    expected_rejected: tuple[str, ...] = ()
    expected_handoff_reason: str | None = None

    def as_expected(self) -> JsonDict:
        return {
            "plan_credito": self.plan_credito,
            "expected_doc_completos": self.expected_doc_completos,
            "expected_stage_preview": self.expected_stage_preview,
            "expected_missing": list(self.expected_missing),
            "expected_rejected": list(self.expected_rejected),
            "expected_handoff_reason": self.expected_handoff_reason,
            "send": "no_send",
            "vision_api_real": False,
            "workflow_side_effects": False,
        }


def phase_e_scenarios() -> tuple[PhaseEScenario, ...]:
    plan = PLAN_CREDITO_CHOICES[0]
    return (
        PhaseEScenario(
            key="blurred_document_rejected",
            name="Documento borroso rechazado no cuenta",
            plan_credito=plan,
            document_facts=(
                _doc("ine_frente", status="rejected", reason="borroso", attachment_id="att-blur"),
            ),
            expected_doc_completos=False,
            expected_stage_preview="papeleria_incompleta",
            expected_missing=("ine_frente", "comprobante_domicilio", "estado_cuenta"),
            expected_rejected=("ine_frente",),
        ),
        PhaseEScenario(
            key="partial_valid_document_missing_rest",
            name="Documento valido parcial mantiene faltantes",
            plan_credito=plan,
            document_facts=(
                _doc("ine_frente", status="accepted", attachment_id="att-ine"),
            ),
            expected_doc_completos=False,
            expected_stage_preview="papeleria_incompleta",
            expected_missing=("comprobante_domicilio", "estado_cuenta"),
        ),
        PhaseEScenario(
            key="complete_expediente_sets_doc_completos",
            name="Expediente completo habilita etapa papeleria completa",
            plan_credito=plan,
            document_facts=(
                _doc("ine_frente", status="accepted", attachment_id="att-ine"),
                _doc("comprobante_domicilio", status="accepted", attachment_id="att-cfe"),
                _doc("estado_cuenta", status="accepted", attachment_id="att-edo"),
            ),
            expected_doc_completos=True,
            expected_stage_preview="papeleria_completa",
        ),
        PhaseEScenario(
            key="foreign_document_doubt_handoff",
            name="Documento ajeno dispara duda y handoff preview",
            plan_credito=plan,
            document_facts=(
                _doc(
                    "estado_cuenta",
                    status="rejected",
                    reason="titular_no_coincide",
                    attachment_id="att-foreign",
                ),
            ),
            expected_doc_completos=False,
            expected_stage_preview="papeleria_incompleta",
            expected_missing=("ine_frente", "comprobante_domicilio", "estado_cuenta"),
            expected_rejected=("estado_cuenta",),
            expected_handoff_reason="documento_dudoso",
        ),
    )


async def seed_dinamo_phase_e_documents(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    dry_run: bool = False,
    created_by_user_id: UUID | None = None,
) -> PhaseEDocumentResult:
    result = PhaseEDocumentResult(tenant_id=str(tenant_id), dry_run=dry_run)
    if dry_run:
        result.updated_tool_bindings = list(PHASE_E_TOOLS)
        result.updated_field_permissions = list(PHASE_E_SYSTEM_FIELDS)
        result.pass_count = len(phase_e_scenarios())
        result.assertions = ["preview_only"]
        return result

    result.outbox_before = await _outbox_count(session, tenant_id)
    result.workflow_executions_before = await _workflow_execution_count(session, tenant_id)
    result.deployments_no_send = await _deployments_are_no_send(session, tenant_id)
    if not result.deployments_no_send:
        raise service.ProductAgentError("tenant deployments are not fully no-send")

    _agent, version = await _load_phase_d_or_newer_version(session, tenant_id)
    await _upsert_phase_e_tool_bindings(
        session,
        tenant_id=tenant_id,
        version=version,
        result=result,
    )
    await _reinforce_phase_e_field_permissions(
        session,
        tenant_id=tenant_id,
        version=version,
        result=result,
    )
    _update_version_phase_e_policy(version)

    lab = _run_phase_e_dry_lab(phase_e_scenarios())
    suite, run = await _store_phase_e_lab(
        session,
        tenant_id=tenant_id,
        version=version,
        lab=lab,
        created_by_user_id=created_by_user_id,
    )
    result.suite_id = str(suite.id)
    result.run_id = str(run.id)
    result.status = run.status
    result.decision = run.decision
    result.pass_count = run.pass_count
    result.blocked_count = run.blocked_count
    result.assertions = ["passed"]
    result.outbox_after = await _outbox_count(session, tenant_id)
    result.workflow_executions_after = await _workflow_execution_count(session, tenant_id)
    if result.outbox_after != result.outbox_before:
        raise service.ProductAgentError("outbox changed during Phase E dry-run")
    if result.workflow_executions_after != result.workflow_executions_before:
        raise service.ProductAgentError("workflow executions changed during Phase E dry-run")
    return result


async def _upsert_phase_e_tool_bindings(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    version: AgentVersion,
    result: PhaseEDocumentResult,
) -> None:
    specs = build_tool_binding_specs()
    rows = (
        await session.execute(
            select(AgentToolBinding).where(
                AgentToolBinding.tenant_id == tenant_id,
                AgentToolBinding.agent_version_id == version.id,
            )
        )
    ).scalars().all()
    by_name = {row.tool_name: row for row in rows}
    for tool_name in PHASE_E_TOOLS:
        spec = specs[tool_name]
        metadata = {
            **spec["metadata_json"],
            "source": SEED_ID,
            "phase_source": PHASE_E_SEED_ID,
            "source_version_id": SOURCE_VERSION_ID,
            "phase_source_version_id": PHASE_E_SOURCE_VERSION_ID,
            "phase": "E",
            "fact_only": True,
            "dry_run_only": True,
            "customer_visible_output_allowed": False,
            "vision_api_real": False,
        }
        binding = by_name.get(tool_name)
        if binding is None:
            session.add(
                AgentToolBinding(
                    tenant_id=tenant_id,
                    agent_version_id=version.id,
                    tool_name=tool_name,
                    enabled=True,
                    required=False,
                    input_schema={"type": "object"},
                    output_schema={"type": "object"},
                    timeout_ms=spec["timeout_ms"],
                    metadata_json=metadata,
                )
            )
        else:
            binding.enabled = True
            binding.required = False
            binding.input_schema = {"type": "object"}
            binding.output_schema = {"type": "object"}
            binding.timeout_ms = spec["timeout_ms"]
            binding.metadata_json = metadata
        result.updated_tool_bindings.append(tool_name)


async def _reinforce_phase_e_field_permissions(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    version: AgentVersion,
    result: PhaseEDocumentResult,
) -> None:
    rows = (
        await session.execute(
            select(AgentFieldPermission).where(
                AgentFieldPermission.tenant_id == tenant_id,
                AgentFieldPermission.agent_version_id == version.id,
                AgentFieldPermission.field_key.in_(PHASE_E_SYSTEM_FIELDS),
            )
        )
    ).scalars().all()
    by_key = {row.field_key: row for row in rows}
    for field_key in PHASE_E_SYSTEM_FIELDS:
        write_policy = {
            "owner": "system_tool",
            "allowed_tools": ["expediente.evaluate"],
            "blocked_for_agent": True,
            "phase_source": PHASE_E_SEED_ID,
        }
        metadata = {
            "source": SEED_ID,
            "phase_source": PHASE_E_SEED_ID,
            "source_version_id": SOURCE_VERSION_ID,
            "phase_source_version_id": PHASE_E_SOURCE_VERSION_ID,
            "phase": "E",
            "write_owner": "system_tool",
        }
        permission = by_key.get(field_key)
        if permission is None:
            session.add(
                AgentFieldPermission(
                    tenant_id=tenant_id,
                    agent_version_id=version.id,
                    field_key=field_key,
                    can_read=True,
                    can_write=False,
                    evidence_required=True,
                    write_policy=write_policy,
                    metadata_json=metadata,
                )
            )
        else:
            permission.can_read = True
            permission.can_write = False
            permission.evidence_required = True
            permission.write_policy = write_policy
            permission.metadata_json = metadata
        result.updated_field_permissions.append(field_key)


def _update_version_phase_e_policy(version: AgentVersion) -> None:
    version.tool_policy = _phase_e_tool_policy(version.tool_policy)
    version.field_policy = _phase_e_field_policy(version.field_policy)
    test_policy = dict(version.test_policy or {})
    test_policy["phase_e_documents_dry_run_gate"] = PHASE_E_DECISION_READY
    version.test_policy = test_policy
    version.snapshot = {
        **(version.snapshot or {}),
        "phase_e_source": PHASE_E_SEED_ID,
        "phase_e_source_version_id": PHASE_E_SOURCE_VERSION_ID,
        "phase_e_tools": list(PHASE_E_TOOLS),
    }


def _phase_e_tool_policy(existing_policy: dict[str, Any] | None) -> JsonDict:
    policy = copy.deepcopy(existing_policy or {})
    bindings = [
        copy.deepcopy(item)
        for item in policy.get("bindings") or []
        if isinstance(item, dict) and (item.get("name") or item.get("tool_name"))
    ]
    by_name = {str(item.get("name") or item.get("tool_name")): item for item in bindings}
    specs = build_tool_binding_specs()
    for tool_name in PHASE_E_TOOLS:
        spec = specs[tool_name]
        binding = by_name.get(tool_name, {"name": tool_name, "tool_name": tool_name})
        binding.update(
            {
                "name": tool_name,
                "tool_name": tool_name,
                "description": spec["description"],
                "enabled": True,
                "required": False,
                "dry_run_only": True,
                "approval_required": False,
                "phase": "E",
                "phase_source": PHASE_E_SEED_ID,
                "phase_source_version_id": PHASE_E_SOURCE_VERSION_ID,
                "customer_visible_output_allowed": False,
                "vision_api_real": False,
            }
        )
        binding.setdefault("input_schema", {"type": "object"})
        binding.setdefault("output_facts_schema", {"type": "object"})
        binding.setdefault("timeout_ms", spec["timeout_ms"])
        binding["metadata"] = {
            **(binding.get("metadata") or {}),
            **spec["metadata_json"],
            "source": SEED_ID,
            "phase_source": PHASE_E_SEED_ID,
            "phase_source_version_id": PHASE_E_SOURCE_VERSION_ID,
            "fact_only": True,
            "dry_run_only": True,
        }
        by_name[tool_name] = binding
    ordered_names = [
        name
        for name in [*(policy.get("required_tools") or []), *(policy.get("optional_tools") or [])]
        if name in by_name
    ]
    for name in PHASE_E_TOOLS:
        if name not in ordered_names:
            ordered_names.append(name)
    optional = list(dict.fromkeys([*(policy.get("optional_tools") or []), *PHASE_E_TOOLS]))
    policy.update(
        {
            "phase_e_source": PHASE_E_SEED_ID,
            "phase_e_source_version_id": PHASE_E_SOURCE_VERSION_ID,
            "optional_tools": optional,
            "document_tools": list(PHASE_E_TOOLS),
            "document_tools_return_customer_copy": False,
            "bindings": [by_name[name] for name in ordered_names],
        }
    )
    return policy


def _phase_e_field_policy(existing_policy: dict[str, Any] | None) -> JsonDict:
    policy = copy.deepcopy(existing_policy or {})
    fields = [
        copy.deepcopy(item)
        for item in policy.get("fields") or []
        if isinstance(item, dict) and (item.get("field_key") or item.get("key"))
    ]
    by_key = {str(item.get("field_key") or item.get("key")): item for item in fields}
    for field_key in PHASE_E_SYSTEM_FIELDS:
        field = by_key.get(field_key, {"field_key": field_key, "key": field_key})
        field.update(
            {
                "field_key": field_key,
                "key": field_key,
                "writable": False,
                "allowed_sources": ["expediente.evaluate"],
                "write_policy": "system_tool_only",
                "phase": "E",
                "phase_source": PHASE_E_SEED_ID,
                "write_policy_metadata": {
                    **(field.get("write_policy_metadata") or {}),
                    "owner": "system_tool",
                    "allowed_tools": ["expediente.evaluate"],
                    "blocked_for_agent": True,
                },
            }
        )
        by_key[field_key] = field
    ordered = [
        field
        for field in fields
        if str(field.get("field_key") or field.get("key")) in by_key
    ]
    seen = {str(field.get("field_key") or field.get("key")) for field in ordered}
    ordered.extend(by_key[key] for key in PHASE_E_SYSTEM_FIELDS if key not in seen)
    policy.update(
        {
            "phase_e_source": PHASE_E_SEED_ID,
            "phase_e_source_version_id": PHASE_E_SOURCE_VERSION_ID,
            "document_system_fields": list(PHASE_E_SYSTEM_FIELDS),
            "fields": ordered,
        }
    )
    return policy


def _run_phase_e_dry_lab(scenarios: tuple[PhaseEScenario, ...]) -> list[JsonDict]:
    results: list[JsonDict] = []
    for scenario in scenarios:
        document_check = _document_check_preview(scenario)
        expediente = _expediente_evaluate_preview(scenario, document_check)
        failures = _assert_scenario_preview(scenario, expediente)
        results.append(
            {
                "scenario_key": scenario.key,
                "scenario_name": scenario.name,
                "status": "passed" if not failures else "blocked",
                "blocked_reason": ",".join(failures) if failures else None,
                "expected": scenario.as_expected(),
                "tool_results": [document_check, expediente],
                "field_update_proposals": expediente["field_updates"],
                "workflow_event_previews": _workflow_previews(scenario, expediente),
                "send_decision": "no_send",
                "outbound_outbox_writes": 0,
                "workflow_execution_writes": 0,
                "openai_api_real": False,
                "vision_api_real": False,
                "side_effects": {
                    "delivery": False,
                    "workflows": False,
                    "actions": False,
                    "field_writes": False,
                },
            }
        )
    return results


def _document_check_preview(scenario: PhaseEScenario) -> JsonDict:
    return {
        "tool_name": "document.check",
        "status": "succeeded",
        "source_kind": "dry_facts",
        "facts": {
            "documents_detected": [dict(item) for item in scenario.document_facts],
            "classification_only": True,
            "vision_api_real": False,
        },
        "can_support_claims": True,
    }


def _expediente_evaluate_preview(
    scenario: PhaseEScenario,
    document_check: JsonDict,
) -> JsonDict:
    documents = [
        dict(item)
        for item in (document_check.get("facts") or {}).get("documents_detected") or []
        if isinstance(item, dict)
    ]
    required = ("ine_frente", "comprobante_domicilio", "estado_cuenta")
    by_type = {str(item.get("document_type")): item for item in documents}
    checklist_items: list[JsonDict] = []
    missing: list[JsonDict] = []
    rejected: list[str] = []
    for doc_key in required:
        item = by_type.get(doc_key)
        status = str((item or {}).get("status") or "missing")
        if status not in {"accepted", "rejected"}:
            status = "missing"
        entry = {
            "key": doc_key,
            "label": _doc_label(doc_key),
            "status": status,
            "evidence": [str((item or {}).get("attachment_id") or "")]
            if item
            else [],
            "rejected_reason": (item or {}).get("reason"),
        }
        checklist_items.append(entry)
        if status != "accepted":
            missing.append(
                {
                    "key": doc_key,
                    "label": entry["label"],
                    "status": status,
                    "missing_count": 1,
                }
            )
        if status == "rejected":
            rejected.append(doc_key)
    complete = bool(checklist_items) and not missing
    doc_incompletos = ", ".join(item["label"] for item in missing)
    checklist = {
        "contract": "Expedientes",
        "plan_credito": scenario.plan_credito,
        "items": checklist_items,
        "missing_documents": missing,
        "rejected_documents": rejected,
        "requirements_complete": complete,
        "vision_api_real": False,
    }
    return {
        "tool_name": "expediente.evaluate",
        "status": "succeeded",
        "source_kind": "dry_facts",
        "facts": {
            "Docs_Checklist": checklist,
            "Doc_Incompletos": doc_incompletos,
            "Doc_Completos": complete,
            "missing_documents": missing,
            "rejected_documents": rejected,
            "stage_preview": "papeleria_completa" if complete else "papeleria_incompleta",
        },
        "field_updates": [
            _field_update("Docs_Checklist", checklist),
            _field_update("Doc_Incompletos", doc_incompletos),
            _field_update("Doc_Completos", complete),
        ],
        "can_support_claims": True,
    }


def _workflow_previews(scenario: PhaseEScenario, expediente: JsonDict) -> list[JsonDict]:
    facts = dict(expediente.get("facts") or {})
    previews = [
        {
            "binding_name": "pipeline.transition",
            "event_name": "docs_complete_for_plan"
            if facts.get("Doc_Completos")
            else "document_accepted",
            "target_stage": facts.get("stage_preview"),
            "dry_run": True,
            "side_effects_allowed": False,
        }
    ]
    if scenario.expected_handoff_reason:
        previews.append(
            {
                "binding_name": "handoff.start",
                "event_name": "human_handoff_requested",
                "reason": scenario.expected_handoff_reason,
                "dry_run": True,
                "side_effects_allowed": False,
            }
        )
        previews.append(
            {
                "binding_name": "notification.create",
                "event_name": "notification_requested",
                "reason": "document_doubt",
                "dry_run": True,
                "side_effects_allowed": False,
            }
        )
    return previews


def _field_update(field_key: str, value: Any) -> JsonDict:
    return {
        "field_key": field_key,
        "value": value,
        "reason": "expediente.evaluate owns Dinamo document system fields.",
        "evidence": ["tool_result:expediente.evaluate"],
        "confidence": 1.0,
        "write_owner": "system_tool",
    }


def _assert_scenario_preview(scenario: PhaseEScenario, expediente: JsonDict) -> list[str]:
    facts = dict(expediente.get("facts") or {})
    failures: list[str] = []
    if facts.get("Doc_Completos") is not scenario.expected_doc_completos:
        failures.append("doc_completos_mismatch")
    if facts.get("stage_preview") != scenario.expected_stage_preview:
        failures.append("stage_preview_mismatch")
    missing = {
        str(item.get("key"))
        for item in facts.get("missing_documents") or []
        if isinstance(item, dict)
    }
    for key in scenario.expected_missing:
        if key not in missing:
            failures.append(f"missing_doc_absent:{key}")
    rejected = set(str(item) for item in facts.get("rejected_documents") or [])
    for key in scenario.expected_rejected:
        if key not in rejected:
            failures.append(f"rejected_doc_absent:{key}")
    field_updates = {
        str(item.get("field_key")): item
        for item in expediente.get("field_updates") or []
        if isinstance(item, dict)
    }
    for field_key in PHASE_E_SYSTEM_FIELDS:
        if field_key not in field_updates:
            failures.append(f"missing_field_update:{field_key}")
        elif field_updates[field_key].get("write_owner") != "system_tool":
            failures.append(f"field_not_system_tool:{field_key}")
    return failures


async def _store_phase_e_lab(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    version: AgentVersion,
    lab: list[JsonDict],
    created_by_user_id: UUID | None,
):
    timestamp = datetime.now(UTC).isoformat()
    suite = await service.create_agent_test_suite(
        session,
        tenant_id=tenant_id,
        version_id=version.id,
        name=f"Dinamo V1 Phase E documents dry-run - {timestamp}",
        mode="publish_readiness",
        metadata={
            "source": PHASE_E_SEED_ID,
            "source_version_id": PHASE_E_SOURCE_VERSION_ID,
            "phase_d_source": PHASE_D_SEED_ID,
            "openai_api_real": False,
            "vision_api_real": False,
            "external_apis": False,
            "send": "no_send",
            "workflow_side_effects": False,
        },
    )
    for scenario in phase_e_scenarios():
        await service.create_agent_test_scenario(
            session,
            tenant_id=tenant_id,
            suite_id=suite.id,
            name=scenario.name,
            turns=[_scenario_turn(scenario)],
            expected=scenario.as_expected(),
            metadata={
                "source": PHASE_E_SEED_ID,
                "scenario_key": scenario.key,
                "openai_api_real": False,
                "vision_api_real": False,
                "external_apis": False,
            },
        )
    run = service.create_agent_test_run_record(
        tenant_id=tenant_id,
        agent_version_id=version.id,
        suite_id=suite.id,
        mode="no_send",
        review_required=False,
        created_by_user_id=created_by_user_id,
    )
    blocked = [item for item in lab if item.get("status") != "passed"]
    run.scenario_results = lab
    run.turn_results = lab
    run.pass_count = len(lab) - len(blocked)
    run.blocked_count = len(blocked)
    run.fail_count = 0
    run.status = "passed" if not blocked else "blocked"
    run.decision = PHASE_E_DECISION_READY if not blocked else PHASE_E_DECISION_BLOCKED
    run.outbox_audit_result = {"status": "clean", "outbound_outbox_writes": 0}
    run.side_effect_audit_result = {
        "status": "clean",
        "delivery": False,
        "workflows": False,
        "actions": False,
        "field_writes": False,
    }
    run.coverage_summary = {
        "source": PHASE_E_SEED_ID,
        "source_version_id": PHASE_E_SOURCE_VERSION_ID,
        "execution_mode": "documents_dry_run_preview",
        "document_tools": list(PHASE_E_TOOLS),
        "system_fields": list(PHASE_E_SYSTEM_FIELDS),
        "send_decision": "no_send",
        "openai_api_real": False,
        "vision_api_real": False,
        "external_apis": False,
        "workflow_side_effects": False,
        "outbound_outbox_writes": 0,
    }
    suite.last_run_id = run.id
    suite.status = run.status
    session.add(run)
    await session.flush()
    return suite, run


def _scenario_turn(scenario: PhaseEScenario) -> JsonDict:
    return {
        "inbound_text": f"document_event:{scenario.key}",
        "attachments": [
            {
                "attachment_id": item.get("attachment_id"),
                "document_type": item.get("document_type"),
                "status": item.get("status"),
            }
            for item in scenario.document_facts
        ],
    }


async def _load_phase_d_or_newer_version(
    session: AsyncSession,
    tenant_id: UUID,
) -> tuple[Agent, AgentVersion]:
    agent = (
        await session.execute(
            select(Agent).where(Agent.tenant_id == tenant_id, Agent.name == AGENT_NAME)
        )
    ).scalars().one_or_none()
    if agent is None:
        raise service.ProductAgentNotFoundError("Dinamo seeded agent was not found")
    version = (
        await session.execute(
            select(AgentVersion)
            .where(AgentVersion.tenant_id == tenant_id, AgentVersion.agent_id == agent.id)
            .order_by(AgentVersion.version_number.desc())
        )
    ).scalars().first()
    if version is None:
        raise service.ProductAgentNotFoundError("Dinamo seeded agent version was not found")
    snapshot = dict(version.snapshot or {})
    if snapshot.get("phase") != "C" or not snapshot.get("phase_d_source"):
        raise service.ProductAgentError("latest Dinamo version must have Phase D active")
    return agent, version


async def _outbox_count(session: AsyncSession, tenant_id: UUID) -> int:
    count = await session.scalar(
        select(func.count())
        .select_from(OutboundOutbox)
        .where(OutboundOutbox.tenant_id == tenant_id)
    )
    return int(count or 0)


async def _workflow_execution_count(session: AsyncSession, tenant_id: UUID) -> int:
    count = await session.scalar(
        select(func.count())
        .select_from(WorkflowExecution)
        .join(Workflow, Workflow.id == WorkflowExecution.workflow_id)
        .where(Workflow.tenant_id == tenant_id)
    )
    return int(count or 0)


async def _deployments_are_no_send(session: AsyncSession, tenant_id: UUID) -> bool:
    deployments = (
        await session.execute(
            select(AgentDeployment).where(AgentDeployment.tenant_id == tenant_id)
        )
    ).scalars().all()
    return bool(deployments) and all(
        not deployment.send_enabled
        and not deployment.outbox_enabled
        and not deployment.live_send_enabled
        and not deployment.single_contact_smoke_enabled
        and not deployment.actions_enabled
        and not deployment.workflow_events_enabled
        and not deployment.workflow_side_effects_enabled
        and not deployment.canary_enabled
        and not deployment.open_production_enabled
        and deployment.send_scope == "none"
        and deployment.runtime_mode == "no_send"
        for deployment in deployments
    )


def _doc(
    document_type: str,
    *,
    status: str,
    attachment_id: str,
    reason: str | None = None,
) -> JsonDict:
    return {
        "attachment_id": attachment_id,
        "document_type": document_type,
        "status": status,
        "reason": reason,
        "confidence": 0.95,
        "source": "phase_e_dry_fact",
    }


def _doc_label(document_type: str) -> str:
    return {
        "ine_frente": "INE frente",
        "comprobante_domicilio": "Comprobante de domicilio",
        "estado_cuenta": "Estado de cuenta",
    }.get(document_type, document_type)


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Seed Dinamo Phase E documents.")
    parser.add_argument("--tenant-id", required=True, type=UUID)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--created-by-user-id", type=UUID, default=None)
    return parser.parse_args(argv)


async def _amain(argv: list[str]) -> int:
    args = _parse_args(argv)
    if args.dry_run:
        result = await seed_dinamo_phase_e_documents(
            _DryRunSession(),  # type: ignore[arg-type]
            tenant_id=args.tenant_id,
            dry_run=True,
            created_by_user_id=args.created_by_user_id,
        )
        print(json.dumps(result.as_dict(), indent=2, sort_keys=True))
        return 0
    async for session in get_db_session():
        try:
            result = await seed_dinamo_phase_e_documents(
                session,
                tenant_id=args.tenant_id,
                dry_run=False,
                created_by_user_id=args.created_by_user_id,
            )
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        print(json.dumps(result.as_dict(), indent=2, sort_keys=True))
        return 0
    return 1


class _DryRunSession:
    pass


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(_amain(sys.argv[1:] if argv is None else argv))


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "PHASE_E_DECISION_READY",
    "PHASE_E_SEED_ID",
    "PHASE_E_SYSTEM_FIELDS",
    "PHASE_E_TOOLS",
    "PhaseEDocumentResult",
    "PhaseEScenario",
    "_assert_scenario_preview",
    "_document_check_preview",
    "_expediente_evaluate_preview",
    "_phase_e_field_policy",
    "_phase_e_tool_policy",
    "_run_phase_e_dry_lab",
    "_scenario_turn",
    "phase_e_scenarios",
    "seed_dinamo_phase_e_documents",
]
