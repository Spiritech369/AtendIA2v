from __future__ import annotations

# ruff: noqa: E501
import asyncio
import hashlib
import json
import os
import re
import unicodedata
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from atendia.agent_runtime.agent_config import agent_studio_config_from_values
from atendia.config import Settings
from atendia.simulation.safety import safety_counters, safety_delta

TENANT_EMAIL = "dinamomotosnl@gmail.com"
TENANT_ID = UUID("6ad78236-1fc9-467a-858d-90d248d57ee5")
AGENT_ID = UUID("c169deec-226d-55b7-bd07-270f339e75a6")
READINESS_SUITE_ID = "agent_runtime_v2_dinamo_fresh_openai_readiness"
REPORT_DATE = date(2026, 6, 2)
REPORT_DIR = Path(__file__).resolve().parents[3] / "docs" / "reports"
FACTUAL_SOURCE_NAMES = {"catalogo_dinamo", "requisitos_dinamo", "faq_dinamo"}
NON_FACTUAL_SOURCE_NAMES = {"prompt_agente_dinamo", "flujo_dinamo_orden_caos"}
ALLOWED_STAGES = {
    "nuevos",
    "plan",
    "cliente_potencial",
    "papeleria_incompleta",
    "papeleria_completa",
    "galgo",
    "sistema",
    "cliente_cerrado",
}
AI_FORBIDDEN_FIELD_KEYS = {"Autorizado"}
AI_FORBIDDEN_STAGE_KEYS = {"sistema", "cliente_cerrado"}


def configure_safe_openai_env() -> None:
    if not os.environ.get("ATENDIA_V2_OPENAI_API_KEY") and os.environ.get("OPENAI_API_KEY"):
        os.environ["ATENDIA_V2_OPENAI_API_KEY"] = os.environ["OPENAI_API_KEY"]
    os.environ["ATENDIA_V2_AGENT_RUNTIME_V2_ENABLED"] = "true"
    os.environ["ATENDIA_V2_AGENT_RUNTIME_V2_SEND_ENABLED"] = "false"
    os.environ["ATENDIA_V2_AGENT_RUNTIME_V2_ACTIONS_ENABLED"] = "false"
    os.environ["ATENDIA_V2_AGENT_RUNTIME_V2_WORKFLOW_EVENTS_ENABLED"] = "false"
    os.environ["ATENDIA_V2_AGENT_RUNTIME_V2_MODEL_PROVIDER"] = "openai"


def report_path(name: str, report_date: date = REPORT_DATE, suffix: str = "md") -> Path:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    return REPORT_DIR / f"{name}_{report_date:%Y_%m_%d}.{suffix}"


def fold(value: str) -> str:
    normalized = unicodedata.normalize("NFD", value.casefold())
    return "".join(char for char in normalized if unicodedata.category(char) != "Mn")


def escape_md(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).replace("|", "\\|")


def jsonable(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, UUID):
        return str(value)
    return value


def payload_hash(payload: dict[str, Any]) -> str:
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


