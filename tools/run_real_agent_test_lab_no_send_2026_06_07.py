from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from atendia.config import get_settings
from atendia.product_agents import service, test_lab

os.environ.setdefault("ATENDIA_V2_AGENT_RUNTIME_V2_SEND_ENABLED", "false")
os.environ.setdefault("ATENDIA_V2_AGENT_RUNTIME_V2_ACTIONS_ENABLED", "false")
os.environ.setdefault("ATENDIA_V2_AGENT_RUNTIME_V2_WORKFLOW_EVENTS_ENABLED", "false")


REPO_ROOT = Path(__file__).resolve().parents[1]
TENANT_CONFIG_DIR = REPO_ROOT / "docs" / "tenant_sources" / "dinamo"
CONTRACT_PATH = TENANT_CONFIG_DIR / "dinamo_runtime_contract.json"
MANIFEST_PATH = TENANT_CONFIG_DIR / "dinamo_knowledge_sources_manifest.json"
SCENARIOS_PATH = TENANT_CONFIG_DIR / "dinamo_test_lab_scenarios.json"
_SCENARIO_CONFIG = (
    json.loads(SCENARIOS_PATH.read_text(encoding="utf-8")) if SCENARIOS_PATH.exists() else {}
)
_SCENARIO_BY_NAME = {
    str(scenario.get("name")): scenario
    for scenario in _SCENARIO_CONFIG.get("scenarios", [])
    if isinstance(scenario, dict)
}
SCENARIO_A = list(_SCENARIO_BY_NAME.get("Negocio ambiguo", {}).get("turns", []))
SCENARIO_B = list(_SCENARIO_BY_NAME.get("Skeleton buro tarjeta", {}).get("turns", []))


def _scenario_payload(
    name: str,
    turns: list[dict[str, Any]],
    *,
    expected_turns: list[dict[str, Any]],
) -> tuple[str, list[dict[str, Any]], dict[str, Any]]:
    del expected_turns
    scenario = _SCENARIO_BY_NAME.get(name, {})
    expected = {
        **dict(_SCENARIO_CONFIG.get("global_expected") or {}),
        **dict(scenario.get("expected") or {}),
    }
    return name, list(scenario.get("turns") or turns), expected


async def _audit(session, tenant_id: UUID) -> dict[str, Any]:
    outbox = (
        await session.execute(
            text(
                """SELECT count(*)
                FROM outbound_outbox
                WHERE tenant_id = :tenant_id
                  AND status IN ('pending', 'retry')"""
            ),
            {"tenant_id": tenant_id},
        )
    ).scalar_one()
    side_effects = (
        await session.execute(
            text(
                """SELECT count(*)
                FROM business_event_ledger
                WHERE tenant_id = :tenant_id
                  AND side_effects_allowed = true"""
            ),
            {"tenant_id": tenant_id},
        )
    ).scalar_one()
    return {
        "outbound_outbox_pending_retry": int(outbox),
        "business_event_ledger_side_effects_allowed": int(side_effects),
    }


async def _select_version(
    session,
    *,
    tenant_id: UUID,
    agent_id: UUID,
    contract_checksum: str,
) -> tuple[UUID, UUID, UUID] | None:
    row = (
        await session.execute(
            text(
                """SELECT av.tenant_id, av.agent_id, av.id AS version_id
                FROM agent_versions av
                WHERE av.tenant_id = :tenant_id
                  AND av.agent_id = :agent_id
                  AND av.snapshot ->> 'runtime_contract_checksum' = :contract_checksum
                ORDER BY av.created_at DESC
                LIMIT 1"""
            ),
            {
                "tenant_id": tenant_id,
                "agent_id": agent_id,
                "contract_checksum": contract_checksum,
            },
        )
    ).mappings().first()
    if row is None:
        return None
    return UUID(str(row["tenant_id"])), UUID(str(row["agent_id"])), UUID(str(row["version_id"]))


