"""Activate Dinamo Phase C agent configuration without live send or OpenAI.

Phase C of ``DINAMO_TENANT_RUNTIME_PLAN_V1.md`` updates the Product Agent
version with the edited Francisco prompt, tool/field/workflow policy metadata,
and post-handoff limited-mode policy. This seed is intentionally DB-backed and
no-send only; it does not call OpenAI or any external API.

Usage:
    PYTHONPATH=. uv run python -m atendia.scripts.seed_dinamo_phase_c_agent \
        --tenant-id <uuid> [--dry-run]
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import hashlib
import json
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from atendia.db.models.agent import Agent
from atendia.db.models.knowledge_os import KnowledgeSource
from atendia.db.models.product_agent import (
    AgentDeployment,
    AgentKnowledgeSourceBinding,
    AgentToolBinding,
    AgentVersion,
)
from atendia.scripts.seed_dinamo_v1 import (
    AGENT_NAME,
    AGENT_ROLE,
    FIELD_SPECS,
    build_agent_field_policy_fields,
    build_agent_workflow_policy_bindings,
    build_tool_binding_specs,
)
from atendia.scripts.seed_dinamo_v1 import (
    SEED_ID as PHASE_A_SEED_ID,
)

PHASE_C_SEED_ID = "dinamo_tenant_runtime_plan_v1_phase_c"
SOURCE_VERSION_ID = "DINAMO_TENANT_RUNTIME_PLAN_V1:PHASE_C:2026-06-11"
ROOT = Path(__file__).resolve().parents[3]
DINAMO_DIR = ROOT / "docs" / "tenant_sources" / "dinamo"
PROMPT_SOURCE_PATH = DINAMO_DIR / "Prompt Agente IA.txt"
RUNTIME_PROMPT_PATH = DINAMO_DIR / "Prompt.txt"
REQUIRED_SOURCE_IDS = (
    "dinamo_catalogo_junio_2026",
    "dinamo_requisitos_junio_2026",
)
OPTIONAL_SOURCE_IDS = ("dinamo_faq_junio_2026",)
REQUIRED_TOOLS = ("catalog.search", "quote.resolve", "requirements.lookup")
OPTIONAL_TOOLS = (
    "faq.lookup",
    "document.check",
    "expediente.evaluate",
    "handoff.request",
    "followup.schedule",
)


@dataclass
class PhaseCResult:
    tenant_id: str
    dry_run: bool
    prompt_source_hash: str
    runtime_prompt_hash: str
    required_sources_checked: list[str] = field(default_factory=list)
    optional_sources_checked: list[str] = field(default_factory=list)
    updated_agent: bool = False
    updated_version: bool = False
    updated_tool_bindings: list[str] = field(default_factory=list)
    deployment_guard: str = "not_checked"
    openai_api_real: bool = False
    external_apis: bool = False
    send: str = "no_send"
    gate_status: str = "phase_c_config_ready_openai_gate_pending"

    def as_dict(self) -> dict[str, Any]:
        return {
            "tenant_id": self.tenant_id,
            "dry_run": self.dry_run,
            "prompt_source_hash": self.prompt_source_hash,
            "runtime_prompt_hash": self.runtime_prompt_hash,
            "required_sources_checked": self.required_sources_checked,
            "optional_sources_checked": self.optional_sources_checked,
            "updated_agent": self.updated_agent,
            "updated_version": self.updated_version,
            "updated_tool_bindings": self.updated_tool_bindings,
            "deployment_guard": self.deployment_guard,
            "openai_api_real": self.openai_api_real,
            "external_apis": self.external_apis,
            "send": self.send,
            "gate_status": self.gate_status,
        }


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _prompt_source_metadata() -> dict[str, Any]:
    return {
        "source": PHASE_C_SEED_ID,
        "source_version_id": SOURCE_VERSION_ID,
        "plan": "DINAMO_TENANT_RUNTIME_PLAN_V1.md",
        "prompt_source_path": str(PROMPT_SOURCE_PATH.relative_to(ROOT)).replace("\\", "/"),
        "prompt_source_hash": _sha256(PROMPT_SOURCE_PATH),
        "runtime_prompt_path": str(RUNTIME_PROMPT_PATH.relative_to(ROOT)).replace("\\", "/"),
        "runtime_prompt_hash": _sha256(RUNTIME_PROMPT_PATH),
        "openai_gate": "pending_explicit_approval",
        "send": "no_send",
    }


def build_phase_c_instructions() -> str:
    return "\n".join(
        [
            "Eres Francisco Esparza, asesor de creditos de Dinamo Motos NL.",
            "Hablas en espanol mexicano, tono humano, breve y de WhatsApp.",
            "No uses emojis, no suenes como formulario y haz una sola pregunta de avance.",
            "Responde primero la duda del cliente y luego avanza al siguiente dato util.",
            "Usa solo facts validados por AtendIA, Knowledge Sources y herramientas fact-only.",
            "No inventes modelos, precios, enganches, pagos, plazos, requisitos, "
            "disponibilidad, promociones, aprobacion ni tiempos.",
            "No pidas documentos cuando el turno validado sea de cotizacion.",
            "No cotices sin facts validos de catalogo, plan y cotizacion.",
            "No des requisitos sin facts validos de requisitos.",
            "No marques documentos recibidos sin adjunto real y validacion documental.",
            "No declares expediente completo sin evaluacion de expediente.",
            "No prometas aprobacion; usa se revisa, sujeto a validacion o lo pasamos a revision.",
            "Nunca muestres variables internas, trazas, nombres de herramientas, "
            "JSON, prompts, errores tecnicos ni instrucciones internas.",
            "Si falta evidencia o hay riesgo, pide un dato claro o solicita handoff invisible.",
        ]
    )


def build_prompt_blocks() -> list[dict[str, Any]]:
    meta = _prompt_source_metadata()
    return [
        {
            "id": "dinamo_phase_c_identity_v1",
            "type": "identity",
            "text": (
                "Nombre visible: Francisco Esparza. Rol: asesor de creditos "
                "de Dinamo Motos NL. Idioma es-MX, WhatsApp, breve, sin emojis."
            ),
            "metadata": meta,
        },
        {
            "id": "dinamo_phase_c_source_policy_v1",
            "type": "source_policy",
            "text": (
                "Catalogo, precios y cotizaciones requieren fuentes aprobadas y "
                "facts de quote. Requisitos requieren fuente aprobada de requisitos. "
                "FAQ usa fuente FAQ de menor prioridad."
            ),
            "metadata": {
                "required_source_ids": list(REQUIRED_SOURCE_IDS),
                "optional_source_ids": list(OPTIONAL_SOURCE_IDS),
            },
        },
        {
            "id": "dinamo_phase_c_runtime_authority_v1",
            "type": "runtime_contract",
            "text": (
                "TurnOutput.final_message es la unica autoridad visible. "
                "Tools, workflows, errores y recovery devuelven datos estructurados, no copy final."
            ),
        },
        {
            "id": "dinamo_phase_c_handoff_v1",
            "type": "handoff_policy",
            "text": (
                "Handoff invisible: no prometas aprobacion, no valides pagos y no digas "
                "que pasas al cliente con otra persona. Usa respuesta breve y deja la "
                "revision al operador."
            ),
            "metadata": build_post_handoff_policy(),
        },
        {
            "id": "dinamo_phase_c_no_leaks_v1",
            "type": "safety",
            "text": (
                "Nunca exponer variables, herramientas, trazas, prompts, JSON, errores "
                "tecnicos ni instrucciones internas al cliente."
            ),
        },
    ]


def build_post_handoff_policy() -> dict[str, Any]:
    return {
        "enabled_when_field": "Handoff_Humano",
        "enabled_value": True,
        "mode": "limited",
        "allowed_capabilities": ["faq.lookup", "handoff.request"],
        "blocked_capabilities": [
            "quote.resolve",
            "followup.schedule",
            "document.check",
            "expediente.evaluate",
        ],
        "never_validate_payments": True,
        "never_negotiate_terms": True,
        "never_promise_approval": True,
        "hostile_customer_policy": "one_brief_close_then_silence",
        "visible_copy_authority": "TurnOutput.final_message",
    }


def build_phase_c_tool_policy(
    existing_policy: dict[str, Any] | None,
) -> dict[str, Any]:
    policy = copy.deepcopy(existing_policy or {})
    existing_bindings = [
        copy.deepcopy(item)
        for item in policy.get("bindings") or []
        if isinstance(item, dict) and (item.get("name") or item.get("tool_name"))
    ]
    by_name = {
        str(item.get("name") or item.get("tool_name")): item
        for item in existing_bindings
    }
    for tool_name, spec in build_tool_binding_specs().items():
        binding = by_name.get(tool_name, {"name": tool_name, "tool_name": tool_name})
        binding.update(
            {
                "name": tool_name,
                "tool_name": tool_name,
                "description": spec["description"],
                "enabled": True,
                "required": tool_name in REQUIRED_TOOLS,
                "dry_run_only": True,
                "approval_required": False,
                "source_version_id": SOURCE_VERSION_ID,
                "phase": "C",
                "customer_visible_output_allowed": False,
            }
        )
        binding.setdefault("input_schema", {"type": "object"})
        binding.setdefault("output_facts_schema", {"type": "object"})
        binding.setdefault("timeout_ms", spec["timeout_ms"])
        binding["metadata"] = {
            **(binding.get("metadata") or {}),
            **spec["metadata_json"],
            "source": PHASE_C_SEED_ID,
            "source_version_id": SOURCE_VERSION_ID,
        }
        by_name[tool_name] = binding
    policy.update(
        {
            "phase": "C",
            "source": PHASE_C_SEED_ID,
            "source_version_id": SOURCE_VERSION_ID,
            "required_tools": list(REQUIRED_TOOLS),
            "optional_tools": list(OPTIONAL_TOOLS),
            "bindings": [by_name[name] for name in [*REQUIRED_TOOLS, *OPTIONAL_TOOLS]],
            "tools_return_customer_copy": False,
            "missing_required_tool_means_no_send": True,
        }
    )
    return policy


def build_phase_c_payload(existing_version: AgentVersion | None = None) -> dict[str, Any]:
    existing_tool_policy = existing_version.tool_policy if existing_version else {}
    field_policy = {
        "source": PHASE_C_SEED_ID,
        "source_version_id": SOURCE_VERSION_ID,
        "fields": build_agent_field_policy_fields(),
        "post_handoff_policy": build_post_handoff_policy(),
    }
    workflow_policy = {
        "execution_mode": "dry_run_only",
        "side_effects_allowed": False,
        "customer_visible_output_allowed": False,
        "bindings": build_agent_workflow_policy_bindings(),
        "source": PHASE_C_SEED_ID,
        "source_version_id": SOURCE_VERSION_ID,
    }
    return {
        "name": AGENT_NAME,
        "role": AGENT_ROLE,
        "tone": "whatsapp_direct",
        "language": "es-MX",
        "instructions": build_phase_c_instructions(),
        "prompt_blocks": build_prompt_blocks(),
        "knowledge_policy": {
            "phase": "C",
            "source": PHASE_C_SEED_ID,
            "source_version_id": SOURCE_VERSION_ID,
            "required_source_ids": list(REQUIRED_SOURCE_IDS),
            "optional_source_ids": list(OPTIONAL_SOURCE_IDS),
            "json_wins_over_docx": True,
            "quote_requires_catalog_source": True,
            "requirements_require_requirements_source": True,
        },
        "tool_policy": build_phase_c_tool_policy(existing_tool_policy),
        "action_policy": {
            "execution_mode": "disabled",
            "source": PHASE_C_SEED_ID,
            "source_version_id": SOURCE_VERSION_ID,
            "post_handoff_policy": build_post_handoff_policy(),
        },
        "field_policy": field_policy,
        "workflow_policy": workflow_policy,
        "safety_policy": {
            "phase": "C",
            "turn_output_final_message_authority": True,
            "required_tool_failure_means_no_send": True,
            "policy_failure_means_no_send": True,
            "internal_text_never_customer_visible": True,
            "no_tool_names_or_trace_leaks": True,
            "openai_api_real": False,
        },
        "test_policy": {
            "required_suite": "dinamo_v1_phase_a_no_send",
            "phase_c_openai_direct_provider_gate": "pending_explicit_approval",
            "no_send_test_lab_required": True,
        },
        "snapshot": {
            "source": PHASE_A_SEED_ID,
            "phase": "C",
            "phase_c_source": PHASE_C_SEED_ID,
            "phase_c_source_version_id": SOURCE_VERSION_ID,
            "prompt_source": _prompt_source_metadata(),
        },
        "change_summary": (
            "Dinamo V1 Phase C agent prompt and policy configuration active in no-send."
        ),
    }


async def _get_agent_and_version(
    session: AsyncSession,
    tenant_id: UUID,
) -> tuple[Agent, AgentVersion]:
    agent = (
        await session.execute(
            select(Agent).where(Agent.tenant_id == tenant_id, Agent.name == AGENT_NAME).limit(1)
        )
    ).scalar_one_or_none()
    if agent is None:
        raise RuntimeError("Dinamo Phase A agent is missing; run seed_dinamo_v1 first")
    version = (
        await session.execute(
            select(AgentVersion)
            .where(
                AgentVersion.tenant_id == tenant_id,
                AgentVersion.agent_id == agent.id,
                AgentVersion.status == "draft",
            )
            .order_by(AgentVersion.version_number.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if version is None:
        raise RuntimeError("Dinamo draft agent version is missing")
    return agent, version


async def _guard_no_send(session: AsyncSession, tenant_id: UUID, version: AgentVersion) -> str:
    rows = (
        await session.execute(
            select(AgentDeployment).where(
                AgentDeployment.tenant_id == tenant_id,
                AgentDeployment.active_version_id == version.id,
            )
        )
    ).scalars().all()
    unsafe = [
        row
        for row in rows
        if row.send_enabled
        or row.outbox_enabled
        or row.live_send_enabled
        or row.single_contact_smoke_enabled
        or row.actions_enabled
        or row.workflow_events_enabled
        or row.workflow_side_effects_enabled
        or row.canary_enabled
        or row.open_production_enabled
        or row.send_scope != "none"
    ]
    if unsafe:
        raise RuntimeError("Phase C refused to run: active deployment is not no-send")
    return f"checked_{len(rows)}_deployments_no_send"


async def _check_phase_b_sources(
    session: AsyncSession,
    tenant_id: UUID,
    version: AgentVersion,
) -> tuple[list[str], list[str]]:
    rows = (
        await session.execute(
            select(KnowledgeSource).where(KnowledgeSource.tenant_id == tenant_id)
        )
    ).scalars().all()
    by_source_id = {
        (row.metadata_json or {}).get("source_id"): row
        for row in rows
        if (row.metadata_json or {}).get("source_id")
    }
    missing = [
        source_id
        for source_id in REQUIRED_SOURCE_IDS
        if source_id not in by_source_id
        or by_source_id[source_id].status != "active"
        or (by_source_id[source_id].metadata_json or {}).get("runtime_status") != "approved"
    ]
    if missing:
        raise RuntimeError(f"Phase C refused to run: missing approved sources {missing}")
    required_source_uuids = [by_source_id[source_id].id for source_id in REQUIRED_SOURCE_IDS]
    binding_count = (
        await session.execute(
            select(AgentKnowledgeSourceBinding).where(
                AgentKnowledgeSourceBinding.tenant_id == tenant_id,
                AgentKnowledgeSourceBinding.agent_version_id == version.id,
                AgentKnowledgeSourceBinding.knowledge_source_id.in_(required_source_uuids),
                AgentKnowledgeSourceBinding.required.is_(True),
            )
        )
    ).scalars().all()
    if len(binding_count) != len(REQUIRED_SOURCE_IDS):
        raise RuntimeError("Phase C refused to run: required source bindings are missing")
    optional_present = [
        source_id
        for source_id in OPTIONAL_SOURCE_IDS
        if source_id in by_source_id and by_source_id[source_id].status == "active"
    ]
    return list(REQUIRED_SOURCE_IDS), optional_present


async def seed_dinamo_phase_c_agent(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    dry_run: bool = False,
) -> PhaseCResult:
    meta = _prompt_source_metadata()
    result = PhaseCResult(
        tenant_id=str(tenant_id),
        dry_run=dry_run,
        prompt_source_hash=meta["prompt_source_hash"],
        runtime_prompt_hash=meta["runtime_prompt_hash"],
    )
    if dry_run:
        result.required_sources_checked = list(REQUIRED_SOURCE_IDS)
        result.optional_sources_checked = list(OPTIONAL_SOURCE_IDS)
        result.updated_agent = True
        result.updated_version = True
        result.updated_tool_bindings = [*REQUIRED_TOOLS, *OPTIONAL_TOOLS]
        result.deployment_guard = "would_check_no_send"
        return result

    agent, version = await _get_agent_and_version(session, tenant_id)
    result.deployment_guard = await _guard_no_send(session, tenant_id, version)
    required_sources, optional_sources = await _check_phase_b_sources(
        session,
        tenant_id,
        version,
    )
    result.required_sources_checked = required_sources
    result.optional_sources_checked = optional_sources

    payload = build_phase_c_payload(version)
    agent.name = payload["name"]
    agent.role = payload["role"]
    agent.status = "draft"
    agent.behavior_mode = "strict"
    agent.tone = payload["tone"]
    agent.language = payload["language"]
    agent.max_sentences = 2
    agent.no_emoji = True
    agent.system_prompt = payload["instructions"]
    agent.knowledge_config = payload["knowledge_policy"]
    agent.extraction_config = {
        "visible_contact_field_keys": [spec.key for spec in FIELD_SPECS],
        "post_handoff_policy": build_post_handoff_policy(),
    }
    agent.ops_config = {
        **(agent.ops_config or {}),
        PHASE_C_SEED_ID: {
            "agent": True,
            "source_version_id": SOURCE_VERSION_ID,
            "phase": "C",
            "live_scope": "none",
            "openai_api_real": False,
        },
        "product_first": True,
    }
    result.updated_agent = True

    version.role = payload["role"]
    version.tone = payload["tone"]
    version.language = payload["language"]
    version.instructions = payload["instructions"]
    version.prompt_blocks = payload["prompt_blocks"]
    version.knowledge_policy = payload["knowledge_policy"]
    version.tool_policy = payload["tool_policy"]
    version.action_policy = payload["action_policy"]
    version.field_policy = payload["field_policy"]
    version.workflow_policy = payload["workflow_policy"]
    version.safety_policy = payload["safety_policy"]
    version.test_policy = payload["test_policy"]
    version.snapshot = {**(version.snapshot or {}), **payload["snapshot"]}
    version.change_summary = payload["change_summary"]
    result.updated_version = True

    await _update_tool_binding_metadata(
        session,
        tenant_id=tenant_id,
        version=version,
        result=result,
    )
    await session.flush()
    return result


async def _update_tool_binding_metadata(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    version: AgentVersion,
    result: PhaseCResult,
) -> None:
    rows = (
        await session.execute(
            select(AgentToolBinding).where(
                AgentToolBinding.tenant_id == tenant_id,
                AgentToolBinding.agent_version_id == version.id,
            )
        )
    ).scalars().all()
    by_name = {row.tool_name: row for row in rows}
    for tool_name in [*REQUIRED_TOOLS, *OPTIONAL_TOOLS]:
        row = by_name.get(tool_name)
        if row is None:
            continue
        row.enabled = True
        row.required = tool_name in REQUIRED_TOOLS
        row.metadata_json = {
            **(row.metadata_json or {}),
            "source": PHASE_C_SEED_ID,
            "source_version_id": SOURCE_VERSION_ID,
            "phase": "C",
            "customer_visible_output_allowed": False,
            "post_handoff_limited": tool_name in {"faq.lookup", "handoff.request"},
        }
        result.updated_tool_bindings.append(tool_name)


async def _main(tenant_id: UUID, dry_run: bool) -> int:
    if dry_run:
        result = await seed_dinamo_phase_c_agent(
            _DryRunSession(),  # type: ignore[arg-type]
            tenant_id=tenant_id,
            dry_run=True,
        )
        print(json.dumps(result.as_dict(), indent=2, ensure_ascii=False))
        print(f"completed_at={datetime.now(UTC).isoformat()}")
        return 0

    from atendia.db.session import _get_factory  # type: ignore[attr-defined]

    factory = _get_factory()
    async with factory() as session:
        result = await seed_dinamo_phase_c_agent(session, tenant_id=tenant_id, dry_run=False)
        await session.commit()
    print(json.dumps(result.as_dict(), indent=2, ensure_ascii=False))
    print(f"completed_at={datetime.now(UTC).isoformat()}")
    return 0


class _DryRunSession:
    """Marker object; dry-run returns before DB access."""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant-id", type=UUID, required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    return asyncio.run(_main(args.tenant_id, args.dry_run))


if __name__ == "__main__":
    sys.exit(main())