async def load_dinamo_precheck(
    session: AsyncSession,
    *,
    settings: Settings,
) -> dict[str, Any]:
    tenant_row = (
        await session.execute(
            text(
                """
                SELECT t.id, t.name, t.config, t.is_demo, tu.email
                FROM tenants t
                JOIN tenant_users tu ON tu.tenant_id = t.id
                WHERE tu.email = :email AND t.id = :tenant_id
                """
            ),
            {"email": TENANT_EMAIL, "tenant_id": TENANT_ID},
        )
    ).mappings().first()
    agent_row = (
        await session.execute(
            text(
                """
                SELECT id, tenant_id, name, role, status, system_prompt, tone, language,
                       knowledge_config, auto_actions, extraction_config,
                       flow_mode_rules, ops_config
                FROM agents
                WHERE id = :agent_id AND tenant_id = :tenant_id
                """
            ),
            {"agent_id": AGENT_ID, "tenant_id": TENANT_ID},
        )
    ).mappings().first()
    source_rows = (
        await session.execute(
            text(
                """
                SELECT id, name, content_type, status, metadata_json
                FROM knowledge_sources
                WHERE tenant_id = :tenant_id
                ORDER BY name
                """
            ),
            {"tenant_id": TENANT_ID},
        )
    ).mappings().all()
    tenant_config = dict(tenant_row["config"] or {}) if tenant_row else {}
    rollout = dict(tenant_config.get("agent_runtime_v2") or {})
    studio_config: dict[str, Any] = {}
    if agent_row:
        studio_config = agent_studio_config_from_values(
            role=agent_row["role"],
            system_prompt=agent_row["system_prompt"],
            tone=agent_row["tone"],
            language=agent_row["language"],
            knowledge_config=dict(agent_row["knowledge_config"] or {}),
            auto_actions=dict(agent_row["auto_actions"] or {}),
            extraction_config=dict(agent_row["extraction_config"] or {}),
            flow_mode_rules=dict(agent_row["flow_mode_rules"] or {}),
            ops_config=dict(agent_row["ops_config"] or {}),
        )
    sources = [dict(row) for row in source_rows]
    enabled_ids = {str(value) for value in studio_config.get("enabled_knowledge_source_ids", [])}
    enabled_sources = [row for row in sources if str(row["id"]) in enabled_ids]
    factual_enabled = [
        str(row["name"])
        for row in enabled_sources
        if str(row["name"]) not in NON_FACTUAL_SOURCE_NAMES
    ]
    non_factual_enabled = [
        str(row["name"])
        for row in enabled_sources
        if str(row["name"]) in NON_FACTUAL_SOURCE_NAMES
    ]
    expected_rollout = {
        "runtime_v2_enabled": True,
        "preview_enabled": True,
        "model_provider_enabled": True,
        "send_enabled": False,
        "manual_send_enabled": False,
        "auto_send_enabled": False,
        "actions_enabled": False,
        "workflow_events_enabled": False,
        "outbox_enabled": False,
        "rollout_mode": "preview_only",
    }
    checks = {
        "tenant_verified": bool(tenant_row and str(tenant_row["id"]) == str(TENANT_ID)),
        "tenant_is_real": bool(tenant_row and not tenant_row["is_demo"]),
        "agent_verified": bool(agent_row and str(agent_row["id"]) == str(AGENT_ID)),
        "rollout_flags_safe": all(rollout.get(key) == value for key, value in expected_rollout.items()),
        "openai_key_present": bool(settings.openai_api_key),
        "provider_openai": settings.agent_runtime_v2_model_provider == "openai",
        "model_present": bool(settings.agent_runtime_v2_model),
        "factual_sources_only": set(factual_enabled) == FACTUAL_SOURCE_NAMES,
        "non_factual_sources_disabled": not non_factual_enabled,
        "prompt_and_flow_present": NON_FACTUAL_SOURCE_NAMES.issubset({str(row["name"]) for row in sources}),
    }
    critical_passed = all(checks.values())
    return {
        "tenant": dict(tenant_row) if tenant_row else None,
        "agent": dict(agent_row) if agent_row else None,
        "rollout": rollout,
        "expected_rollout": expected_rollout,
        "sources": sources,
        "enabled_sources": enabled_sources,
        "factual_enabled": factual_enabled,
        "non_factual_enabled": non_factual_enabled,
        "studio_config": studio_config,
        "checks": checks,
        "critical_passed": critical_passed,
        "provider": "openai",
        "model": settings.agent_runtime_v2_model,
        "openai_key_present": bool(settings.openai_api_key),
    }