async def _select_or_seed_version(session) -> tuple[UUID, UUID, UUID] | None:
    if not _config_paths_exist():
        return None
    contract = _load_json(CONTRACT_PATH)
    contract_checksum = _file_sha256(CONTRACT_PATH)
    tenant_id = UUID(str(contract["tenant_id"]))
    agent_id = UUID(str(contract["agent_id"]))
    selected = await _select_version(
        session,
        tenant_id=tenant_id,
        agent_id=agent_id,
        contract_checksum=contract_checksum,
    )
    if selected is not None:
        return selected

    agent = (
        await session.execute(
            text(
                """SELECT id, tenant_id
                FROM agents
                WHERE tenant_id = :tenant_id AND id = :agent_id
                LIMIT 1"""
            ),
            {"tenant_id": tenant_id, "agent_id": agent_id},
        )
    ).mappings().first()
    if agent is None:
        return None

    next_version_number = int(
        (
            await session.execute(
                text(
                    """SELECT COALESCE(MAX(version_number), 0) + 1
                    FROM agent_versions
                    WHERE tenant_id = :tenant_id AND agent_id = :agent_id"""
                ),
                {"tenant_id": agent["tenant_id"], "agent_id": agent["id"]},
            )
        ).scalar_one()
    )

    row = (
        await session.execute(
            text(
                """INSERT INTO agent_versions (
                    id, tenant_id, agent_id, version_number, status, is_immutable,
                    role, tone, language, instructions, prompt_blocks,
                    knowledge_policy, tool_policy, action_policy, field_policy,
                    workflow_policy, safety_policy, test_policy, snapshot,
                    change_summary, published_at
                )
                VALUES (
                    :version_id, :tenant_id, :agent_id, :version_number,
                    'published', true,
                    'asesor', 'humano', 'es', :instructions, '[]'::jsonb,
                    CAST(:knowledge_policy AS jsonb), CAST(:tool_policy AS jsonb),
                    '{}'::jsonb, '{}'::jsonb,
                    '{}'::jsonb, CAST(:safety_policy AS jsonb), CAST(:test_policy AS jsonb),
                    CAST(:snapshot AS jsonb), :change_summary, now()
                )
                RETURNING tenant_id, agent_id, id AS version_id"""
            ),
            {
                "version_id": uuid4(),
                "tenant_id": agent["tenant_id"],
                "agent_id": agent["id"],
                "version_number": next_version_number,
                "instructions": (
                    "Francisco Esparza, asesor de creditos de Dinamo Motos NL. "
                    "ChatGPT interpreta; AtendIA valida datos duros, policy y envio no-send."
                ),
                "tool_policy": json.dumps(
                    {
                        "required_tools": [tool["tool_id"] for tool in contract["tools"]],
                        "source": "dinamo_runtime_contract.json",
                    }
                ),
                "knowledge_policy": json.dumps(
                    {
                        "knowledge_os": contract["knowledge_os"],
                        "source": "dinamo_runtime_contract.json",
                    }
                ),
                "safety_policy": json.dumps(
                    {"send_mode": "no_send", "internal_copy_forbidden": True}
                ),
                "test_policy": json.dumps(
                    {"execution_mode": "runtime_v2_agent_service", "no_send_only": True}
                ),
                "snapshot": json.dumps(
                    {
                        "source": "dinamo_runtime_contract_config",
                        "live_enabled": False,
                        "runtime_contract_path": _repo_path(CONTRACT_PATH),
                        "runtime_contract_checksum": contract_checksum,
                        "tenant_domain_contract": contract,
                    }
                ),
                "change_summary": (
                    "Seed no-send con contrato tenant real Dinamo; no live deployment."
                ),
            },
        )
    ).mappings().one()
    return UUID(str(row["tenant_id"])), UUID(str(row["agent_id"])), UUID(str(row["version_id"]))


def _config_paths_exist() -> bool:
    if not all(path.exists() for path in (CONTRACT_PATH, MANIFEST_PATH, SCENARIOS_PATH)):
        return False
    manifest = _load_json(MANIFEST_PATH)
    return all((REPO_ROOT / source["path"]).exists() for source in manifest["sources"])


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _file_sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _repo_path(path: Path) -> str:
    return str(path.relative_to(REPO_ROOT)).replace("\\", "/")


def _knowledge_os_content_type(domain_content_type: str) -> str:
    mapped = {
        "requirements": "document_rules",
        "flow_policy": "policy",
        "prompt": "policy",
    }
    allowed = {
        "faq",
        "policy",
        "pricing",
        "catalog",
        "services",
        "appointment_rules",
        "document_rules",
        "general",
    }
    normalized = domain_content_type.strip().casefold()
    return mapped.get(normalized) or (normalized if normalized in allowed else "general")


