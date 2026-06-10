from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from atendia.agent_runtime.agent_service import AgentService, AgentServiceResult

RUNTIME_CONTRACT_MISSING = "runtime_contract_missing"


AgentServiceFactory = Callable[[AsyncSession], Any]


class ProductAgentRuntimeAdapter:
    """Run Product-First Test Lab turns through Runtime V2 AgentService.

    The adapter owns Product Agent -> Runtime V2 wiring for Test Lab. Runtime V2
    remains generic: it receives tenant, conversation, agent metadata and
    no-send mode, then executes ContextBuilder, SemanticAdvisorBrain, tools,
    StateWriter, policy and SendAdapter normally.
    """

    def __init__(
        self,
        *,
        session: AsyncSession,
        agent_version_id: UUID,
        agent_service_factory: AgentServiceFactory | None = None,
    ) -> None:
        self._session = session
        self._agent_version_id = agent_version_id
        self._agent_service_factory = agent_service_factory

    async def handle_turn(
        self,
        *,
        tenant_id: str,
        conversation_id: str,
        inbound_text: str,
        turn_number: int,
        mode: str,
        metadata: dict[str, Any] | None = None,
        to_phone_e164: str | None = None,
    ) -> AgentServiceResult:
        metadata = dict(metadata or {})
        contract = await self._load_runtime_contract(tenant_id=tenant_id)
        if contract.get("blocked_reason"):
            return _blocked_result(
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                inbound_text=inbound_text,
                mode=mode,
                reason=str(contract["blocked_reason"]),
            )

        agent_id = str(contract["agent_id"])
        visible_field_keys = await self._load_visible_field_keys(tenant_id=tenant_id)
        metadata = {
            **metadata,
            "agent_id": agent_id,
            "agent_version_id": str(self._agent_version_id),
            "product_agent_runtime_adapter": True,
            "product_agent_visible_contact_field_keys": visible_field_keys,
            "runtime_contract_source": contract["source"],
            "send_mode": "no_send",
        }
        if isinstance(contract.get("tenant_domain_contract"), dict):
            metadata["tenant_domain_contract"] = contract["tenant_domain_contract"]
        await self._assign_sandbox_agent(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            agent_id=agent_id,
        )
        await self._insert_inbound_message(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            inbound_text=inbound_text,
            metadata=metadata,
        )
        service = (
            self._agent_service_factory(self._session)
            if self._agent_service_factory is not None
            else AgentService(session=self._session)
        )
        return await service.handle_turn(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            inbound_text=inbound_text,
            turn_number=turn_number,
            mode=mode,
            metadata=metadata,
            to_phone_e164=to_phone_e164,
        )

    async def _load_runtime_contract(self, *, tenant_id: str) -> dict[str, Any]:
        version = (
            await self._session.execute(
                text(
                    """SELECT agent_id, snapshot, tool_policy, knowledge_policy,
                              field_policy, safety_policy
                    FROM agent_versions
                    WHERE tenant_id = :tenant_id AND id = :version_id"""
                ),
                {"tenant_id": tenant_id, "version_id": self._agent_version_id},
            )
        ).mappings().first()
        if version is None:
            return {"blocked_reason": RUNTIME_CONTRACT_MISSING}

        tenant_config = (
            await self._session.execute(
                text("SELECT config FROM tenants WHERE id = :tenant_id"),
                {"tenant_id": tenant_id},
            )
        ).scalar_one_or_none()
        runtime_config = _runtime_config(tenant_config)
        if _has_runtime_contract(runtime_config):
            return {
                "agent_id": version["agent_id"],
                "source": "tenant_runtime_v2_config",
            }
        product_contract = _product_version_runtime_contract(version)
        if product_contract:
            return {
                "agent_id": version["agent_id"],
                "source": "product_agent_version",
                "tenant_domain_contract": product_contract,
            }
        return {
            "agent_id": version["agent_id"],
            "blocked_reason": RUNTIME_CONTRACT_MISSING,
        }

    async def _load_visible_field_keys(self, *, tenant_id: str) -> list[str]:
        rows = (
            await self._session.execute(
                text(
                    """SELECT field_key
                    FROM agent_field_permissions
                    WHERE tenant_id = :tenant_id
                      AND agent_version_id = :version_id
                      AND can_read = true
                    ORDER BY field_key"""
                ),
                {"tenant_id": tenant_id, "version_id": self._agent_version_id},
            )
        ).scalars().all()
        return [str(item) for item in rows if str(item).strip()]

    async def _assign_sandbox_agent(
        self,
        *,
        tenant_id: str,
        conversation_id: str,
        agent_id: str,
    ) -> None:
        await self._session.execute(
            text(
                """UPDATE conversations
                SET assigned_agent_id = :agent_id
                WHERE id = :conversation_id
                  AND tenant_id = :tenant_id
                  AND channel = 'test_lab'"""
            ),
            {
                "tenant_id": tenant_id,
                "conversation_id": conversation_id,
                "agent_id": agent_id,
            },
        )

    async def _insert_inbound_message(
        self,
        *,
        tenant_id: str,
        conversation_id: str,
        inbound_text: str,
        metadata: dict[str, Any],
    ) -> None:
        await self._session.execute(
            text(
                """INSERT INTO messages (
                    tenant_id, conversation_id, direction, text, sent_at, metadata_json
                )
                VALUES (
                    :tenant_id, :conversation_id, 'inbound', :text_value, :sent_at,
                    CAST(:metadata AS jsonb)
                )"""
            ),
            {
                "tenant_id": tenant_id,
                "conversation_id": conversation_id,
                "text_value": inbound_text,
                "sent_at": datetime.now(UTC),
                "metadata": json.dumps(metadata, ensure_ascii=False),
            },
        )