async def load_dinamo_precheck_with_retry(
    session_factory: Any,
    *,
    settings: Settings,
    attempts: int = 2,
    timeout_s: float = 20.0,
    backoff_s: float = 1.0,
) -> dict[str, Any]:
    last_exc: BaseException | None = None
    for attempt in range(1, attempts + 1):
        try:
            print(f"dinamo_precheck stage=load attempt={attempt}/{attempts}")
            async with session_factory() as session:
                result = await asyncio.wait_for(
                    load_dinamo_precheck(session, settings=settings),
                    timeout=timeout_s,
                )
                await session.rollback()
                print(f"dinamo_precheck stage=load attempt={attempt} status=ok")
                return result
        except TimeoutError as exc:
            last_exc = exc
            print(
                f"dinamo_precheck stage=load attempt={attempt} status=timeout "
                f"timeout_s={timeout_s}"
            )
        except Exception as exc:
            last_exc = exc
            print(
                f"dinamo_precheck stage=load attempt={attempt} status=error "
                f"error_type={type(exc).__name__}"
            )
        if attempt < attempts:
            await asyncio.sleep(backoff_s * attempt)
    raise RuntimeError(
        f"dinamo precheck failed after {attempts} attempts; "
        f"last_error={type(last_exc).__name__ if last_exc else 'Unknown'}"
    ) from last_exc


def write_precheck_report(precheck: dict[str, Any], *, report_date: date = REPORT_DATE) -> Path:
    path = report_path("dinamo_openai_precheck", report_date)
    check_lines = "\n".join(
        f"- {key}: `{'pass' if value else 'fail'}`"
        for key, value in precheck["checks"].items()
    )
    source_rows = "\n".join(
        f"| `{row['name']}` | `{row['id']}` | `{row['content_type']}` | `{row['status']}` | "
        f"`{row['name'] in precheck['factual_enabled']}` |"
        for row in precheck["sources"]
    )
    path.write_text(
        f"""# Dinamo OpenAI Precheck - {report_date:%Y-%m-%d}

## Identity

- tenant_email: `{TENANT_EMAIL}`
- tenant_id: `{TENANT_ID}`
- agent_id: `{AGENT_ID}`
- provider/model: `openai` / `{precheck['model']}`
- OPENAI_API_KEY present: `{str(precheck['openai_key_present']).lower()}`
- critical_passed: `{str(precheck['critical_passed']).lower()}`

## Rollout Config

```json
{json.dumps(precheck['rollout'], ensure_ascii=False, indent=2, default=str)}
```

## Checks

{check_lines}

## Knowledge Sources

| source | id | content_type | status | factual_enabled |
| --- | --- | --- | --- | --- |
{source_rows}

## Factual Source Decision

- factual_sources_enabled: `{precheck['factual_enabled']}`
- non_factual_sources_enabled: `{precheck['non_factual_enabled']}`
- prompt_agente_dinamo: `configuration/instructions only`
- flujo_dinamo_orden_caos: `eval/simulation only`

## Decision

{('OpenAI provider run allowed.' if precheck['critical_passed'] else 'OpenAI provider run blocked until failed checks are fixed.')}
""",
        encoding="utf-8",
    )
    return path


def write_db_precheck_stability_report(
    payload: dict[str, Any],
    *,
    report_date: date = REPORT_DATE,
) -> Path:
    path = report_path("dinamo_db_precheck_stability", report_date)
    path.write_text(
        f"""# Dinamo DB Precheck Stability - {report_date:%Y-%m-%d}

## Result

- status: `{payload.get('status')}`
- attempts: `{payload.get('attempts')}`
- timeout_s: `{payload.get('timeout_s')}`
- tenant_id: `{TENANT_ID}`
- agent_id: `{AGENT_ID}`

## Notes

{payload.get('notes') or ''}

```json
{json.dumps(payload, ensure_ascii=False, indent=2, default=str)}
```
""",
        encoding="utf-8",
    )
    return path