async def _ensure_product_agent_bindings(
    session,
    *,
    tenant_id: UUID,
    agent_id: UUID,
    version_id: UUID,
) -> dict[str, Any]:
    manifest = _load_json(MANIFEST_PATH)
    contract = _load_json(CONTRACT_PATH)
    source_ids: list[str] = []
    for source in manifest["sources"]:
        source_uuid = await _ensure_knowledge_source(session, tenant_id=tenant_id, source=source)
        source_ids.append(str(source_uuid))
        await _ensure_knowledge_binding(
            session,
            tenant_id=tenant_id,
            version_id=version_id,
            source_id=source_uuid,
            source=source,
        )
    for tool in contract["tools"]:
        await _ensure_tool_binding(
            session,
            tenant_id=tenant_id,
            version_id=version_id,
            tool=tool,
        )
    for field in contract["fields"]:
        await _ensure_field_permission(
            session,
            tenant_id=tenant_id,
            version_id=version_id,
            field=field,
        )
    return {
        "knowledge_source_count": len(source_ids),
        "knowledge_source_ids": source_ids,
        "tool_binding_count": len(contract["tools"]),
        "field_permission_count": len(contract["fields"]),
    }


async def _ensure_knowledge_source(session, *, tenant_id: UUID, source: dict[str, Any]) -> UUID:
    logical_id = str(source["source_id"])
    source_uuid = uuid5(NAMESPACE_URL, f"atendia:{tenant_id}:knowledge:{logical_id}")
    source_path = REPO_ROOT / source["path"]
    metadata = {
        "source_id": logical_id,
        "source_path": source["path"],
        "official_path": source.get("official_path"),
        "domain_content_type": source["content_type"],
        "checksum": _file_sha256(source_path),
        "content_checksum": _file_sha256(source_path),
        "health": "healthy",
        "source_version": "2026-06-07",
        "product_first": True,
    }
    existing = (
        await session.execute(
            text(
                """SELECT id
                FROM knowledge_sources
                WHERE tenant_id = :tenant_id
                  AND metadata_json ->> 'source_id' = :source_id
                LIMIT 1"""
            ),
            {"tenant_id": tenant_id, "source_id": logical_id},
        )
    ).scalar_one_or_none()
    if existing is None:
        await session.execute(
            text(
                """INSERT INTO knowledge_sources (
                    id, tenant_id, name, type, content_type, status, priority, metadata_json
                )
                VALUES (
                    :id, :tenant_id, :name, :type, :content_type, :status, :priority,
                    CAST(:metadata AS jsonb)
                )"""
            ),
            {
                "id": source_uuid,
                "tenant_id": tenant_id,
                "name": source["name"],
                "type": source["type"],
                "content_type": _knowledge_os_content_type(source["content_type"]),
                "status": source["status"],
                "priority": int(source.get("priority") or 0),
                "metadata": json.dumps(metadata),
            },
        )
        return source_uuid
    await session.execute(
        text(
            """UPDATE knowledge_sources
            SET name = :name,
                type = :type,
                content_type = :content_type,
                status = :status,
                priority = :priority,
                metadata_json = CAST(:metadata AS jsonb),
                updated_at = now()
            WHERE id = :id AND tenant_id = :tenant_id"""
        ),
        {
            "id": existing,
            "tenant_id": tenant_id,
            "name": source["name"],
            "type": source["type"],
            "content_type": _knowledge_os_content_type(source["content_type"]),
            "status": source["status"],
            "priority": int(source.get("priority") or 0),
            "metadata": json.dumps(metadata),
        },
    )
    return UUID(str(existing))


async def _ensure_knowledge_binding(
    session,
    *,
    tenant_id: UUID,
    version_id: UUID,
    source_id: UUID,
    source: dict[str, Any],
) -> None:
    existing = (
        await session.execute(
            text(
                """SELECT id
                FROM agent_knowledge_source_bindings
                WHERE tenant_id = :tenant_id
                  AND agent_version_id = :version_id
                  AND knowledge_source_id = :source_id
                LIMIT 1"""
            ),
            {"tenant_id": tenant_id, "version_id": version_id, "source_id": source_id},
        )
    ).scalar_one_or_none()
    metadata = {
        "source_health_at_binding": "healthy",
        "source_status_at_binding": source["status"],
        "product_first": True,
        "source_id": source["source_id"],
    }
    if existing is None:
        await session.execute(
            text(
                """INSERT INTO agent_knowledge_source_bindings (
                    id, tenant_id, agent_version_id, knowledge_source_id, binding_mode,
                    required, priority, metadata_json
                )
                VALUES (
                    :id, :tenant_id, :version_id, :source_id, :binding_mode,
                    :required, :priority, CAST(:metadata AS jsonb)
                )"""
            ),
            {
                "id": uuid4(),
                "tenant_id": tenant_id,
                "version_id": version_id,
                "source_id": source_id,
                "binding_mode": source.get("binding_mode") or "read",
                "required": bool(source.get("required", True)),
                "priority": int(source.get("priority") or 0),
                "metadata": json.dumps(metadata),
            },
        )