def _runtime_config(tenant_config: Any) -> dict[str, Any]:
    if not isinstance(tenant_config, dict):
        return {}
    raw = tenant_config.get("agent_runtime_v2") or tenant_config.get("agent_runtime_v2_rollout")
    return dict(raw) if isinstance(raw, dict) else {}


def _has_runtime_contract(runtime_config: dict[str, Any]) -> bool:
    tenant_config = runtime_config.get("tenant_config")
    if not isinstance(tenant_config, dict):
        tenant_config = {}
    return any(
        isinstance(value, dict) and bool(value)
        for value in (
            runtime_config.get("tenant_domain_contract"),
            runtime_config.get("domain_contract"),
            tenant_config.get("tenant_domain_contract"),
            tenant_config.get("domain_contract"),
        )
    )


def _product_version_runtime_contract(version: Any) -> dict[str, Any]:
    for key in ("snapshot", "tool_policy", "knowledge_policy", "field_policy", "safety_policy"):
        value = version.get(key) if hasattr(version, "get") else None
        contract = _contract_payload(value)
        if contract:
            return contract
    return {}


def _contract_payload(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    for key in ("tenant_domain_contract", "domain_contract"):
        candidate = value.get(key)
        if isinstance(candidate, dict) and candidate:
            return dict(candidate)
    runtime_contract = value.get("runtime_contract")
    if isinstance(runtime_contract, dict):
        nested = _contract_payload(runtime_contract)
        if nested:
            return nested
        if runtime_contract:
            return dict(runtime_contract)
    return {}


def _blocked_result(
    *,
    tenant_id: str,
    conversation_id: str,
    inbound_text: str,
    mode: str,
    reason: str,
) -> AgentServiceResult:
    from atendia.agent_runtime.schemas import TurnContext
    from atendia.agent_runtime.send_adapter import SendAdapterResult
    from atendia.agent_runtime.send_policy import PreparedSendDecision

    return AgentServiceResult(
        context=TurnContext(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            inbound_text=inbound_text,
        ),
        output=None,
        state_persistence={},
        send=SendAdapterResult(
            mode=mode,
            send_decision=PreparedSendDecision(
                status="blocked",
                allowed=False,
                reason="test_lab_runtime_contract_missing",
            ),
            delivery_status={"send_status": "no_send", "send_decision": "no_send"},
        ),
        errors=[
            {
                "where": "product_agent_runtime_adapter",
                "code": reason,
                "message": "Runtime V2 tenant contract is required for Test Lab readiness.",
            }
        ],
    )


__all__ = ["RUNTIME_CONTRACT_MISSING", "ProductAgentRuntimeAdapter"]
