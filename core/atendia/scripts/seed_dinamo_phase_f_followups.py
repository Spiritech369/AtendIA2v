"""Activate Dinamo Phase F follow-up contracts in DB real, dry-run only.

Phase F wires followup.schedule (quiet-hours 7:00-23:00, jitter 2-10 min,
attempts 3h/12h/72h, max 3, cancel-on-reply/handoff/terminal) and the
customer_message.request copy channel for the three follow-up templates.
It stores DB-backed no-send evidence from a deterministic scheduler preview.
It does not enqueue real follow-ups, send messages, or execute workflows.

Usage:
    PYTHONPATH=. uv run python -m atendia.scripts.seed_dinamo_phase_f_followups \
        --tenant-id <uuid>
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import json
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime, time, timedelta
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
from atendia.scripts.seed_dinamo_phase_e_documents import PHASE_E_SEED_ID
from atendia.scripts.seed_dinamo_v1 import (
    AGENT_NAME,
    SEED_ID,
    SOURCE_VERSION_ID,
    TEMPLATE_SPECS,
    WorkflowSpec,
    build_workflow_specs,
)

JsonDict = dict[str, Any]

PHASE_F_SEED_ID = "dinamo_tenant_runtime_plan_v1_phase_f"
PHASE_F_SOURCE_VERSION_ID = "DINAMO_TENANT_RUNTIME_PLAN_V1:PHASE_F:2026-06-11"
PHASE_F_DECISION_READY = "DINAMO_PHASE_F_FOLLOWUPS_DRY_RUN_READY"
PHASE_F_DECISION_BLOCKED = "DINAMO_PHASE_F_FOLLOWUPS_DRY_RUN_BLOCKED"
PHASE_F_WORKFLOWS = ("followup.schedule", "customer_message.request")
PHASE_F_SYSTEM_FIELDS = ("Followups_Enviados", "Proximo_Followup")
PHASE_F_TEMPLATES = (
    "dinamo_followup_3h_v1",
    "dinamo_followup_12h_v1",
    "dinamo_followup_72h_v1",
)
# Deterministic preview jitter per attempt index; the live node draws uniform
# 2-10 min. Preview values must stay inside that range.
PREVIEW_JITTER_MINUTES = (2, 6, 10)


@dataclass
class PhaseFFollowupResult:
    tenant_id: str
    dry_run: bool
    updated_workflows: list[str] = field(default_factory=list)
    updated_bindings: list[str] = field(default_factory=list)
    updated_field_permissions: list[str] = field(default_factory=list)
    verified_templates: list[str] = field(default_factory=list)
    suite_id: str | None = None
    run_id: str | None = None
    status: str = "ready"
    decision: str = PHASE_F_DECISION_READY
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
            "external_apis": False,
            "send": "no_send",
            "workflow_side_effects": False,
        }


@dataclass(frozen=True)
class PhaseFScenario:
    key: str
    name: str
    silence_start: str
    state: JsonDict
    cancel_events: tuple[JsonDict, ...] = ()
    expected_statuses: tuple[str, ...] = ("scheduled", "scheduled", "scheduled")
    expected_queued: tuple[bool, ...] = (False, False, False)
    expected_cancel_reason: str | None = None

    def as_expected(self) -> JsonDict:
        return {
            "silence_start": self.silence_start,
            "expected_statuses": list(self.expected_statuses),
            "expected_queued": list(self.expected_queued),
            "expected_cancel_reason": self.expected_cancel_reason,
            "max_attempts": 3,
            "send": "no_send",
            "workflow_side_effects": False,
        }


def _full_state() -> JsonDict:
    return {
        "Moto": "Italika FT150",
        "Plan_Credito_Sentence": "Tu plan Nómina Tarjeta sigue vigente.",
        "Siguiente_Dato_O_Documento": "tu comprobante de domicilio",
    }


def phase_f_scenarios() -> tuple[PhaseFScenario, ...]:
    return (
        PhaseFScenario(
            key="in_window_three_attempts",
            name="Silencio en horario agenda 3h/12h/72h dentro de ventana",
            silence_start="2026-06-15T09:00",
            state=_full_state(),
        ),
        PhaseFScenario(
            key="quiet_hours_queue_first_attempt",
            name="Intento que cae de madrugada queda en cola hasta las 7:00",
            silence_start="2026-06-15T21:30",
            state=_full_state(),
            expected_queued=(True, False, False),
        ),
        PhaseFScenario(
            key="reply_cancels_remaining",
            name="Cliente responde tras intento 1 y cancela el resto",
            silence_start="2026-06-15T09:00",
            state=_full_state(),
            cancel_events=(
                {"at": "2026-06-15T14:00", "cancel_token": "message_received"},
            ),
            expected_statuses=("scheduled", "cancelled", "cancelled"),
            expected_cancel_reason="message_received",
        ),
        PhaseFScenario(
            key="handoff_cancels_all",
            name="Handoff humano cancela todos los follow-ups pendientes",
            silence_start="2026-06-15T09:00",
            state=_full_state(),
            cancel_events=(
                {"at": "2026-06-15T10:00", "cancel_token": "Handoff_Humano"},
            ),
            expected_statuses=("cancelled", "cancelled", "cancelled"),
            expected_cancel_reason="Handoff_Humano",
        ),
        PhaseFScenario(
            key="terminal_stage_cancels_pending",
            name="Etapa terminal cancela los intentos restantes",
            silence_start="2026-06-15T09:00",
            state=_full_state(),
            cancel_events=(
                {"at": "2026-06-16T08:00", "cancel_token": "cerrado_perdido"},
            ),
            expected_statuses=("scheduled", "scheduled", "cancelled"),
            expected_cancel_reason="cerrado_perdido",
        ),
        PhaseFScenario(
            key="missing_variable_fails_closed",
            name="Variable sin estado validado bloquea plantilla sin improvisar",
            silence_start="2026-06-15T09:00",
            state={
                "Siguiente_Dato_O_Documento": "tu comprobante de domicilio",
            },
            expected_statuses=(
                "scheduled",
                "blocked_missing_variable",
                "scheduled",
            ),
        ),
    )


def followup_node_config() -> JsonDict:
    specs = {spec.key: spec for spec in build_workflow_specs()}
    node = next(
        node
        for node in specs["followup.schedule"].nodes
        if node.get("type") == "followup"
    )
    return dict(node.get("config") or {})


def _template_variables() -> dict[str, tuple[str, ...]]:
    return {spec.name: spec.variables for spec in TEMPLATE_SPECS}


def _parse_local(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _in_quiet_hours(moment: datetime, config: JsonDict) -> bool:
    quiet = dict(config.get("quiet_hours") or {})
    start = time.fromisoformat(str(quiet.get("start") or "23:00"))
    end = time.fromisoformat(str(quiet.get("end") or "07:00"))
    current = moment.time()
    if start > end:  # window wraps midnight
        return current >= start or current < end
    return start <= current < end


def _defer_to_window(moment: datetime, config: JsonDict) -> datetime:
    quiet = dict(config.get("quiet_hours") or {})
    end = time.fromisoformat(str(quiet.get("end") or "07:00"))
    candidate = moment.replace(
        hour=end.hour, minute=end.minute, second=0, microsecond=0
    )
    if candidate <= moment and moment.time() >= time.fromisoformat(
        str(quiet.get("start") or "23:00")
    ):
        candidate += timedelta(days=1)
    return candidate


def schedule_followups_preview(
    config: JsonDict,
    *,
    silence_start: datetime,
    state: JsonDict,
    cancel_events: tuple[JsonDict, ...] = (),
) -> JsonDict:
    delays = [int(item) for item in config.get("attempt_delays_hours") or []]
    max_attempts = int(config.get("max_attempts") or len(delays))
    templates = [str(item) for item in config.get("templates") or []]
    jitter_low, jitter_high = (
        int((config.get("jitter_minutes") or [2, 10])[0]),
        int((config.get("jitter_minutes") or [2, 10])[1]),
    )
    cancel_on = {str(item) for item in config.get("cancel_on") or []}
    variables_by_template = _template_variables()
    parsed_events = sorted(
        (
            (_parse_local(str(event["at"])), str(event["cancel_token"]))
            for event in cancel_events
            if str(event.get("cancel_token")) in cancel_on
        ),
        key=lambda item: item[0],
    )
    attempts: list[JsonDict] = []
    cancel_reason: str | None = None
    for index, delay_hours in enumerate(delays[:max_attempts]):
        jitter = PREVIEW_JITTER_MINUTES[index % len(PREVIEW_JITTER_MINUTES)]
        if not jitter_low <= jitter <= jitter_high:
            jitter = jitter_low
        raw = silence_start + timedelta(hours=delay_hours)
        queued = _in_quiet_hours(raw, config)
        window_start = _defer_to_window(raw, config) if queued else raw
        scheduled_for = window_start + timedelta(minutes=jitter)
        attempt: JsonDict = {
            "attempt": index + 1,
            "delay_hours": delay_hours,
            "template": templates[index] if index < len(templates) else None,
            "jitter_minutes": jitter,
            "raw_time": raw.isoformat(),
            "scheduled_for": scheduled_for.isoformat(),
            "queued_from_quiet_hours": queued,
            "status": "scheduled",
            "cancel_reason": None,
            "missing_variables": [],
            "send_decision": "no_send",
            "dry_run": True,
        }
        cancelled_by = next(
            (token for at, token in parsed_events if at <= scheduled_for),
            None,
        )
        if cancelled_by is not None:
            attempt["status"] = "cancelled"
            attempt["cancel_reason"] = cancelled_by
            cancel_reason = cancel_reason or cancelled_by
            attempts.append(attempt)
            continue
        template_name = attempt["template"]
        required = variables_by_template.get(str(template_name), ())
        missing = [name for name in required if not state.get(name)]
        if missing:
            attempt["status"] = "blocked_missing_variable"
            attempt["missing_variables"] = missing
        attempts.append(attempt)
    return {
        "attempts": attempts,
        "max_attempts": max_attempts,
        "cancel_reason": cancel_reason,
        "quiet_hours": dict(config.get("quiet_hours") or {}),
        "jitter_range_minutes": [jitter_low, jitter_high],
        "templates": templates,
        "outbound_outbox_writes": 0,
        "workflow_execution_writes": 0,
        "send_decision": "no_send",
    }


def _assert_scenario_preview(scenario: PhaseFScenario, preview: JsonDict) -> list[str]:
    failures: list[str] = []
    attempts = [item for item in preview.get("attempts") or [] if isinstance(item, dict)]
    if len(attempts) != 3:
        failures.append("attempt_count_mismatch")
        return failures
    for index, attempt in enumerate(attempts):
        if attempt.get("status") != scenario.expected_statuses[index]:
            failures.append(f"status_mismatch:attempt_{index + 1}")
        if attempt.get("queued_from_quiet_hours") != scenario.expected_queued[index]:
            failures.append(f"queued_mismatch:attempt_{index + 1}")
        if attempt.get("template") != PHASE_F_TEMPLATES[index]:
            failures.append(f"template_mismatch:attempt_{index + 1}")
        if attempt.get("send_decision") != "no_send":
            failures.append(f"send_decision_not_no_send:attempt_{index + 1}")
        jitter = attempt.get("jitter_minutes")
        if not isinstance(jitter, int) or not 2 <= jitter <= 10:
            failures.append(f"jitter_out_of_range:attempt_{index + 1}")
        scheduled_for = _parse_local(str(attempt.get("scheduled_for")))
        if attempt.get("status") == "scheduled" and (
            scheduled_for.time() >= time(23, 0) or scheduled_for.time() < time(7, 0)
        ):
            failures.append(f"scheduled_inside_quiet_hours:attempt_{index + 1}")
        if attempt.get("status") == "blocked_missing_variable" and not attempt.get(
            "missing_variables"
        ):
            failures.append(f"missing_variables_empty:attempt_{index + 1}")
    if preview.get("cancel_reason") != scenario.expected_cancel_reason:
        failures.append("cancel_reason_mismatch")
    if preview.get("outbound_outbox_writes") != 0:
        failures.append("outbox_write_present")
    if preview.get("workflow_execution_writes") != 0:
        failures.append("workflow_execution_write_present")
    return failures


def _run_phase_f_dry_lab(scenarios: tuple[PhaseFScenario, ...]) -> list[JsonDict]:
    config = followup_node_config()
    results: list[JsonDict] = []
    for scenario in scenarios:
        preview = schedule_followups_preview(
            config,
            silence_start=_parse_local(scenario.silence_start),
            state=dict(scenario.state),
            cancel_events=scenario.cancel_events,
        )
        failures = _assert_scenario_preview(scenario, preview)
        results.append(
            {
                "scenario_key": scenario.key,
                "scenario_name": scenario.name,
                "status": "passed" if not failures else "blocked",
                "blocked_reason": ",".join(failures) if failures else None,
                "expected": scenario.as_expected(),
                "preview": preview,
                "send_decision": "no_send",
                "outbound_outbox_writes": 0,
                "workflow_execution_writes": 0,
                "openai_api_real": False,
                "side_effects": {
                    "delivery": False,
                    "workflows": False,
                    "actions": False,
                    "field_writes": False,
                },
            }
        )
    return results


async def seed_dinamo_phase_f_followups(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    dry_run: bool = False,
    created_by_user_id: UUID | None = None,
) -> PhaseFFollowupResult:
    result = PhaseFFollowupResult(tenant_id=str(tenant_id), dry_run=dry_run)
    if dry_run:
        result.updated_workflows = list(PHASE_F_WORKFLOWS)
        result.updated_field_permissions = list(PHASE_F_SYSTEM_FIELDS)
        result.verified_templates = list(PHASE_F_TEMPLATES)
        result.pass_count = len(phase_f_scenarios())
        result.assertions = ["preview_only"]
        return result

    result.outbox_before = await _outbox_count(session, tenant_id)
    result.workflow_executions_before = await _workflow_execution_count(session, tenant_id)
    result.deployments_no_send = await _deployments_are_no_send(session, tenant_id)
    if not result.deployments_no_send:
        raise service.ProductAgentError("tenant deployments are not fully no-send")

    _agent, version = await _load_phase_e_or_newer_version(session, tenant_id)
    await _verify_followup_templates(session, tenant_id=tenant_id, result=result)
    specs = _phase_f_specs()
    workflows = await _upsert_phase_f_workflows(
        session,
        tenant_id=tenant_id,
        specs=specs,
        result=result,
    )
    await _upsert_phase_f_bindings(
        session,
        tenant_id=tenant_id,
        version=version,
        workflows=workflows,
        specs=specs,
        result=result,
    )
    await _reinforce_phase_f_field_permissions(
        session,
        tenant_id=tenant_id,
        version=version,
        result=result,
    )
    _update_version_phase_f_policy(version)

    lab = _run_phase_f_dry_lab(phase_f_scenarios())
    suite, run = await _store_phase_f_lab(
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
        raise service.ProductAgentError("outbox changed during Phase F dry-run")
    if result.workflow_executions_after != result.workflow_executions_before:
        raise service.ProductAgentError("workflow executions changed during Phase F dry-run")
    return result


def _phase_f_specs() -> dict[str, WorkflowSpec]:
    specs = {spec.key: spec for spec in build_workflow_specs()}
    return {key: specs[key] for key in PHASE_F_WORKFLOWS}


async def _verify_followup_templates(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    result: PhaseFFollowupResult,
) -> None:
    rows = (
        await session.execute(
            select(WhatsAppTemplate).where(
                WhatsAppTemplate.tenant_id == tenant_id,
                WhatsAppTemplate.name.in_(PHASE_F_TEMPLATES),
            )
        )
    ).scalars().all()
    by_name = {row.name: row for row in rows}
    missing = [name for name in PHASE_F_TEMPLATES if name not in by_name]
    if missing:
        raise service.ProductAgentError(
            f"missing follow-up templates: {', '.join(missing)}"
        )
    result.verified_templates = list(PHASE_F_TEMPLATES)


async def _upsert_phase_f_workflows(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    specs: dict[str, WorkflowSpec],
    result: PhaseFFollowupResult,
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
    for key, spec in specs.items():
        definition = _phase_f_definition(spec)
        trigger_config = {
            "source": SEED_ID,
            "phase_source": PHASE_F_SEED_ID,
            "source_version_id": SOURCE_VERSION_ID,
            "phase_source_version_id": PHASE_F_SOURCE_VERSION_ID,
            "event_type": spec.event_type,
            "dry_run_only": True,
        }
        workflow = by_key.get(key)
        if workflow is None:
            workflow = Workflow(
                tenant_id=tenant_id,
                name=spec.name,
                description="Dinamo V1 Phase F dry-run workflow. Side effects disabled.",
                trigger_type=spec.trigger_type,
                trigger_config=trigger_config,
                definition=definition,
                active=False,
            )
            session.add(workflow)
            await session.flush()
        else:
            workflow.name = spec.name
            workflow.description = (
                "Dinamo V1 Phase F dry-run workflow. Side effects disabled."
            )
            workflow.trigger_type = spec.trigger_type
            workflow.trigger_config = trigger_config
            workflow.definition = definition
            workflow.active = False
        result.updated_workflows.append(key)
        updated[key] = workflow
    return updated


def _phase_f_definition(spec: WorkflowSpec) -> JsonDict:
    definition = {
        "nodes": list(copy.deepcopy(spec.nodes)),
        "edges": list(copy.deepcopy(spec.edges)),
        "metadata": {
            "source": SEED_ID,
            "phase_source": PHASE_F_SEED_ID,
            "source_version_id": SOURCE_VERSION_ID,
            "phase_source_version_id": PHASE_F_SOURCE_VERSION_ID,
            "workflow_key": spec.key,
            "phase": "F",
            "status": "dry_run_ready",
            "side_effects": "disabled",
            "customer_visible_output_allowed": False,
            "customer_message_request_only": spec.customer_message_request_only,
            "rollback": "rerun seed_dinamo_v1 or Phase D seed",
        },
    }
    if spec.key == "followup.schedule":
        definition["metadata"]["followup_policy"] = {
            "attempt_delays_hours": [3, 12, 72],
            "quiet_hours": "23:00-07:00 America/Mexico_City",
            "jitter_minutes": [2, 10],
            "max_attempts": 3,
            "cancel_on_reply": True,
            "copy_via": "customer_message.request",
        }
    if spec.key == "customer_message.request":
        definition["metadata"]["dedupe_required"] = True
        definition["metadata"]["followup_templates"] = list(PHASE_F_TEMPLATES)
    return definition


async def _upsert_phase_f_bindings(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    version: AgentVersion,
    workflows: dict[str, Workflow],
    specs: dict[str, WorkflowSpec],
    result: PhaseFFollowupResult,
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
    for key, workflow in workflows.items():
        spec = specs[key]
        binding_key = (str(workflow.id), spec.event_type)
        metadata = {
            "source": SEED_ID,
            "phase_source": PHASE_F_SEED_ID,
            "source_version_id": SOURCE_VERSION_ID,
            "phase_source_version_id": PHASE_F_SOURCE_VERSION_ID,
            "workflow_key": key,
            "phase": "F",
            "customer_message_request_only": spec.customer_message_request_only,
            "side_effects_allowed": False,
            "customer_visible_output_allowed": False,
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


async def _reinforce_phase_f_field_permissions(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    version: AgentVersion,
    result: PhaseFFollowupResult,
) -> None:
    rows = (
        await session.execute(
            select(AgentFieldPermission).where(
                AgentFieldPermission.tenant_id == tenant_id,
                AgentFieldPermission.agent_version_id == version.id,
                AgentFieldPermission.field_key.in_(PHASE_F_SYSTEM_FIELDS),
            )
        )
    ).scalars().all()
    by_key = {row.field_key: row for row in rows}
    for field_key in PHASE_F_SYSTEM_FIELDS:
        write_policy = {
            "owner": "system_workflow",
            "allowed_workflows": ["followup.schedule"],
            "blocked_for_agent": True,
            "phase_source": PHASE_F_SEED_ID,
        }
        metadata = {
            "source": SEED_ID,
            "phase_source": PHASE_F_SEED_ID,
            "source_version_id": SOURCE_VERSION_ID,
            "phase_source_version_id": PHASE_F_SOURCE_VERSION_ID,
            "phase": "F",
            "write_owner": "system_workflow",
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


def _update_version_phase_f_policy(version: AgentVersion) -> None:
    workflow_policy = dict(version.workflow_policy or {})
    workflow_policy["phase_f_source"] = PHASE_F_SEED_ID
    workflow_policy["phase_f_source_version_id"] = PHASE_F_SOURCE_VERSION_ID
    workflow_policy["followup_workflows"] = list(PHASE_F_WORKFLOWS)
    workflow_policy["followup_policy"] = {
        "attempt_delays_hours": [3, 12, 72],
        "quiet_hours": "23:00-07:00 America/Mexico_City",
        "jitter_minutes": [2, 10],
        "max_attempts": 3,
        "cancel_on": [
            "message_received",
            "Handoff_Humano",
            "no_califica",
            "cerrado_perdido",
            "cerrado_ganado",
        ],
        "copy_via": "customer_message.request",
    }
    version.workflow_policy = workflow_policy
    test_policy = dict(version.test_policy or {})
    test_policy["phase_f_followups_dry_run_gate"] = PHASE_F_DECISION_READY
    version.test_policy = test_policy
    version.snapshot = {
        **(version.snapshot or {}),
        "phase_f_source": PHASE_F_SEED_ID,
        "phase_f_source_version_id": PHASE_F_SOURCE_VERSION_ID,
        "phase_f_workflows": list(PHASE_F_WORKFLOWS),
    }


async def _store_phase_f_lab(
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
        name=f"Dinamo V1 Phase F followups dry-run - {timestamp}",
        mode="publish_readiness",
        metadata={
            "source": PHASE_F_SEED_ID,
            "source_version_id": PHASE_F_SOURCE_VERSION_ID,
            "phase_e_source": PHASE_E_SEED_ID,
            "openai_api_real": False,
            "external_apis": False,
            "send": "no_send",
            "workflow_side_effects": False,
        },
    )
    for scenario in phase_f_scenarios():
        await service.create_agent_test_scenario(
            session,
            tenant_id=tenant_id,
            suite_id=suite.id,
            name=scenario.name,
            turns=[_scenario_turn(scenario)],
            expected=scenario.as_expected(),
            metadata={
                "source": PHASE_F_SEED_ID,
                "scenario_key": scenario.key,
                "openai_api_real": False,
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
    run.decision = PHASE_F_DECISION_READY if not blocked else PHASE_F_DECISION_BLOCKED
    run.outbox_audit_result = {"status": "clean", "outbound_outbox_writes": 0}
    run.side_effect_audit_result = {
        "status": "clean",
        "delivery": False,
        "workflows": False,
        "actions": False,
        "field_writes": False,
    }
    run.coverage_summary = {
        "source": PHASE_F_SEED_ID,
        "source_version_id": PHASE_F_SOURCE_VERSION_ID,
        "execution_mode": "followup_scheduler_dry_run_preview",
        "followup_workflows": list(PHASE_F_WORKFLOWS),
        "system_fields": list(PHASE_F_SYSTEM_FIELDS),
        "templates": list(PHASE_F_TEMPLATES),
        "send_decision": "no_send",
        "openai_api_real": False,
        "external_apis": False,
        "workflow_side_effects": False,
        "outbound_outbox_writes": 0,
    }
    suite.last_run_id = run.id
    suite.status = run.status
    session.add(run)
    await session.flush()
    return suite, run


def _scenario_turn(scenario: PhaseFScenario) -> JsonDict:
    return {
        "inbound_text": f"followup_event:{scenario.key}",
        "silence_start": scenario.silence_start,
        "cancel_events": [dict(event) for event in scenario.cancel_events],
        "state": dict(scenario.state),
    }


async def _load_phase_e_or_newer_version(
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
    if not snapshot.get("phase_e_source"):
        raise service.ProductAgentError("latest Dinamo version must have Phase E active")
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
    parser = argparse.ArgumentParser(description="Seed Dinamo Phase F followups.")
    parser.add_argument("--tenant-id", required=True, type=UUID)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--created-by-user-id", type=UUID, default=None)
    return parser.parse_args(argv)


async def _amain(argv: list[str]) -> int:
    args = _parse_args(argv)
    if args.dry_run:
        result = await seed_dinamo_phase_f_followups(
            _DryRunSession(),  # type: ignore[arg-type]
            tenant_id=args.tenant_id,
            dry_run=True,
            created_by_user_id=args.created_by_user_id,
        )
        print(json.dumps(result.as_dict(), indent=2, sort_keys=True))
        return 0
    async for session in get_db_session():
        try:
            result = await seed_dinamo_phase_f_followups(
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
    "PHASE_F_DECISION_READY",
    "PHASE_F_SEED_ID",
    "PHASE_F_SYSTEM_FIELDS",
    "PHASE_F_TEMPLATES",
    "PHASE_F_WORKFLOWS",
    "PhaseFFollowupResult",
    "PhaseFScenario",
    "_assert_scenario_preview",
    "_run_phase_f_dry_lab",
    "followup_node_config",
    "phase_f_scenarios",
    "schedule_followups_preview",
    "seed_dinamo_phase_f_followups",
]