async def _ensure_tool_binding(
    session,
    *,
    tenant_id: UUID,
    version_id: UUID,
    tool: dict[str, Any],
) -> None:
    existing = (
        await session.execute(
            text(
                """SELECT id
                FROM agent_tool_bindings
                WHERE tenant_id = :tenant_id
                  AND agent_version_id = :version_id
                  AND tool_name = :tool_name
                LIMIT 1"""
            ),
            {"tenant_id": tenant_id, "version_id": version_id, "tool_name": tool["tool_id"]},
        )
    ).scalar_one_or_none()
    if existing is None:
        await session.execute(
            text(
                """INSERT INTO agent_tool_bindings (
                    id, tenant_id, agent_version_id, tool_name, enabled, required,
                    input_schema, output_schema, metadata_json
                )
                VALUES (
                    :id, :tenant_id, :version_id, :tool_name, true, true,
                    '{}'::jsonb, '{}'::jsonb, CAST(:metadata AS jsonb)
                )"""
            ),
            {
                "id": uuid4(),
                "tenant_id": tenant_id,
                "version_id": version_id,
                "tool_name": tool["tool_id"],
                "metadata": json.dumps(
                    {
                        "product_first": True,
                        "topic": tool.get("topic"),
                        "side_effect_type": "none",
                        "facts_only": True,
                    }
                ),
            },
        )


async def _ensure_field_permission(
    session,
    *,
    tenant_id: UUID,
    version_id: UUID,
    field: dict[str, Any],
) -> None:
    existing = (
        await session.execute(
            text(
                """SELECT id
                FROM agent_field_permissions
                WHERE tenant_id = :tenant_id
                  AND agent_version_id = :version_id
                  AND field_key = :field_key
                LIMIT 1"""
            ),
            {"tenant_id": tenant_id, "version_id": version_id, "field_key": field["key"]},
        )
    ).scalar_one_or_none()
    if existing is None:
        await session.execute(
            text(
                """INSERT INTO agent_field_permissions (
                    id, tenant_id, agent_version_id, field_key, can_read, can_write,
                    evidence_required, write_policy, metadata_json
                )
                VALUES (
                    :id, :tenant_id, :version_id, :field_key, true, true,
                    :evidence_required, CAST(:write_policy AS jsonb), CAST(:metadata AS jsonb)
                )"""
            ),
            {
                "id": uuid4(),
                "tenant_id": tenant_id,
                "version_id": version_id,
                "field_key": field["key"],
                "evidence_required": bool(field.get("evidence_required", True)),
                "write_policy": json.dumps(
                    {
                        "write_policy": field.get("write_policy"),
                        "allowed_sources": field.get("allowed_sources") or [],
                    }
                ),
                "metadata": json.dumps(
                    {"product_first": True, "domain_role": field.get("domain_role")}
                ),
            },
        )

