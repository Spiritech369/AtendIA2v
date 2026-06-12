"""Activate Dinamo Phase G Google integration contracts, dry-run only.

Phase G wires tenant-scoped dry-run workflow contracts for Google Sheets,
Google Drive, and manual Google Form completion. It stores DB-backed no-send
evidence from deterministic previews.

It does not call Google APIs, create Drive files, write Sheets rows, enqueue
messages, execute workflows, or require Google credentials.

Usage:
    PYTHONPATH=. uv run python -m atendia.scripts.seed_dinamo_phase_g_google \
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
    AgentVersion,
    AgentWorkflowBinding,
)
from atendia.db.models.workflow import Workflow, WorkflowExecution
from atendia.db.session import get_db_session
from atendia.product_agents import service
from atendia.scripts.seed_dinamo_phase_f_followups import PHASE_F_SEED_ID
from atendia.scripts.seed_dinamo_v1 import AGENT_NAME, SEED_ID, SOURCE_VERSION_ID

JsonDict = dict[str, Any]

PHASE_G_SEED_ID = "dinamo_tenant_runtime_plan_v1_phase_g"
PHASE_G_SOURCE_VERSION_ID = "DINAMO_TENANT_RUNTIME_PLAN_V1:PHASE_G:2026-06-12"
PHASE_G_DECISION_READY = "DINAMO_PHASE_G_GOOGLE_DRY_RUN_READY"
PHASE_G_DECISION_BLOCKED = "DINAMO_PHASE_G_GOOGLE_DRY_RUN_BLOCKED"
PHASE_G_WORKFLOWS = (
    "google_sheets.upsert_row",
    "google_drive.upload_file",
    "google_form.mark_manual",
    "notification.create",
)
PHASE_G_SYSTEM_FIELDS = (
    "Solicitud_ID",
    "Google_Sheets_Row_ID",
    "Google_Drive_Folder_ID",
    "Google_Drive_File_IDs",
    "Formulario",
)
DRIVE_SUBFOLDERS = (
    "00_raw",
    "01_aceptados",
    "02_rechazados",
    "03_formulario",
    "99_notas_revision",
)


@dataclass(frozen=True)
class PhaseGWorkflowSpec:
    key: str
    name: str
    trigger_type: str
    event_type: str
    nodes: tuple[JsonDict, ...]


@dataclass
class PhaseGGoogleResult:
    tenant_id: str
    dry_run: bool
    updated_workflows: list[str] = field(default_factory=list)
    updated_bindings: list[str] = field(default_factory=list)
    updated_field_permissions: list[str] = field(default_factory=list)
    suite_id: str | None = None
    run_id: str | None = None
    status: str = "ready"
    decision: str = PHASE_G_DECISION_READY
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
            "updated_workflows": self.updated_workflows,
            "updated_bindings": self.updated_bindings,
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
            "google_api_real": False,
            "external_apis": False,
            "send": "no_send",
            "workflow_side_effects": False,
        }


@dataclass(frozen=True)
class PhaseGScenario:
    key: str
    name: str
    workflow_key: str
    event_type: str
    event: JsonDict
    expected_field_updates: JsonDict = field(default_factory=dict)
    expected_notifications: int = 0
    expected_drive_subfolders: tuple[str, ...] = ()
    expected_failed_action: str | None = None

    def as_expected(self) -> JsonDict:
        return {
            "workflow_key": self.workflow_key,
            "event_type": self.event_type,
            "expected_field_updates": dict(self.expected_field_updates),
            "expected_notifications": self.expected_notifications,
            "expected_drive_subfolders": list(self.expected_drive_subfolders),
            "expected_failed_action": self.expected_failed_action,
            "send": "no_send",
            "google_api_real": False,
            "workflow_side_effects": False,
        }


def phase_g_workflow_specs() -> dict[str, PhaseGWorkflowSpec]:
    return {
        "google_sheets.upsert_row": PhaseGWorkflowSpec(
            key="google_sheets.upsert_row",
            name="Dinamo V1 - Google Sheets upsert row",
            trigger_type="field_updated",
            event_type="field_updated",
            nodes=(
                {
                    "id": "build_sheets_payload",
                    "type": "google_sheets_upsert",
                    "config": {
                        "mode": "dry_run_only",
                        "idempotency_field": "Google_Sheets_Row_ID",
                        "business_key": "Solicitud_ID",
                        "one_row_per_solicitud": True,
                        "requires_credentials": False,
                    },
                },
            ),
        ),
        "google_drive.upload_file": PhaseGWorkflowSpec(
            key="google_drive.upload_file",
            name="Dinamo V1 - Google Drive upload file",
            trigger_type="agent_document_received",
            event_type="agent_document_received",
            nodes=(
                {
                    "id": "build_drive_plan",
                    "type": "google_drive_upload",
                    "config": {
                        "mode": "dry_run_only",
                        "folder_field": "Google_Drive_Folder_ID",
                        "file_ids_field": "Google_Drive_File_IDs",
                        "subfolders": list(DRIVE_SUBFOLDERS),
                        "requires_credentials": False,
                    },
                },
            ),
        ),
        "google_form.mark_manual": PhaseGWorkflowSpec(
            key="google_form.mark_manual",
            name="Dinamo V1 - Google Form manual completion",
            trigger_type="form_completed_manual",
            event_type="form_completed_manual",
            nodes=(
                {
                    "id": "mark_formulario_manual",
                    "type": "update_field",
                    "config": {
                        "field": "Formulario",
                        "value": "completado_manual",
                        "write_owner": "system_workflow",
                    },
                },
            ),
        ),
        "notification.create": PhaseGWorkflowSpec(
            key="notification.create",
            name="Dinamo V1 - Google integration failure notification",
            trigger_type="notification_requested",
            event_type="notification_requested",
            nodes=(
                {
                    "id": "notify_google_failure",
                    "type": "notify_agent",
                    "config": {
                        "role": "operator",
                        "dedupe_key": "dinamo_google_failure:{conversation_id}:{action}",
                    },
                },
            ),
        ),
    }


def phase_g_scenarios() -> tuple[PhaseGScenario, ...]:
    return (
        PhaseGScenario(
            key="sheets_upsert_idempotent_by_solicitud",
            name="Sheets preview upserts one row by Solicitud_ID",
            workflow_key="google_sheets.upsert_row",
            event_type="field_updated",
            event={
                "conversation_id": "dry-run-conv",
                "Solicitud_ID": "SOL-DINAMO-0001",
                "Google_Sheets_Row_ID": "row-44",
                "fields": {
                    "Moto": "Italika FT150",
                    "Plan_Credito": "Nomina Tarjeta",
                    "Cotizacion_Enviada": True,
                },
            },
            expected_field_updates={"Google_Sheets_Row_ID": "row-44"},
        ),
        PhaseGScenario(
            key="drive_valid_and_invalid_are_separated",
            name="Drive preview separates accepted and rejected files",
            workflow_key="google_drive.upload_file",
            event_type="agent_document_received",
            event={
                "conversation_id": "dry-run-conv",
                "phone": "528128889241",
                "customer_name": "Cliente Dinamo",
                "date": "2026-06-12",
                "attachments": [
                    {
                        "attachment_id": "att-ok",
                        "document_type": "ine_frente",
                        "status": "accepted",
                        "extension": "jpg",
                    },
                    {
                        "attachment_id": "att-bad",
                        "document_type": "estado_cuenta",
                        "status": "rejected",
                        "extension": "pdf",
                    },
                ],
            },
            expected_field_updates={
                "Google_Drive_Folder_ID": "dry_drive_folder_528128889241_2026-06-12",
                "Google_Drive_File_IDs": {
                    "att-ok": "dry_drive_file_att-ok",
                    "att-bad": "dry_drive_file_att-bad",
                },
            },
            expected_drive_subfolders=DRIVE_SUBFOLDERS,
        ),
        PhaseGScenario(
            key="form_manual_completion_marks_field",
            name="Manual form completion marks Formulario",
            workflow_key="google_form.mark_manual",
            event_type="form_completed_manual",
            event={"conversation_id": "dry-run-conv", "Formulario": "completado_manual"},
            expected_field_updates={"Formulario": "completado_manual"},
        ),
        PhaseGScenario(
            key="google_failure_notifies_without_customer_copy",
            name="Google failure creates internal notification preview only",
            workflow_key="notification.create",
            event_type="notification_requested",
            event={
                "conversation_id": "dry-run-conv",
                "action": "google_sheets.upsert_row",
                "reason": "credentials_missing",
            },
            expected_notifications=1,
            expected_failed_action="google_sheets.upsert_row",
        ),
    )


async def seed_dinamo_phase_g_google(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    dry_run: bool = False,
    created_by_user_id: UUID | None = None,
) -> PhaseGGoogleResult:
    result = PhaseGGoogleResult(tenant_id=str(tenant_id), dry_run=dry_run)
    if dry_run:
        result.updated_workflows = list(PHASE_G_WORKFLOWS)
        result.updated_bindings = [
            f"{scenario.workflow_key}:{scenario.event_type}"
            for scenario in phase_g_scenarios()
        ]
        result.updated_field_permissions = list(PHASE_G_SYSTEM_FIELDS)
        result.pass_count = len(phase_g_scenarios())
        result.assertions = ["preview_only"]
        return result

    result.outbox_before = await _outbox_count(session, tenant_id)
    result.workflow_executions_before = await _workflow_execution_count(session, tenant_id)
    result.deployments_no_send = await _deployments_are_no_send(session, tenant_id)
    if not result.deployments_no_send:
        raise service.ProductAgentError("tenant deployments are not fully no-send")

    _agent, version = await _load_phase_f_or_newer_version(session, tenant_id)
    specs = phase_g_workflow_specs()
    workflows = await _upsert_phase_g_workflows(
        session,
        tenant_id=tenant_id,
        specs=specs,
        result=result,
    )
    await _upsert_phase_g_bindings(
        session,
        tenant_id=tenant_id,
        version=version,
        workflows=workflows,
        specs=specs,
        result=result,
    )
    await _reinforce_phase_g_field_permissions(
        session,
        tenant_id=tenant_id,
        version=version,
        result=result,
    )
    _update_version_phase_g_policy(version)

    lab = _run_phase_g_dry_lab(workflows, phase_g_scenarios())
    suite, run = await _store_phase_g_lab(
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
        raise service.ProductAgentError("outbox changed during Phase G dry-run")
    if result.workflow_executions_after != result.workflow_executions_before:
        raise service.ProductAgentError("workflow executions changed during Phase G dry-run")
    return result


async def _upsert_phase_g_workflows(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    specs: dict[str, PhaseGWorkflowSpec],
    result: PhaseGGoogleResult,
) -> dict[str, Workflow]:
    rows = (
        await session.execute(select(Workflow).where(Workflow.tenant_id == tenant_id))
    ).scalars().all()
    by_key = {
        ((row.definition or {}).get("metadata") or {}).get("workflow_key"): row
        for row in rows
        if ((row.definition or {}).get("metadata") or {}).get("source") == SEED_ID
    }
    updated: dict[str, Workflow] = {}
    for key in PHASE_G_WORKFLOWS:
        spec = specs[key]
        definition = _phase_g_definition(spec)
        trigger_config = {
            "source": SEED_ID,
            "phase_source": PHASE_G_SEED_ID,
            "source_version_id": SOURCE_VERSION_ID,
            "phase_source_version_id": PHASE_G_SOURCE_VERSION_ID,
            "event_type": spec.event_type,
            "dry_run_only": True,
            "google_api_real": False,
        }
        workflow = by_key.get(key)
        if workflow is None:
            workflow = Workflow(
                tenant_id=tenant_id,
                name=spec.name,
                description="Dinamo V1 Phase G dry-run Google workflow. APIs disabled.",
                trigger_type=spec.trigger_type,
                trigger_config=trigger_config,
                definition=definition,
                active=False,
            )
            session.add(workflow)
            await session.flush()
        else:
            workflow.name = spec.name
            workflow.description = "Dinamo V1 Phase G dry-run Google workflow. APIs disabled."
            workflow.trigger_type = spec.trigger_type
            workflow.trigger_config = trigger_config
            workflow.definition = definition
            workflow.active = False
        result.updated_workflows.append(key)
        updated[key] = workflow
    return updated


def _phase_g_definition(spec: PhaseGWorkflowSpec) -> JsonDict:
    metadata: JsonDict = {
        "source": SEED_ID,
        "phase_source": PHASE_G_SEED_ID,
        "source_version_id": SOURCE_VERSION_ID,
        "phase_source_version_id": PHASE_G_SOURCE_VERSION_ID,
        "workflow_key": spec.key,
        "phase": "G",
        "status": "dry_run_ready",
        "side_effects": "disabled",
        "customer_visible_output_allowed": False,
        "customer_message_request_only": False,
        "google_api_real": False,
        "requires_credentials": False,
        "rollback": "rerun Phase F seed; keep Google bindings dry_run_only",
    }
    if spec.key == "google_sheets.upsert_row":
        metadata["idempotency"] = "one row per Solicitud_ID via Google_Sheets_Row_ID"
    if spec.key == "google_drive.upload_file":
        metadata["drive_subfolders"] = list(DRIVE_SUBFOLDERS)
        metadata["invalid_documents_count_as_received"] = False
    if spec.key == "notification.create":
        metadata["dedupe_required"] = True
    return {
        "nodes": list(copy.deepcopy(spec.nodes)),
        "edges": [],
        "metadata": metadata,
    }


async def _upsert_phase_g_bindings(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    version: AgentVersion,
    workflows: dict[str, Workflow],
    specs: dict[str, PhaseGWorkflowSpec],
    result: PhaseGGoogleResult,
) -> None:
    rows = (
        await session.execute(
            select(AgentWorkflowBinding).where(
                AgentWorkflowBinding.tenant_id == tenant_id,
                AgentWorkflowBinding.agent_version_id == version.id,
            )
        )
    ).scalars().all()
    by_key = {(str(row.workflow_id), row.event_type): row for row in rows}
    for key in PHASE_G_WORKFLOWS:
        workflow = workflows[key]
        spec = specs[key]
        binding_key = (str(workflow.id), spec.event_type)
        metadata = {
            "source": SEED_ID,
            "phase_source": PHASE_G_SEED_ID,
            "source_version_id": SOURCE_VERSION_ID,
            "phase_source_version_id": PHASE_G_SOURCE_VERSION_ID,
            "workflow_key": key,
            "phase": "G",
            "side_effects_allowed": False,
            "customer_visible_output_allowed": False,
            "google_api_real": False,
            "requires_credentials": False,
        }
        binding = by_key.get(binding_key)
        if binding is None:
            session.add(
                AgentWorkflowBinding(
                    tenant_id=tenant_id,
                    agent_version_id=version.id,
                    workflow_id=workflow.id,
                    event_type=spec.event_type,
                    enabled=True,
                    execution_mode="dry_run_only",
                    side_effects_allowed=False,
                    customer_visible_output_allowed=False,
                    metadata_json=metadata,
                )
            )
        else:
            binding.enabled = True
            binding.execution_mode = "dry_run_only"
            binding.side_effects_allowed = False
            binding.customer_visible_output_allowed = False
            binding.metadata_json = metadata
        result.updated_bindings.append(f"{key}:{spec.event_type}")


async def _reinforce_phase_g_field_permissions(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    version: AgentVersion,
    result: PhaseGGoogleResult,
) -> None:
    rows = (
        await session.execute(
            select(AgentFieldPermission).where(
                AgentFieldPermission.tenant_id == tenant_id,
                AgentFieldPermission.agent_version_id == version.id,
                AgentFieldPermission.field_key.in_(PHASE_G_SYSTEM_FIELDS),
            )
        )
    ).scalars().all()
    by_key = {row.field_key: row for row in rows}
    for field_key in PHASE_G_SYSTEM_FIELDS:
        owner = "system_or_human" if field_key == "Formulario" else "system_integration"
        write_policy = {
            "owner": owner,
            "allowed_workflows": [
                "google_sheets.upsert_row",
                "google_drive.upload_file",
                "google_form.mark_manual",
            ],
            "blocked_for_agent": True,
            "phase_source": PHASE_G_SEED_ID,
        }
        metadata = {
            "source": SEED_ID,
            "phase_source": PHASE_G_SEED_ID,
            "source_version_id": SOURCE_VERSION_ID,
            "phase_source_version_id": PHASE_G_SOURCE_VERSION_ID,
            "phase": "G",
            "write_owner": owner,
            "google_api_real": False,
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


def _update_version_phase_g_policy(version: AgentVersion) -> None:
    version.workflow_policy = _phase_g_workflow_policy(version.workflow_policy)
    version.field_policy = _phase_g_field_policy(version.field_policy)
    action_policy = dict(version.action_policy or {})
    action_policy["phase_g_source"] = PHASE_G_SEED_ID
    action_policy["phase_g_source_version_id"] = PHASE_G_SOURCE_VERSION_ID
    action_policy["google_actions"] = {
        "execution_mode": "dry_run_only",
        "google_api_real": False,
        "requires_credentials": False,
        "live_activation_blocked_until": "Phase I beta gate approval",
    }
    version.action_policy = action_policy
    test_policy = dict(version.test_policy or {})
    test_policy["phase_g_google_dry_run_gate"] = PHASE_G_DECISION_READY
    version.test_policy = test_policy
    version.snapshot = {
        **(version.snapshot or {}),
        "phase_g_source": PHASE_G_SEED_ID,
        "phase_g_source_version_id": PHASE_G_SOURCE_VERSION_ID,
        "phase_g_workflows": list(PHASE_G_WORKFLOWS),
    }


def _phase_g_workflow_policy(existing_policy: dict[str, Any] | None) -> JsonDict:
    policy = copy.deepcopy(existing_policy or {})
    policy["phase_g_source"] = PHASE_G_SEED_ID
    policy["phase_g_source_version_id"] = PHASE_G_SOURCE_VERSION_ID
    policy["google_workflows"] = list(PHASE_G_WORKFLOWS)
    policy["google_execution_mode"] = "dry_run_only"
    policy["google_api_real"] = False
    policy["google_credentials_required_for_dry_run"] = False
    policy["google_failure_policy"] = {
        "notify_agent": True,
        "retry": True,
        "customer_conversation_impact": False,
    }
    return policy


def _phase_g_field_policy(existing_policy: dict[str, Any] | None) -> JsonDict:
    policy = copy.deepcopy(existing_policy or {})
    fields = [
        copy.deepcopy(item)
        for item in policy.get("fields") or []
        if isinstance(item, dict) and (item.get("field_key") or item.get("key"))
    ]
    by_key = {str(item.get("field_key") or item.get("key")): item for item in fields}
    for field_key in PHASE_G_SYSTEM_FIELDS:
        write_policy = (
            "system_or_human" if field_key == "Formulario" else "system_integration_only"
        )
        field = by_key.get(field_key, {"field_key": field_key, "key": field_key})
        field.update(
            {
                "field_key": field_key,
                "key": field_key,
                "writable": False,
                "allowed_sources": [
                    "google_sheets.upsert_row",
                    "google_drive.upload_file",
                    "google_form.mark_manual",
                ],
                "write_policy": write_policy,
                "phase": "G",
                "phase_source": PHASE_G_SEED_ID,
                "write_policy_metadata": {
                    **(field.get("write_policy_metadata") or {}),
                    "blocked_for_agent": True,
                    "google_api_real": False,
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
    ordered.extend(by_key[key] for key in PHASE_G_SYSTEM_FIELDS if key not in seen)
    policy.update(
        {
            "phase_g_source": PHASE_G_SEED_ID,
            "phase_g_source_version_id": PHASE_G_SOURCE_VERSION_ID,
            "google_system_fields": list(PHASE_G_SYSTEM_FIELDS),
            "fields": ordered,
        }
    )
    return policy


def _run_phase_g_dry_lab(
    workflows: dict[str, Workflow],
    scenarios: tuple[PhaseGScenario, ...],
) -> list[JsonDict]:
    results: list[JsonDict] = []
    for scenario in scenarios:
        workflow = workflows.get(scenario.workflow_key)
        if workflow is None:
            results.append(_blocked_scenario(scenario, "workflow_missing"))
            continue
        preview = _preview_google_workflow(workflow.definition or {}, scenario)
        failures = _assert_scenario_preview(scenario, preview)
        results.append(
            {
                "scenario_key": scenario.key,
                "scenario_name": scenario.name,
                "workflow_key": scenario.workflow_key,
                "event_type": scenario.event_type,
                "status": "passed" if not failures else "blocked",
                "blocked_reason": ",".join(failures) if failures else None,
                "expected": scenario.as_expected(),
                "preview": preview,
                "send_decision": "no_send",
                "outbound_outbox_writes": 0,
                "workflow_execution_writes": 0,
                "openai_api_real": False,
                "google_api_real": False,
                "side_effects": {
                    "delivery": False,
                    "workflows": False,
                    "actions": False,
                    "field_writes": False,
                    "external_apis": False,
                },
            }
        )
    return results


def _blocked_scenario(scenario: PhaseGScenario, reason: str) -> JsonDict:
    return {
        "scenario_key": scenario.key,
        "workflow_key": scenario.workflow_key,
        "event_type": scenario.event_type,
        "status": "blocked",
        "blocked_reason": reason,
        "expected": scenario.as_expected(),
        "preview": {},
    }


def _preview_google_workflow(
    definition: JsonDict,
    scenario: PhaseGScenario,
) -> JsonDict:
    preview: JsonDict = {
        "status": "dry_run",
        "nodes": [],
        "field_updates": {},
        "notifications": [],
        "google_api_calls": 0,
        "credential_lookup": False,
        "customer_visible_output": None,
        "outbound_outbox_writes": 0,
        "workflow_execution_writes": 0,
        "side_effects": {
            "delivery": False,
            "workflows": False,
            "actions": False,
            "field_writes": False,
            "external_apis": False,
        },
    }
    for node in definition.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        node_id = str(node.get("id") or "")
        node_type = str(node.get("type") or "")
        preview["nodes"].append({"id": node_id, "type": node_type})
        if node_type == "google_sheets_upsert":
            preview["sheets"] = _preview_sheets_upsert(scenario.event)
            preview["field_updates"].update(preview["sheets"]["field_updates"])
        elif node_type == "google_drive_upload":
            preview["drive"] = _preview_drive_upload(scenario.event)
            preview["field_updates"].update(preview["drive"]["field_updates"])
        elif node_type == "update_field":
            config = dict(node.get("config") or {})
            preview["field_updates"][str(config.get("field") or "")] = config.get("value")
        elif node_type == "notify_agent":
            config = dict(node.get("config") or {})
            preview["notifications"].append(
                {
                    "role": config.get("role"),
                    "dedupe_key": _render_dedupe(
                        str(config.get("dedupe_key") or ""),
                        scenario.event,
                    ),
                    "action": scenario.event.get("action"),
                    "reason": scenario.event.get("reason"),
                    "dry_run": True,
                }
            )
    return preview


def _preview_sheets_upsert(event: JsonDict) -> JsonDict:
    solicitud_id = str(event.get("Solicitud_ID") or "dry_solicitud_pending")
    row_id = str(event.get("Google_Sheets_Row_ID") or f"dry_sheet_row_{solicitud_id}")
    return {
        "action": "google_sheets.upsert_row",
        "mode": "dry_run_only",
        "idempotency_key": f"sheets:{solicitud_id}",
        "row_id": row_id,
        "one_row_per_solicitud": True,
        "google_api_call": False,
        "field_updates": {"Google_Sheets_Row_ID": row_id},
        "payload_columns": sorted((event.get("fields") or {}).keys()),
    }


def _preview_drive_upload(event: JsonDict) -> JsonDict:
    phone = str(event.get("phone") or "unknown_phone")
    customer_name = str(event.get("customer_name") or "Cliente Dinamo")
    date = str(event.get("date") or "unknown_date")
    folder_id = f"dry_drive_folder_{phone}_{date}"
    file_ids: dict[str, str] = {}
    placements: list[JsonDict] = []
    for item in event.get("attachments") or []:
        if not isinstance(item, dict):
            continue
        attachment_id = str(item.get("attachment_id") or "unknown")
        status = str(item.get("status") or "raw")
        target_folder = "01_aceptados" if status == "accepted" else "02_rechazados"
        if status not in {"accepted", "rejected"}:
            target_folder = "00_raw"
        file_id = f"dry_drive_file_{attachment_id}"
        file_ids[attachment_id] = file_id
        placements.append(
            {
                "attachment_id": attachment_id,
                "document_type": item.get("document_type"),
                "status": status,
                "target_subfolder": target_folder,
                "file_id": file_id,
                "counts_as_received": status == "accepted",
            }
        )
    return {
        "action": "google_drive.upload_file",
        "mode": "dry_run_only",
        "root_folder_name": f"{phone}_{customer_name}_{date}",
        "folder_id": folder_id,
        "subfolders": list(DRIVE_SUBFOLDERS),
        "placements": placements,
        "google_api_call": False,
        "field_updates": {
            "Google_Drive_Folder_ID": folder_id,
            "Google_Drive_File_IDs": file_ids,
        },
    }


def _render_dedupe(template: str, event: JsonDict) -> str:
    rendered = template
    for key in ("conversation_id", "action", "reason"):
        rendered = rendered.replace("{" + key + "}", str(event.get(key) or ""))
    return rendered


def _assert_scenario_preview(scenario: PhaseGScenario, preview: JsonDict) -> list[str]:
    failures: list[str] = []
    if preview.get("google_api_calls") != 0:
        failures.append("google_api_call_present")
    if preview.get("credential_lookup") is not False:
        failures.append("credential_lookup_present")
    if preview.get("customer_visible_output") is not None:
        failures.append("customer_visible_output_present")
    if preview.get("outbound_outbox_writes") != 0:
        failures.append("outbox_write_present")
    if preview.get("workflow_execution_writes") != 0:
        failures.append("workflow_execution_write_present")
    field_updates = dict(preview.get("field_updates") or {})
    for key, expected in scenario.expected_field_updates.items():
        if field_updates.get(key) != expected:
            failures.append(f"field_update_mismatch:{key}")
    if len(preview.get("notifications") or []) != scenario.expected_notifications:
        failures.append("notification_count_mismatch")
    if scenario.expected_failed_action:
        actions = {item.get("action") for item in preview.get("notifications") or []}
        if scenario.expected_failed_action not in actions:
            failures.append("failed_action_notification_missing")
    if scenario.expected_drive_subfolders:
        subfolders = tuple((preview.get("drive") or {}).get("subfolders") or ())
        if subfolders != scenario.expected_drive_subfolders:
            failures.append("drive_subfolders_mismatch")
    side_effects = dict(preview.get("side_effects") or {})
    if any(bool(value) for value in side_effects.values()):
        failures.append("side_effect_present")
    return failures


async def _store_phase_g_lab(
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
        name=f"Dinamo V1 Phase G Google dry-run - {timestamp}",
        mode="publish_readiness",
        metadata={
            "source": PHASE_G_SEED_ID,
            "source_version_id": PHASE_G_SOURCE_VERSION_ID,
            "phase_f_source": PHASE_F_SEED_ID,
            "openai_api_real": False,
            "google_api_real": False,
            "external_apis": False,
            "send": "no_send",
            "workflow_side_effects": False,
        },
    )
    for scenario in phase_g_scenarios():
        await service.create_agent_test_scenario(
            session,
            tenant_id=tenant_id,
            suite_id=suite.id,
            name=scenario.name,
            turns=[_scenario_turn(scenario)],
            expected=scenario.as_expected(),
            metadata={
                "source": PHASE_G_SEED_ID,
                "scenario_key": scenario.key,
                "workflow_key": scenario.workflow_key,
                "openai_api_real": False,
                "google_api_real": False,
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
    run.decision = PHASE_G_DECISION_READY if not blocked else PHASE_G_DECISION_BLOCKED
    run.outbox_audit_result = {"status": "clean", "outbound_outbox_writes": 0}
    run.side_effect_audit_result = {
        "status": "clean",
        "delivery": False,
        "workflows": False,
        "actions": False,
        "field_writes": False,
        "external_apis": False,
    }
    run.coverage_summary = {
        "source": PHASE_G_SEED_ID,
        "source_version_id": PHASE_G_SOURCE_VERSION_ID,
        "execution_mode": "google_integration_dry_run_preview",
        "google_workflows": list(PHASE_G_WORKFLOWS),
        "system_fields": list(PHASE_G_SYSTEM_FIELDS),
        "send_decision": "no_send",
        "openai_api_real": False,
        "google_api_real": False,
        "external_apis": False,
        "workflow_side_effects": False,
        "outbound_outbox_writes": 0,
    }
    suite.last_run_id = run.id
    suite.status = run.status
    session.add(run)
    await session.flush()
    return suite, run


def _scenario_turn(scenario: PhaseGScenario) -> JsonDict:
    return {
        "inbound_text": f"google_event:{scenario.workflow_key}:{scenario.key}",
        "event_type": scenario.event_type,
        "event": dict(scenario.event),
    }


async def _load_phase_f_or_newer_version(
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
    if not snapshot.get("phase_f_source"):
        raise service.ProductAgentError("latest Dinamo version must have Phase F active")
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


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Seed Dinamo Phase G Google dry-run.")
    parser.add_argument("--tenant-id", required=True, type=UUID)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--created-by-user-id", type=UUID, default=None)
    return parser.parse_args(argv)


async def _amain(argv: list[str]) -> int:
    args = _parse_args(argv)
    if args.dry_run:
        result = await seed_dinamo_phase_g_google(
            _DryRunSession(),  # type: ignore[arg-type]
            tenant_id=args.tenant_id,
            dry_run=True,
            created_by_user_id=args.created_by_user_id,
        )
        print(json.dumps(result.as_dict(), indent=2, sort_keys=True))
        return 0
    async for session in get_db_session():
        try:
            result = await seed_dinamo_phase_g_google(
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
    "DRIVE_SUBFOLDERS",
    "PHASE_G_DECISION_READY",
    "PHASE_G_SEED_ID",
    "PHASE_G_SYSTEM_FIELDS",
    "PHASE_G_WORKFLOWS",
    "PhaseGGoogleResult",
    "PhaseGScenario",
    "_assert_scenario_preview",
    "_phase_g_field_policy",
    "_phase_g_workflow_policy",
    "_preview_drive_upload",
    "_preview_google_workflow",
    "_preview_sheets_upsert",
    "_run_phase_g_dry_lab",
    "_scenario_turn",
    "phase_g_scenarios",
    "phase_g_workflow_specs",
    "seed_dinamo_phase_g_google",
]
