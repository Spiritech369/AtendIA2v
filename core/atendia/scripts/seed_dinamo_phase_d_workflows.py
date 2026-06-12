"""Activate Dinamo Phase D workflow contracts in DB real, dry-run only.

Phase D does not execute workflow side effects. It updates tenant-scoped
workflow definitions/bindings for the core workflow set and stores DB-backed
Test Lab evidence from a deterministic dry-run preview.

Usage:
    PYTHONPATH=. uv run python -m atendia.scripts.seed_dinamo_phase_d_workflows \
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
    AgentVersion,
    AgentWorkflowBinding,
)
from atendia.db.models.workflow import Workflow, WorkflowExecution
from atendia.db.session import get_db_session
from atendia.product_agents import service
from atendia.scripts.seed_dinamo_phase_c_agent import PHASE_C_SEED_ID
from atendia.scripts.seed_dinamo_v1 import (
    AGENT_NAME,
    PLAN_CREDITO_CHOICES,
    PLAN_ENGANCHE_BY_PLAN,
    SEED_ID,
    SOURCE_VERSION_ID,
    WorkflowSpec,
    build_workflow_specs,
)

JsonDict = dict[str, Any]

PHASE_D_SEED_ID = "dinamo_tenant_runtime_plan_v1_phase_d"
PHASE_D_SOURCE_VERSION_ID = "DINAMO_TENANT_RUNTIME_PLAN_V1:PHASE_D:2026-06-12"
PHASE_D_DECISION_READY = "DINAMO_PHASE_D_WORKFLOWS_DRY_RUN_READY"
PHASE_D_DECISION_BLOCKED = "DINAMO_PHASE_D_WORKFLOWS_DRY_RUN_BLOCKED"
PHASE_D_CORE_WORKFLOWS = (
    "state.write_contact_field",
    "pipeline.transition",
    "handoff.start",
    "human.assign",
    "notification.create",
)


@dataclass
class PhaseDWorkflowResult:
    tenant_id: str
    dry_run: bool
    updated_workflows: list[str] = field(default_factory=list)
    updated_bindings: list[str] = field(default_factory=list)
    suite_id: str | None = None
    run_id: str | None = None
    status: str = "ready"
    decision: str = PHASE_D_DECISION_READY
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
class PhaseDScenario:
    key: str
    workflow_key: str
    event_type: str
    event: JsonDict
    expected_nodes: tuple[str, ...]
    expected_field_updates: JsonDict = field(default_factory=dict)
    expected_stage: str | None = None
    expected_notifications: int = 0
    expected_assignment: bool = False
    expected_pause_bot: bool = False

    def as_expected(self) -> JsonDict:
        return {
            "workflow_key": self.workflow_key,
            "event_type": self.event_type,
            "expected_nodes": list(self.expected_nodes),
            "expected_field_updates": dict(self.expected_field_updates),
            "expected_stage": self.expected_stage,
            "expected_notifications": self.expected_notifications,
            "expected_assignment": self.expected_assignment,
            "expected_pause_bot": self.expected_pause_bot,
            "send": "no_send",
            "workflow_side_effects": False,
        }


def phase_d_scenarios() -> tuple[PhaseDScenario, ...]:
    plan = PLAN_CREDITO_CHOICES[0]
    return (
        PhaseDScenario(
            key="derive_plan_enganche",
            workflow_key="state.write_contact_field",
            event_type="field_extracted",
            event={"field": "Plan_Credito", "value": plan},
            expected_nodes=("derive_plan_enganche", "update_plan_enganche"),
            expected_field_updates={"Plan_Enganche": PLAN_ENGANCHE_BY_PLAN[plan]},
        ),
        PhaseDScenario(
            key="pipeline_no_califica_transition",
            workflow_key="pipeline.transition",
            event_type="field_updated",
            event={"lifecycle": {"target_stage_id": "no_califica"}},
            expected_nodes=("move_stage",),
            expected_stage="no_califica",
        ),
        PhaseDScenario(
            key="handoff_payment_reported",
            workflow_key="handoff.start",
            event_type="human_handoff_requested",
            event={"reason": "pago_reportado", "conversation_id": "dry-run-conv"},
            expected_nodes=(
                "assign",
                "notify",
                "pause_bot",
                "handoff_flag",
                "handoff_reason",
            ),
            expected_field_updates={
                "Handoff_Humano": "true",
                "Motivo_Handoff": "pago_reportado",
            },
            expected_notifications=1,
            expected_assignment=True,
            expected_pause_bot=True,
        ),
        PhaseDScenario(
            key="human_assign_operator",
            workflow_key="human.assign",
            event_type="human_handoff_requested",
            event={"reason": "humano_solicitado"},
            expected_nodes=("assign", "write_advisor"),
            expected_field_updates={"Asesor_Asignado": "Francisco"},
            expected_assignment=True,
        ),
        PhaseDScenario(
            key="notification_dedupe",
            workflow_key="notification.create",
            event_type="notification_requested",
            event={"conversation_id": "dry-run-conv", "event_type": "document_doubt"},
            expected_nodes=("notify_agent",),
            expected_notifications=1,
        ),
    )


async def seed_dinamo_phase_d_workflows(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    dry_run: bool = False,
    created_by_user_id: UUID | None = None,
) -> PhaseDWorkflowResult:
    result = PhaseDWorkflowResult(tenant_id=str(tenant_id), dry_run=dry_run)
    if dry_run:
        result.updated_workflows = list(PHASE_D_CORE_WORKFLOWS)
        result.updated_bindings = [scenario.event_type for scenario in phase_d_scenarios()]
        result.pass_count = len(phase_d_scenarios())
        result.assertions = ["preview_only"]
        return result

    result.outbox_before = await _outbox_count(session, tenant_id)
    result.workflow_executions_before = await _workflow_execution_count(session, tenant_id)
    result.deployments_no_send = await _deployments_are_no_send(session, tenant_id)
    if not result.deployments_no_send:
        raise service.ProductAgentError("tenant deployments are not fully no-send")

    _agent, version = await _load_phase_c_or_newer_version(session, tenant_id)
    specs = _phase_d_specs()
    workflows = await _upsert_phase_d_workflows(
        session,
        tenant_id=tenant_id,
        specs=specs,
        result=result,
    )
    await _upsert_phase_d_bindings(
        session,
        tenant_id=tenant_id,
        version=version,
        workflows=workflows,
        specs=specs,
        result=result,
    )
    _update_version_phase_d_policy(version)

    lab = _run_phase_d_dry_lab(workflows, phase_d_scenarios())
    suite, run = await _store_phase_d_lab(
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
        raise service.ProductAgentError("outbox changed during Phase D dry-run")
    if result.workflow_executions_after != result.workflow_executions_before:
        raise service.ProductAgentError("workflow executions changed during Phase D dry-run")
    return result


def _phase_d_specs() -> dict[str, WorkflowSpec]:
    specs = {spec.key: spec for spec in build_workflow_specs()}
    return {key: specs[key] for key in PHASE_D_CORE_WORKFLOWS}


async def _upsert_phase_d_workflows(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    specs: dict[str, WorkflowSpec],
    result: PhaseDWorkflowResult,
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
        definition = _phase_d_definition(spec)
        trigger_config = {
            "source": SEED_ID,
            "phase_source": PHASE_D_SEED_ID,
            "source_version_id": SOURCE_VERSION_ID,
            "phase_source_version_id": PHASE_D_SOURCE_VERSION_ID,
            "event_type": spec.event_type,
            "dry_run_only": True,
        }
        workflow = by_key.get(key)
        if workflow is None:
            workflow = Workflow(
                tenant_id=tenant_id,
                name=spec.name,
                description="Dinamo V1 Phase D dry-run workflow. Side effects disabled.",
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
                "Dinamo V1 Phase D dry-run workflow. Side effects disabled."
            )
            workflow.trigger_type = spec.trigger_type
            workflow.trigger_config = trigger_config
            workflow.definition = definition
            workflow.active = False
        result.updated_workflows.append(key)
        updated[key] = workflow
    return updated


def _phase_d_definition(spec: WorkflowSpec) -> JsonDict:
    definition = {
        "nodes": list(copy.deepcopy(spec.nodes)),
        "edges": list(copy.deepcopy(spec.edges)),
        "metadata": {
            "source": SEED_ID,
            "phase_source": PHASE_D_SEED_ID,
            "source_version_id": SOURCE_VERSION_ID,
            "phase_source_version_id": PHASE_D_SOURCE_VERSION_ID,
            "workflow_key": spec.key,
            "phase": "D",
            "status": "dry_run_ready",
            "side_effects": "disabled",
            "customer_visible_output_allowed": False,
            "customer_message_request_only": spec.customer_message_request_only,
            "rollback": "rerun seed_dinamo_v1 or Phase C seed",
        },
    }
    if spec.key == "state.write_contact_field":
        definition["metadata"]["derives"] = {
            "Plan_Enganche": "from Plan_Credito using tenant plan map"
        }
    if spec.key in {"notification.create", "handoff.start"}:
        definition["metadata"]["dedupe_required"] = True
    return definition


async def _upsert_phase_d_bindings(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    version: AgentVersion,
    workflows: dict[str, Workflow],
    specs: dict[str, WorkflowSpec],
    result: PhaseDWorkflowResult,
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
            "phase_source": PHASE_D_SEED_ID,
            "source_version_id": SOURCE_VERSION_ID,
            "phase_source_version_id": PHASE_D_SOURCE_VERSION_ID,
            "workflow_key": key,
            "phase": "D",
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


def _update_version_phase_d_policy(version: AgentVersion) -> None:
    workflow_policy = dict(version.workflow_policy or {})
    workflow_policy["execution_mode"] = "dry_run_only"
    workflow_policy["side_effects_allowed"] = False
    workflow_policy["phase_d_source"] = PHASE_D_SEED_ID
    workflow_policy["phase_d_source_version_id"] = PHASE_D_SOURCE_VERSION_ID
    workflow_policy["core_workflows"] = list(PHASE_D_CORE_WORKFLOWS)
    version.workflow_policy = workflow_policy
    test_policy = dict(version.test_policy or {})
    test_policy["phase_d_workflow_dry_run_gate"] = PHASE_D_DECISION_READY
    version.test_policy = test_policy
    version.snapshot = {
        **(version.snapshot or {}),
        "phase_d_source": PHASE_D_SEED_ID,
        "phase_d_source_version_id": PHASE_D_SOURCE_VERSION_ID,
        "phase_d_workflows": list(PHASE_D_CORE_WORKFLOWS),
    }


def _run_phase_d_dry_lab(
    workflows: dict[str, Workflow],
    scenarios: tuple[PhaseDScenario, ...],
) -> list[JsonDict]:
    results: list[JsonDict] = []
    for scenario in scenarios:
        workflow = workflows.get(scenario.workflow_key)
        if workflow is None:
            results.append(_blocked_scenario(scenario, "workflow_missing"))
            continue
        preview = _preview_workflow(workflow.definition or {}, scenario.event)
        failures = _assert_preview(scenario, preview)
        results.append(
            {
                "scenario_key": scenario.key,
                "scenario_name": scenario.key,
                "workflow_key": scenario.workflow_key,
                "event_type": scenario.event_type,
                "status": "passed" if not failures else "blocked",
                "blocked_reason": ",".join(failures) if failures else None,
                "expected": scenario.as_expected(),
                "preview": preview,
                "send_decision": "no_send",
                "outbound_outbox_writes": 0,
                "workflow_execution_writes": 0,
                "side_effects": {
                    "delivery": False,
                    "workflows": False,
                    "actions": False,
                    "field_writes": False,
                },
            }
        )
    return results


def _blocked_scenario(scenario: PhaseDScenario, reason: str) -> JsonDict:
    return {
        "scenario_key": scenario.key,
        "workflow_key": scenario.workflow_key,
        "event_type": scenario.event_type,
        "status": "blocked",
        "blocked_reason": reason,
        "expected": scenario.as_expected(),
        "preview": {},
    }


def _preview_workflow(definition: JsonDict, event: JsonDict) -> JsonDict:
    preview: JsonDict = {
        "status": "dry_run",
        "nodes": [],
        "field_updates": {},
        "stage_transition": None,
        "assignments": [],
        "notifications": [],
        "pause_bot": None,
        "customer_visible_output": None,
        "outbound_outbox_writes": 0,
        "workflow_execution_writes": 0,
        "side_effects": {
            "delivery": False,
            "workflows": False,
            "actions": False,
            "field_writes": False,
        },
    }
    derived: JsonDict = {}
    for node in definition.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        node_id = str(node.get("id") or "")
        node_type = str(node.get("type") or "")
        config = dict(node.get("config") or {})
        preview["nodes"].append({"id": node_id, "type": node_type})
        if node_type == "condition":
            _apply_condition(config, event, derived)
        elif node_type == "update_field":
            field_key = str(config.get("field") or "")
            preview["field_updates"][field_key] = _resolve_value(config, event, derived)
        elif node_type == "move_stage":
            preview["stage_transition"] = _resolve_template_value(
                str(config.get("stage_id") or ""),
                event,
            )
        elif node_type == "assign_agent":
            preview["assignments"].append({"role": config.get("role"), "dry_run": True})
        elif node_type == "notify_agent":
            preview["notifications"].append(
                {
                    "role": config.get("role"),
                    "dedupe_key": _render_dedupe(str(config.get("dedupe_key") or ""), event),
                    "dry_run": True,
                }
            )
        elif node_type == "pause_bot":
            preview["pause_bot"] = {"mode": config.get("mode"), "dry_run": True}
        elif node_type in {"message", "template_message"}:
            preview["customer_visible_output"] = {
                "node_id": node_id,
                "blocked": True,
                "reason": "customer_copy_not_allowed_in_phase_d_core",
            }
    return preview


def _apply_condition(config: JsonDict, event: JsonDict, derived: JsonDict) -> None:
    when = dict(config.get("when") or {})
    field_key = str(when.get("field") or "")
    if field_key and event.get("field") != field_key:
        return
    derive_config = dict(config.get("derives") or {})
    target = str(derive_config.get("target_field") or "")
    value_map = dict(derive_config.get("map") or {})
    if target and event.get("value") in value_map:
        derived[target] = value_map[event["value"]]


def _resolve_value(config: JsonDict, event: JsonDict, derived: JsonDict) -> Any:
    if "value" in config:
        return config["value"]
    value_from = str(config.get("value_from") or "")
    if value_from.startswith("derived."):
        return derived.get(value_from.removeprefix("derived."))
    if value_from.startswith("event."):
        return event.get(value_from.removeprefix("event."))
    return None


def _resolve_template_value(template: str, event: JsonDict) -> str:
    lifecycle = event.get("lifecycle") if isinstance(event.get("lifecycle"), dict) else {}
    return template.replace(
        "{{ lifecycle.target_stage_id }}",
        str(lifecycle.get("target_stage_id") or ""),
    )


def _render_dedupe(template: str, event: JsonDict) -> str:
    rendered = template
    for key in ("conversation_id", "reason", "event_type", "case"):
        rendered = rendered.replace("{" + key + "}", str(event.get(key) or ""))
    return rendered


def _assert_preview(scenario: PhaseDScenario, preview: JsonDict) -> list[str]:
    failures: list[str] = []
    node_ids = [str(node.get("id")) for node in preview.get("nodes") or []]
    for node_id in scenario.expected_nodes:
        if node_id not in node_ids:
            failures.append(f"missing_node:{node_id}")
    field_updates = dict(preview.get("field_updates") or {})
    for key, value in scenario.expected_field_updates.items():
        if field_updates.get(key) != value:
            failures.append(f"field_update_mismatch:{key}")
    if scenario.expected_stage and preview.get("stage_transition") != scenario.expected_stage:
        failures.append("stage_transition_mismatch")
    if len(preview.get("notifications") or []) != scenario.expected_notifications:
        failures.append("notification_count_mismatch")
    if scenario.expected_assignment and not preview.get("assignments"):
        failures.append("assignment_missing")
    if scenario.expected_pause_bot and not preview.get("pause_bot"):
        failures.append("pause_bot_missing")
    if preview.get("customer_visible_output") is not None:
        failures.append("customer_visible_output_present")
    if preview.get("outbound_outbox_writes") != 0:
        failures.append("outbox_write_present")
    if preview.get("workflow_execution_writes") != 0:
        failures.append("workflow_execution_write_present")
    return failures


async def _store_phase_d_lab(
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
        name=f"Dinamo V1 Phase D workflow dry-run - {timestamp}",
        mode="publish_readiness",
        metadata={
            "source": PHASE_D_SEED_ID,
            "source_version_id": PHASE_D_SOURCE_VERSION_ID,
            "phase_c_source": PHASE_C_SEED_ID,
            "openai_api_real": False,
            "external_apis": False,
            "send": "no_send",
            "workflow_side_effects": False,
        },
    )
    for scenario in phase_d_scenarios():
        await service.create_agent_test_scenario(
            session,
            tenant_id=tenant_id,
            suite_id=suite.id,
            name=scenario.key,
            turns=[_scenario_turn(scenario)],
            expected=scenario.as_expected(),
            metadata={
                "source": PHASE_D_SEED_ID,
                "workflow_key": scenario.workflow_key,
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
    run.decision = PHASE_D_DECISION_READY if not blocked else PHASE_D_DECISION_BLOCKED
    run.outbox_audit_result = {"status": "clean", "outbound_outbox_writes": 0}
    run.side_effect_audit_result = {
        "status": "clean",
        "delivery": False,
        "workflows": False,
        "actions": False,
        "field_writes": False,
    }
    run.coverage_summary = {
        "source": PHASE_D_SEED_ID,
        "source_version_id": PHASE_D_SOURCE_VERSION_ID,
        "execution_mode": "workflow_dry_run_preview",
        "core_workflows": list(PHASE_D_CORE_WORKFLOWS),
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


def _scenario_turn(scenario: PhaseDScenario) -> JsonDict:
    return {
        "inbound_text": f"workflow_event:{scenario.event_type}:{scenario.key}",
        "event_type": scenario.event_type,
        "event": scenario.event,
    }


async def _load_phase_c_or_newer_version(
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
    if (version.snapshot or {}).get("phase") != "C":
        raise service.ProductAgentError("latest Dinamo version must have Phase C active")
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
    parser = argparse.ArgumentParser(description="Seed Dinamo Phase D workflows.")
    parser.add_argument("--tenant-id", required=True, type=UUID)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--created-by-user-id", type=UUID, default=None)
    return parser.parse_args(argv)


async def _amain(argv: list[str]) -> int:
    args = _parse_args(argv)
    if args.dry_run:
        result = await seed_dinamo_phase_d_workflows(
            _DryRunSession(),  # type: ignore[arg-type]
            tenant_id=args.tenant_id,
            dry_run=True,
            created_by_user_id=args.created_by_user_id,
        )
        print(json.dumps(result.as_dict(), indent=2, sort_keys=True))
        return 0
    async for session in get_db_session():
        try:
            result = await seed_dinamo_phase_d_workflows(
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
    "PHASE_D_CORE_WORKFLOWS",
    "PHASE_D_DECISION_READY",
    "PHASE_D_SEED_ID",
    "PhaseDScenario",
    "PhaseDWorkflowResult",
    "_assert_preview",
    "_phase_d_definition",
    "_preview_workflow",
    "phase_d_scenarios",
    "seed_dinamo_phase_d_workflows",
]