async def main() -> None:
    settings = get_settings()
    key = settings.openai_api_key or os.getenv("OPENAI_API_KEY") or ""
    result: dict[str, Any] = {
        "openai_api_key_present": bool(key),
        "openai_api_key_length": len(key),
        "send_enabled": bool(settings.agent_runtime_v2_send_enabled),
        "actions_enabled": bool(settings.agent_runtime_v2_actions_enabled),
        "workflow_events_enabled": bool(settings.agent_runtime_v2_workflow_events_enabled),
        "model_provider": settings.agent_runtime_v2_model_provider,
        "model": settings.agent_runtime_v2_model,
    }
    if not key:
        result["decision"] = "REAL_AGENT_TEST_LAB_BLOCKED_BY_OPENAI_API"
        result["blocker"] = "OPENAI_API_KEY_MISSING"
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    engine = create_async_engine(settings.database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        async with session.begin():
            selected = await _select_or_seed_version(session)
            if selected is None:
                result["decision"] = "REAL_AGENT_TEST_LAB_FAILED_BY_DB_AUDIT"
                result["blocker"] = "NO_PRODUCT_AGENT_FOUND"
                print(json.dumps(result, ensure_ascii=False, indent=2))
                return

            tenant_id, _agent_id, version_id = selected
            result["tenant_id"] = str(tenant_id)
            result["agent_version_id"] = str(version_id)
            result["binding_result"] = await _ensure_product_agent_bindings(
                session,
                tenant_id=tenant_id,
                agent_id=_agent_id,
                version_id=version_id,
            )
            result["db_audit_before"] = await _audit(session, tenant_id)

            scenario_config = _load_json(SCENARIOS_PATH)
            suite = await service.create_agent_test_suite(
                session,
                tenant_id=tenant_id,
                version_id=version_id,
                name=scenario_config["suite_name"],
                mode=scenario_config["mode"],
                metadata={
                    "created_by": "run_real_agent_test_lab_no_send_2026_06_07",
                    "scenario_source": _repo_path(SCENARIOS_PATH),
                    "runtime_contract_source": _repo_path(CONTRACT_PATH),
                },
            )
            for name, turns, expected in (
                _scenario_payload(
                    "Negocio ambiguo",
                    SCENARIO_A,
                    expected_turns=[
                        {},
                        {
                            "forbidden_state_writes": [
                                "plan_selection",
                                "down_payment_percent",
                            ],
                            "final_message_not_contains": [
                                "ya validé tu tipo de ingreso",
                                "Cuánto tiempo llevas trabajando",
                                "Dime qué dato quieres revisar.",
                            ],
                        },
                        {
                            "final_message_not_contains": [
                                "Dime qué dato quieres revisar.",
                            ],
                        },
                        {
                            "expected_tools": ["credit_plan.resolve"],
                            "expected_state_writes": [
                                "plan_selection",
                                "down_payment_percent",
                            ],
                            "final_message_not_contains": [
                                "Dime qué dato quieres revisar.",
                            ],
                        },
                        {
                            "final_message_not_contains": [
                                "Dime qué dato quieres revisar.",
                            ],
                        },
                        {
                            "expected_tools": ["catalog.search"],
                            "expected_state_writes": ["product_selection"],
                            "final_message_not_contains": [
                                "Dime qué dato quieres revisar.",
                            ],
                        },
                    ],
                ),
                _scenario_payload(
                    "Skeleton buro tarjeta",
                    SCENARIO_B,
                    expected_turns=[
                        {
                            "expected_tools": ["catalog.search", "faq.lookup"],
                            "expected_state_writes": ["product_selection"],
                        },
                        {
                            "expected_tools": ["credit_plan.resolve"],
                            "expected_state_writes": [
                                "plan_selection",
                                "down_payment_percent",
                            ],
                        },
                        {
                            "expected_tools": ["quote.resolve"],
                            "expected_state_writes": [
                                "employment_seniority",
                                "quote_snapshot_id",
                            ],
                            "final_message_not_contains": [
                                "Dime qué dato quieres revisar.",
                            ],
                        },
                        {
                            "expected_tools": ["requirements.lookup"],
                            "expected_state_writes": ["requirements_checklist"],
                        },
                    ],
                ),
            ):
                await service.create_agent_test_scenario(
                    session,
                    tenant_id=tenant_id,
                    suite_id=suite.id,
                    name=name,
                    turns=turns,
                    expected=expected,
                    metadata={"created_by": "run_real_agent_test_lab_no_send_2026_06_07"},
                )

            run = await test_lab.run_test_suite(
                session,
                tenant_id=tenant_id,
                suite_id=suite.id,
                mode=scenario_config["send_mode"],
                execution_mode=scenario_config["execution_mode"],
                review_required=True,
                created_by_user_id=None,
            )
            result["suite_id"] = str(suite.id)
            result["test_run_id"] = str(run.id)
            result["run_status"] = run.status
            result["run_decision"] = run.decision
            result["scenario_results"] = run.scenario_results
            result["turn_results"] = run.turn_results
            result["trace_ids"] = run.trace_ids
            result["outbox_audit_result"] = run.outbox_audit_result
            result["side_effect_audit_result"] = run.side_effect_audit_result
            result["coverage_summary"] = run.coverage_summary
            result["db_audit_after"] = await _audit(session, tenant_id)

    await engine.dispose()
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(main())
