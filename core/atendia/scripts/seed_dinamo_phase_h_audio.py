"""Activate Dinamo Phase H audio contracts, dry-run only.

Phase H wires tenant-scoped dry-run workflow contracts for audio transcription
and stores DB-backed no-send evidence from deterministic audio facts.

It does not call speech APIs, download media, enqueue messages, execute
workflows, write outbox rows, or require external credentials.

Usage:
    PYTHONPATH=. uv run python -m atendia.scripts.seed_dinamo_phase_h_audio \
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
from atendia.db.models.workflow import WhatsAppTemplate, Workflow, WorkflowExecution
from atendia.db.session import get_db_session
from atendia.product_agents import service
from atendia.scripts.seed_dinamo_phase_g_google import PHASE_G_SEED_ID
from atendia.scripts.seed_dinamo_v1 import (
    AGENT_NAME,
    SEED_ID,
    SOURCE_VERSION_ID,
    TEMPLATE_SPECS,
)

JsonDict = dict[str, Any]

PHASE_H_SEED_ID = "dinamo_tenant_runtime_plan_v1_phase_h"
PHASE_H_SOURCE_VERSION_ID = "DINAMO_TENANT_RUNTIME_PLAN_V1:PHASE_H:2026-06-12"
PHASE_H_DECISION_READY = "DINAMO_PHASE_H_AUDIO_DRY_RUN_READY"
PHASE_H_DECISION_BLOCKED = "DINAMO_PHASE_H_AUDIO_DRY_RUN_BLOCKED"
PHASE_H_WORKFLOWS = (
    "audio.transcribe",
    "customer_message.request",
    "notification.create",
)
PHASE_H_SYSTEM_FIELDS = ("Transcripcion_Ultimo_Audio",)
PHASE_H_TEMPLATES = ("dinamo_audio_processed_v1",)
LOW_CONFIDENCE_THRESHOLD = 0.7


@dataclass(frozen=True)
class PhaseHWorkflowSpec:
    key: str
    name: str
    trigger_type: str
    event_type: str
    nodes: tuple[JsonDict, ...]
    customer_message_request_only: bool = False


@dataclass
class PhaseHAudioResult:
    tenant_id: str
    dry_run: bool
    updated_workflows: list[str] = field(default_factory=list)
    updated_bindings: list[str] = field(default_factory=list)
    updated_field_permissions: list[str] = field(default_factory=list)
    verified_templates: list[str] = field(default_factory=list)
    suite_id: str | None = None
    run_id: str | None = None
    status: str = "ready"
    decision: str = PHASE_H_DECISION_READY
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
            "verified_templates": self.verified_templates,
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
            "speech_api_real": False,
            "external_apis": False,
            "send": "no_send",
            "workflow_side_effects": False,
        }


@dataclass(frozen=True)
class PhaseHScenario:
    key: str
    name: str
    audio_event: JsonDict
    expected_transcription: str
    expected_low_confidence: bool
    expected_next_question: str
    expected_notifications: int = 0

    def as_expected(self) -> JsonDict:
        return {
            "expected_transcription": self.expected_transcription,
            "expected_low_confidence": self.expected_low_confidence,
            "expected_next_question": self.expected_next_question,
            "expected_notifications": self.expected_notifications,
            "send": "no_send",
            "speech_api_real": False,
            "workflow_side_effects": False,
        }


def phase_h_workflow_specs() -> dict[str, PhaseHWorkflowSpec]:
    return {
        "audio.transcribe": PhaseHWorkflowSpec(
            key="audio.transcribe",
            name="Dinamo V1 - Audio transcribe",
            trigger_type="agent_audio_received",
            event_type="agent_audio_received",
            nodes=(
                {
                    "id": "transcribe_audio",
                    "type": "audio_transcribe",
                    "config": {
                        "mode": "dry_run_only",
                        "field": "Transcripcion_Ultimo_Audio",
                        "low_confidence_threshold": LOW_CONFIDENCE_THRESHOLD,
                        "requires_credentials": False,
                    },
                },
                {
                    "id": "write_transcription",
                    "type": "update_field",
                    "config": {
                        "field": "Transcripcion_Ultimo_Audio",
                        "value_from": "audio.transcription",
                        "write_owner": "system_audio_pipeline",
                    },
                },
                {
                    "id": "request_audio_confirmation",
                    "type": "customer_message_request",
                    "config": {
                        "template": "dinamo_audio_processed_v1",
                        "send_scope": "canonical_send_adapter_only",
                        "dedupe_key": "dinamo_audio_processed:{conversation_id}:{attachment_id}",
                    },
                },
            ),
        ),
        "customer_message.request": PhaseHWorkflowSpec(
            key="customer_message.request",
            name="Dinamo V1 - Audio customer message request",
            trigger_type="customer_message.request",
            event_type="customer_message.request",
            customer_message_request_only=True,
            nodes=(
                {
                    "id": "template",
                    "type": "template_message",
                    "config": {
                        "template_source": "tenant_whatsapp_templates",
                        "send_scope": "canonical_send_adapter_only",
                        "dedupe_key": "dinamo_customer_message:{conversation_id}:{case}",
                    },
                },
            ),
        ),
        "notification.create": PhaseHWorkflowSpec(
            key="notification.create",
            name="Dinamo V1 - Audio notification",
            trigger_type="notification_requested",
            event_type="notification_requested",
            nodes=(
                {
                    "id": "notify_audio_issue",
                    "type": "notify_agent",
                    "config": {
                        "role": "operator",
                        "dedupe_key": "dinamo_audio:{conversation_id}:{reason}",
                    },
                },
            ),
        ),
    }


def phase_h_scenarios() -> tuple[PhaseHScenario, ...]:
    return (
        PhaseHScenario(
            key="long_audio_transcribed_to_turn_input",
            name="Audio largo produce transcripcion y una pregunta",
            audio_event={
                "conversation_id": "dry-run-conv",
                "attachment_id": "aud-long",
                "duration_seconds": 85,
                "confidence": 0.91,
                "dry_transcription": (
                    "Me interesa una FT150, tengo dos anios trabajando y me pagan "
                    "por nomina con tarjeta."
                ),
                "next_question": "que banco usas para tu nomina",
            },
            expected_transcription=(
                "Me interesa una FT150, tengo dos anios trabajando y me pagan "
                "por nomina con tarjeta."
            ),
            expected_low_confidence=False,
            expected_next_question="que banco usas para tu nomina",
        ),
        PhaseHScenario(
            key="low_confidence_audio_requests_written_confirmation",
            name="Audio baja confianza pide confirmacion por escrito",
            audio_event={
                "conversation_id": "dry-run-conv",
                "attachment_id": "aud-low",
                "duration_seconds": 22,
                "confidence": 0.42,
                "dry_transcription": "Quiero la moto barata creo y papeles no se escucha bien",
                "next_question": "que modelo o presupuesto quieres revisar",
            },
            expected_transcription="Quiero la moto barata creo y papeles no se escucha bien",
            expected_low_confidence=True,
            expected_next_question="que modelo o presupuesto quieres revisar",
            expected_notifications=1,
        ),
        PhaseHScenario(
            key="audio_with_many_questions_keeps_one_next_question",
            name="Audio multi-intencion conserva una sola pregunta siguiente",
            audio_event={
                "conversation_id": "dry-run-conv",
                "attachment_id": "aud-many",
                "duration_seconds": 64,
                "confidence": 0.84,
                "dry_transcription": (
                    "Quiero saber si checan buro, donde estan y si puedo liquidar antes."
                ),
                "next_question": "cuanto tiempo tienes trabajando",
            },
            expected_transcription=(
                "Quiero saber si checan buro, donde estan y si puedo liquidar antes."
            ),
            expected_low_confidence=False,
            expected_next_question="cuanto tiempo tienes trabajando",
        ),
    )


async def seed_dinamo_phase_h_audio(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    dry_run: bool = False,
    created_by_user_id: UUID | None = None,
) -> PhaseHAudioResult:
    result = PhaseHAudioResult(tenant_id=str(tenant_id), dry_run=dry_run)
    if dry_run:
        result.updated_workflows = list(PHASE_H_WORKFLOWS)
        result.updated_bindings = [
            f"{key}:{spec.event_type}" for key, spec in phase_h_workflow_specs().items()
        ]
        result.updated_field_permissions = list(PHASE_H_SYSTEM_FIELDS)
        result.verified_templates = list(PHASE_H_TEMPLATES)
        result.pass_count = len(phase_h_scenarios())
        result.assertions = ["preview_only"]
        return result

    result.outbox_before = await _outbox_count(session, tenant_id)
    result.workflow_executions_before = await _workflow_execution_count(session, tenant_id)
    result.deployments_no_send = await _deployments_are_no_send(session, tenant_id)
    if not result.deployments_no_send:
        raise service.ProductAgentError("tenant deployments are not fully no-send")

    _agent, version = await _load_phase_g_or_newer_version(session, tenant_id)
    await _verify_audio_templates(session, tenant_id=tenant_id, result=result)
    specs = phase_h_workflow_specs()
    workflows = await _upsert_phase_h_workflows(
        session,
        tenant_id=tenant_id,
        specs=specs,
        result=result,
    )
    await _upsert_phase_h_bindings(
        session,
        tenant_id=tenant_id,
        version=version,
        workflows=workflows,
        specs=specs,
        result=result,
    )
    await _reinforce_phase_h_field_permissions(
        session,
        tenant_id=tenant_id,
        version=version,
        result=result,
    )
    _update_version_phase_h_policy(version)

    lab = _run_phase_h_dry_lab(workflows, phase_h_scenarios())
    suite, run = await _store_phase_h_lab(
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
        raise service.ProductAgentError("outbox changed during Phase H dry-run")
    if result.workflow_executions_after != result.workflow_executions_before:
        raise service.ProductAgentError("workflow executions changed during Phase H dry-run")
    return result


async def _verify_audio_templates(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    result: PhaseHAudioResult,
) -> None:
    rows = (
        await session.execute(
            select(WhatsAppTemplate).where(
                WhatsAppTemplate.tenant_id == tenant_id,
                WhatsAppTemplate.name.in_(PHASE_H_TEMPLATES),
            )
        )
    ).scalars().all()
    by_name = {row.name: row for row in rows}
    missing = [name for name in PHASE_H_TEMPLATES if name not in by_name]
    if missing:
        raise service.ProductAgentError(f"missing audio templates: {', '.join(missing)}")
    expected_variables = _template_variables()
    for name in PHASE_H_TEMPLATES:
        variables = tuple(by_name[name].variables or ())
        if variables != expected_variables[name]:
            raise service.ProductAgentError(f"audio template variables mismatch: {name}")
    result.verified_templates = list(PHASE_H_TEMPLATES)


def _template_variables() -> dict[str, tuple[str, ...]]:
    return {
        spec.name: spec.variables
        for spec in TEMPLATE_SPECS
        if spec.name in PHASE_H_TEMPLATES
    }


async def _upsert_phase_h_workflows(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    specs: dict[str, PhaseHWorkflowSpec],
    result: PhaseHAudioResult,
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
    for key in PHASE_H_WORKFLOWS:
        spec = specs[key]
        definition = _phase_h_definition(spec)
        trigger_config = {
            "source": SEED_ID,
            "phase_source": PHASE_H_SEED_ID,
            "source_version_id": SOURCE_VERSION_ID,
            "phase_source_version_id": PHASE_H_SOURCE_VERSION_ID,
            "event_type": spec.event_type,
            "dry_run_only": True,
            "speech_api_real": False,
        }
        workflow = by_key.get(key)
        if workflow is None:
            workflow = Workflow(
                tenant_id=tenant_id,
                name=spec.name,
                description="Dinamo V1 Phase H dry-run audio workflow. APIs disabled.",
                trigger_type=spec.trigger_type,
                trigger_config=trigger_config,
                definition=definition,
                active=False,
            )
            session.add(workflow)
            await session.flush()
        else:
            workflow.name = spec.name
            workflow.description = "Dinamo V1 Phase H dry-run audio workflow. APIs disabled."
            workflow.trigger_type = spec.trigger_type
            workflow.trigger_config = trigger_config
            workflow.definition = definition
            workflow.active = False
        result.updated_workflows.append(key)
        updated[key] = workflow
    return updated


def _phase_h_definition(spec: PhaseHWorkflowSpec) -> JsonDict:
    metadata: JsonDict = {
        "source": SEED_ID,
        "phase_source": PHASE_H_SEED_ID,
        "source_version_id": SOURCE_VERSION_ID,
        "phase_source_version_id": PHASE_H_SOURCE_VERSION_ID,
        "workflow_key": spec.key,
        "phase": "H",
        "status": "dry_run_ready",
        "side_effects": "disabled",
        "customer_visible_output_allowed": False,
        "customer_message_request_only": spec.customer_message_request_only,
        "speech_api_real": False,
        "requires_credentials": False,
        "rollback": "rerun Phase G seed; keep audio bindings dry_run_only",
    }
    if spec.key == "audio.transcribe":
        metadata["audio_policy"] = {
            "field": "Transcripcion_Ultimo_Audio",
            "low_confidence_threshold": LOW_CONFIDENCE_THRESHOLD,
            "low_confidence_notification": "audio_low_confidence",
            "agent_uses_transcription_as_input": True,
            "max_next_questions": 1,
            "copy_via": "customer_message.request",
        }
    if spec.key == "notification.create":
        metadata["dedupe_required"] = True
    return {
        "nodes": list(copy.deepcopy(spec.nodes)),
        "edges": [],
        "metadata": metadata,
    }


async def _upsert_phase_h_bindings(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    version: AgentVersion,
    workflows: dict[str, Workflow],
    specs: dict[str, PhaseHWorkflowSpec],
    result: PhaseHAudioResult,
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
    for key in PHASE_H_WORKFLOWS:
        workflow = workflows[key]
        spec = specs[key]
        binding_key = (str(workflow.id), spec.event_type)
        metadata = {
            "source": SEED_ID,
            "phase_source": PHASE_H_SEED_ID,
            "source_version_id": SOURCE_VERSION_ID,
            "phase_source_version_id": PHASE_H_SOURCE_VERSION_ID,
            "workflow_key": key,
            "phase": "H",
            "side_effects_allowed": False,
            "customer_visible_output_allowed": False,
            "speech_api_real": False,
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


async def _reinforce_phase_h_field_permissions(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    version: AgentVersion,
    result: PhaseHAudioResult,
) -> None:
    rows = (
        await session.execute(
            select(AgentFieldPermission).where(
                AgentFieldPermission.tenant_id == tenant_id,
                AgentFieldPermission.agent_version_id == version.id,
                AgentFieldPermission.field_key.in_(PHASE_H_SYSTEM_FIELDS),
            )
        )
    ).scalars().all()
    by_key = {row.field_key: row for row in rows}
    for field_key in PHASE_H_SYSTEM_FIELDS:
        write_policy = {
            "owner": "system_audio_pipeline",
            "allowed_workflows": ["audio.transcribe"],
            "blocked_for_agent": True,
            "phase_source": PHASE_H_SEED_ID,
        }
        metadata = {
            "source": SEED_ID,
            "phase_source": PHASE_H_SEED_ID,
            "source_version_id": SOURCE_VERSION_ID,
            "phase_source_version_id": PHASE_H_SOURCE_VERSION_ID,
            "phase": "H",
            "write_owner": "system_audio_pipeline",
            "speech_api_real": False,
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


def _update_version_phase_h_policy(version: AgentVersion) -> None:
    version.workflow_policy = _phase_h_workflow_policy(version.workflow_policy)
    version.field_policy = _phase_h_field_policy(version.field_policy)
    test_policy = dict(version.test_policy or {})
    test_policy["phase_h_audio_dry_run_gate"] = PHASE_H_DECISION_READY
    version.test_policy = test_policy
    version.snapshot = {
        **(version.snapshot or {}),
        "phase_h_source": PHASE_H_SEED_ID,
        "phase_h_source_version_id": PHASE_H_SOURCE_VERSION_ID,
        "phase_h_workflows": list(PHASE_H_WORKFLOWS),
    }


def _phase_h_workflow_policy(existing_policy: dict[str, Any] | None) -> JsonDict:
    policy = copy.deepcopy(existing_policy or {})
    policy["phase_h_source"] = PHASE_H_SEED_ID
    policy["phase_h_source_version_id"] = PHASE_H_SOURCE_VERSION_ID
    policy["audio_workflows"] = list(PHASE_H_WORKFLOWS)
    policy["audio_execution_mode"] = "dry_run_only"
    policy["speech_api_real"] = False
    policy["audio_credentials_required_for_dry_run"] = False
    policy["audio_policy"] = {
        "field": "Transcripcion_Ultimo_Audio",
        "low_confidence_threshold": LOW_CONFIDENCE_THRESHOLD,
        "low_confidence_notification": "audio_low_confidence",
        "max_next_questions": 1,
        "customer_message_request_template": "dinamo_audio_processed_v1",
    }
    return policy


def _phase_h_field_policy(existing_policy: dict[str, Any] | None) -> JsonDict:
    policy = copy.deepcopy(existing_policy or {})
    fields = [
        copy.deepcopy(item)
        for item in policy.get("fields") or []
        if isinstance(item, dict) and (item.get("field_key") or item.get("key"))
    ]
    by_key = {str(item.get("field_key") or item.get("key")): item for item in fields}
    for field_key in PHASE_H_SYSTEM_FIELDS:
        field = by_key.get(field_key, {"field_key": field_key, "key": field_key})
        field.update(
            {
                "field_key": field_key,
                "key": field_key,
                "writable": False,
                "allowed_sources": ["audio.transcribe"],
                "write_policy": "system_audio_pipeline_only",
                "phase": "H",
                "phase_source": PHASE_H_SEED_ID,
                "write_policy_metadata": {
                    **(field.get("write_policy_metadata") or {}),
                    "blocked_for_agent": True,
                    "speech_api_real": False,
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
    ordered.extend(by_key[key] for key in PHASE_H_SYSTEM_FIELDS if key not in seen)
    policy.update(
        {
            "phase_h_source": PHASE_H_SEED_ID,
            "phase_h_source_version_id": PHASE_H_SOURCE_VERSION_ID,
            "audio_system_fields": list(PHASE_H_SYSTEM_FIELDS),
            "fields": ordered,
        }
    )
    return policy


def _run_phase_h_dry_lab(
    workflows: dict[str, Workflow],
    scenarios: tuple[PhaseHScenario, ...],
) -> list[JsonDict]:
    results: list[JsonDict] = []
    workflow = workflows.get("audio.transcribe")
    for scenario in scenarios:
        if workflow is None:
            results.append(_blocked_scenario(scenario, "workflow_missing"))
            continue
        preview = _preview_audio_workflow(workflow.definition or {}, scenario)
        failures = _assert_scenario_preview(scenario, preview)
        results.append(
            {
                "scenario_key": scenario.key,
                "scenario_name": scenario.name,
                "workflow_key": "audio.transcribe",
                "event_type": "agent_audio_received",
                "status": "passed" if not failures else "blocked",
                "blocked_reason": ",".join(failures) if failures else None,
                "expected": scenario.as_expected(),
                "preview": preview,
                "send_decision": "no_send",
                "outbound_outbox_writes": 0,
                "workflow_execution_writes": 0,
                "openai_api_real": False,
                "speech_api_real": False,
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


def _blocked_scenario(scenario: PhaseHScenario, reason: str) -> JsonDict:
    return {
        "scenario_key": scenario.key,
        "workflow_key": "audio.transcribe",
        "event_type": "agent_audio_received",
        "status": "blocked",
        "blocked_reason": reason,
        "expected": scenario.as_expected(),
        "preview": {},
    }


def _preview_audio_workflow(definition: JsonDict, scenario: PhaseHScenario) -> JsonDict:
    event = scenario.audio_event
    transcription = str(event.get("dry_transcription") or "")
    confidence = float(event.get("confidence") or 0.0)
    low_confidence = confidence < LOW_CONFIDENCE_THRESHOLD
    next_question = str(event.get("next_question") or "")
    preview: JsonDict = {
        "status": "dry_run",
        "nodes": [],
        "field_updates": {},
        "notifications": [],
        "customer_message_requests": [],
        "speech_api_calls": 0,
        "credential_lookup": False,
        "customer_visible_output": None,
        "agent_turn_input": {
            "inbound_text": transcription,
            "source": "audio.transcribe",
            "usable_for_agent_claims": not low_confidence,
            "max_next_questions": 1,
        },
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
        if node_type == "audio_transcribe":
            preview["transcription"] = {
                "text": transcription,
                "confidence": confidence,
                "low_confidence": low_confidence,
                "duration_seconds": event.get("duration_seconds"),
                "speech_api_call": False,
            }
        elif node_type == "update_field":
            preview["field_updates"]["Transcripcion_Ultimo_Audio"] = {
                "value": transcription,
                "write_owner": "system_audio_pipeline",
                "evidence": [f"audio_attachment:{event.get('attachment_id')}"],
                "usable_for_agent_claims": not low_confidence,
            }
        elif node_type == "customer_message_request":
            preview["customer_message_requests"].append(
                {
                    "template": "dinamo_audio_processed_v1",
                    "variables": {"siguiente_pregunta": next_question},
                    "dedupe_key": _render_dedupe(
                        str((node.get("config") or {}).get("dedupe_key") or ""),
                        event,
                    ),
                    "send_decision": "no_send",
                    "dry_run": True,
                }
            )
    if low_confidence:
        preview["notifications"].append(
            {
                "reason": "audio_low_confidence",
                "dedupe_key": _render_dedupe(
                    "dinamo_audio:{conversation_id}:audio_low_confidence",
                    event,
                ),
                "dry_run": True,
            }
        )
    return preview


def _render_dedupe(template: str, event: JsonDict) -> str:
    rendered = template
    for key in ("conversation_id", "attachment_id", "reason"):
        rendered = rendered.replace("{" + key + "}", str(event.get(key) or ""))
    return rendered


def _assert_scenario_preview(scenario: PhaseHScenario, preview: JsonDict) -> list[str]:
    failures: list[str] = []
    if preview.get("speech_api_calls") != 0:
        failures.append("speech_api_call_present")
    if preview.get("credential_lookup") is not False:
        failures.append("credential_lookup_present")
    if preview.get("customer_visible_output") is not None:
        failures.append("customer_visible_output_present")
    if preview.get("outbound_outbox_writes") != 0:
        failures.append("outbox_write_present")
    if preview.get("workflow_execution_writes") != 0:
        failures.append("workflow_execution_write_present")
    transcription = dict(preview.get("transcription") or {})
    if transcription.get("text") != scenario.expected_transcription:
        failures.append("transcription_mismatch")
    if transcription.get("low_confidence") is not scenario.expected_low_confidence:
        failures.append("low_confidence_mismatch")
    field_update = (preview.get("field_updates") or {}).get("Transcripcion_Ultimo_Audio")
    if not isinstance(field_update, dict):
        failures.append("transcription_field_missing")
    elif field_update.get("write_owner") != "system_audio_pipeline":
        failures.append("transcription_field_owner_mismatch")
    requests = preview.get("customer_message_requests") or []
    if len(requests) != 1:
        failures.append("customer_message_request_count_mismatch")
    else:
        variables = dict(requests[0].get("variables") or {})
        if variables.get("siguiente_pregunta") != scenario.expected_next_question:
            failures.append("next_question_mismatch")
        if _count_question_prompts(str(variables.get("siguiente_pregunta") or "")) > 1:
            failures.append("more_than_one_next_question")
        if requests[0].get("send_decision") != "no_send":
            failures.append("customer_message_request_not_no_send")
    if len(preview.get("notifications") or []) != scenario.expected_notifications:
        failures.append("notification_count_mismatch")
    side_effects = dict(preview.get("side_effects") or {})
    if any(bool(value) for value in side_effects.values()):
        failures.append("side_effect_present")
    return failures


def _count_question_prompts(text: str) -> int:
    stripped = text.strip()
    if not stripped:
        return 0
    return stripped.count("?") or 1


async def _store_phase_h_lab(
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
        name=f"Dinamo V1 Phase H Audio dry-run - {timestamp}",
        mode="publish_readiness",
        metadata={
            "source": PHASE_H_SEED_ID,
            "source_version_id": PHASE_H_SOURCE_VERSION_ID,
            "phase_g_source": PHASE_G_SEED_ID,
            "openai_api_real": False,
            "speech_api_real": False,
            "external_apis": False,
            "send": "no_send",
            "workflow_side_effects": False,
        },
    )
    for scenario in phase_h_scenarios():
        await service.create_agent_test_scenario(
            session,
            tenant_id=tenant_id,
            suite_id=suite.id,
            name=scenario.name,
            turns=[_scenario_turn(scenario)],
            expected=scenario.as_expected(),
            metadata={
                "source": PHASE_H_SEED_ID,
                "scenario_key": scenario.key,
                "workflow_key": "audio.transcribe",
                "openai_api_real": False,
                "speech_api_real": False,
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
    run.decision = PHASE_H_DECISION_READY if not blocked else PHASE_H_DECISION_BLOCKED
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
        "source": PHASE_H_SEED_ID,
        "source_version_id": PHASE_H_SOURCE_VERSION_ID,
        "execution_mode": "audio_dry_run_preview",
        "audio_workflows": list(PHASE_H_WORKFLOWS),
        "system_fields": list(PHASE_H_SYSTEM_FIELDS),
        "templates": list(PHASE_H_TEMPLATES),
        "send_decision": "no_send",
        "openai_api_real": False,
        "speech_api_real": False,
        "external_apis": False,
        "workflow_side_effects": False,
        "outbound_outbox_writes": 0,
    }
    suite.last_run_id = run.id
    suite.status = run.status
    session.add(run)
    await session.flush()
    return suite, run


def _scenario_turn(scenario: PhaseHScenario) -> JsonDict:
    return {
        "inbound_text": f"audio_event:{scenario.key}",
        "attachments": [
            {
                "attachment_id": scenario.audio_event.get("attachment_id"),
                "type": "audio",
                "duration_seconds": scenario.audio_event.get("duration_seconds"),
            }
        ],
        "event": dict(scenario.audio_event),
    }


async def _load_phase_g_or_newer_version(
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
    if not snapshot.get("phase_g_source"):
        raise service.ProductAgentError("latest Dinamo version must have Phase G active")
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
    parser = argparse.ArgumentParser(description="Seed Dinamo Phase H audio dry-run.")
    parser.add_argument("--tenant-id", required=True, type=UUID)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--created-by-user-id", type=UUID, default=None)
    return parser.parse_args(argv)


async def _amain(argv: list[str]) -> int:
    args = _parse_args(argv)
    if args.dry_run:
        result = await seed_dinamo_phase_h_audio(
            _DryRunSession(),  # type: ignore[arg-type]
            tenant_id=args.tenant_id,
            dry_run=True,
            created_by_user_id=args.created_by_user_id,
        )
        print(json.dumps(result.as_dict(), indent=2, sort_keys=True))
        return 0
    async for session in get_db_session():
        try:
            result = await seed_dinamo_phase_h_audio(
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
    "LOW_CONFIDENCE_THRESHOLD",
    "PHASE_H_DECISION_READY",
    "PHASE_H_SEED_ID",
    "PHASE_H_SYSTEM_FIELDS",
    "PHASE_H_TEMPLATES",
    "PHASE_H_WORKFLOWS",
    "PhaseHAudioResult",
    "PhaseHScenario",
    "_assert_scenario_preview",
    "_phase_h_field_policy",
    "_phase_h_workflow_policy",
    "_preview_audio_workflow",
    "_run_phase_h_dry_lab",
    "_scenario_turn",
    "phase_h_scenarios",
    "phase_h_workflow_specs",
    "seed_dinamo_phase_h_audio",
]