def write_approval_record(
    *,
    model: str,
    report_date: date = REPORT_DATE,
) -> dict[str, Path]:
    requested = report_path("dinamo_openai_provider_approval_record", report_date)
    gate_compat = report_path("dinamo_model_provider_approval_record", report_date)
    content = f"""# Dinamo OpenAI Provider Approval Record - {report_date:%Y-%m-%d}

- approval_status: `approved`
- approver: `tenant operator explicit approval`
- tenant_id: `{TENANT_ID}`
- agent_id: `{AGENT_ID}`
- provider: `openai`
- model: `{model}`
- retention mode: `provider_default_no_secret_logging`
- region/data policy: `safe-preview-no-send`
- scope: `test-turn / preview / simulation / shadow no-send only`
- send_enabled: `false`
- manual_send_enabled: `false`
- auto_send_enabled: `false`
- actions_enabled: `false`
- workflow_events_enabled: `false`
- outbox_enabled: `false`
- allowed data categories: `latest customer message, minimal recent conversation history, limited Knowledge OS snippets/citations, lifecycle stage/status, available contact field schema, agent instructions, allowed action identifiers, citations`
- forbidden data categories: `API keys, tokens, secrets, attachments, full conversation history, full internal config, real write results, unnecessary phone numbers, unnecessary emails, WhatsApp media`
- payload minimization: `redact phone/email-like values when not needed; send only required knowledge snippets; log only payload hash/summary, not full sensitive payload; never log OPENAI_API_KEY`

This approval is restricted to AgentRuntime v2 provider testing for the tenant and agent above. It does not approve WhatsApp sends, outbox writes, real actions, manual-send, auto-send, or workflow event execution.
"""
    requested.write_text(content, encoding="utf-8")
    gate_compat.write_text(content, encoding="utf-8")
    return {"requested": requested, "gate_compat": gate_compat}


async def side_effect_snapshot(session: AsyncSession) -> dict[str, int]:
    return await safety_counters(session, tenant_id=TENANT_ID)


def no_real_side_effects(delta: dict[str, int]) -> bool:
    return all(
        delta.get(key, 0) == 0
        for key in (
            "whatsapp_sends",
            "outbound_outbox",
            "real_customers",
            "workflow_executions",
        )
    )


async def compute_side_effect_delta(
    session: AsyncSession,
    before: dict[str, int],
) -> dict[str, int]:
    after = await side_effect_snapshot(session)
    return safety_delta(before, after)


async def update_readiness_gate(
    session: AsyncSession,
    *,
    passed: bool,
    score: float,
    scenario_count: int,
    failed_scenarios: list[str],
    metadata: dict[str, Any],
) -> None:
    await session.execute(
        text(
            """
            INSERT INTO agent_readiness_eval_results
              (id, tenant_id, agent_id, suite_id, score, passed, scenario_count,
               failed_scenarios, policy_failures, metadata)
            VALUES
              (:id, :tenant_id, :agent_id, :suite_id, :score, :passed, :scenario_count,
               CAST(:failed_scenarios AS jsonb), CAST('[]' AS jsonb), CAST(:metadata AS jsonb))
            """
        ),
        {
            "id": uuid4(),
            "tenant_id": TENANT_ID,
            "agent_id": AGENT_ID,
            "suite_id": READINESS_SUITE_ID,
            "score": score,
            "passed": passed,
            "scenario_count": scenario_count,
            "failed_scenarios": json.dumps(failed_scenarios, ensure_ascii=False),
            "metadata": json.dumps(metadata, ensure_ascii=False, default=str),
        },
    )
    row = (
        await session.execute(
            text("SELECT config FROM tenants WHERE id = :tenant_id"),
            {"tenant_id": TENANT_ID},
        )
    ).scalar_one()
    config = dict(row or {})
    rollout = dict(config.get("agent_runtime_v2") or {})
    rollout.update(
        {
            "required_eval_suite_passed": passed,
            "ready_for_live_preview": passed,
            "ready_for_shadow": "conditional" if passed else False,
            "ready_for_manual_send": False,
            "send_enabled": False,
            "manual_send_enabled": False,
            "auto_send_enabled": False,
            "actions_enabled": False,
            "workflow_events_enabled": False,
            "outbox_enabled": False,
            "rollout_mode": "preview_only",
            "last_readiness_suite_id": READINESS_SUITE_ID,
            "last_readiness_score": score,
            "last_readiness_updated_at": datetime.now(UTC).isoformat(),
        }
    )
    config["agent_runtime_v2"] = rollout
    await session.execute(
        text("UPDATE tenants SET config = CAST(:config AS jsonb) WHERE id = :tenant_id"),
        {
            "tenant_id": TENANT_ID,
            "config": json.dumps(config, ensure_ascii=False, default=str),
        },
    )


def scenario_failed_checks(result: dict[str, Any]) -> list[str]:
    checks = dict(result.get("checks") or {})
    return [key for key, value in checks.items() if not value]
