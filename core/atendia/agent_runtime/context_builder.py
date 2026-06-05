from __future__ import annotations

from typing import Any, Protocol

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from atendia.agent_runtime.agent_config import agent_studio_config_from_values
from atendia.agent_runtime.schemas import (
    ActiveAgentContext,
    ContactFieldDefinitionContext,
    ConversationMemoryContext,
    CustomerContext,
    KnowledgeCitation,
    LifecycleContext,
    MessageContext,
    TenantRuntimeConfigContext,
    TurnContext,
    TurnInput,
)
from atendia.agent_runtime.tenant_domain_contract import (
    apply_tenant_domain_contract,
    load_tenant_domain_contract,
    tenant_domain_trace_metadata,
)


class KnowledgeContextProvider(Protocol):
    async def retrieve(
        self,
        *,
        tenant_id: Any,
        query: str,
        agent_id: Any | None = None,
        top_k: int | None = None,
        source_ids: list[str] | None = None,
    ) -> Any: ...


class ContextBuilder:
    """Build the canonical context consumed by AgentRuntime.

    Missing integrations are represented as empty structured fields with TODO
    metadata. That keeps the runtime contract stable while DB adapters mature.
    """

    def __init__(
        self,
        session: AsyncSession | None = None,
        *,
        history_limit: int = 12,
        knowledge_provider: KnowledgeContextProvider | None = None,
    ) -> None:
        self._session = session
        self._history_limit = history_limit
        self._knowledge_provider = knowledge_provider

    async def build(self, turn_input: TurnInput) -> TurnContext:
        if self._session is None:
            evidence = await self._retrieve_knowledge(
                tenant_id=turn_input.tenant_id,
                query=turn_input.inbound_text,
                agent_id=turn_input.metadata.get("agent_id"),
                source_ids=turn_input.metadata.get("enabled_knowledge_source_ids"),
            )
            tenant_config = _tenant_config_from_metadata(
                turn_input.metadata,
                tenant_id=turn_input.tenant_id,
                agent_id=_maybe_str(turn_input.metadata.get("agent_id")),
            )
            return TurnContext(
                tenant_id=turn_input.tenant_id,
                conversation_id=turn_input.conversation_id,
                inbound_text=turn_input.inbound_text,
                messages=[MessageContext(role="customer", text=turn_input.inbound_text)],
                memory=_memory_from_metadata(turn_input.metadata),
                tenant_config=tenant_config,
                knowledge_citations=_citations_from_evidence(evidence),
                metadata={
                    **turn_input.metadata,
                    "context_builder": "stub_no_session",
                    "knowledge": _knowledge_metadata(evidence),
                    **tenant_domain_trace_metadata(
                        TurnContext(
                            tenant_id=turn_input.tenant_id,
                            conversation_id=turn_input.conversation_id,
                            inbound_text=turn_input.inbound_text,
                            tenant_config=tenant_config,
                        )
                    ),
                    "todo": (
                        "Attach AsyncSession to hydrate customer, lifecycle, agent "
                        "and KB context."
                    ),
                },
            )

        conversation = await self._load_conversation(turn_input.conversation_id)
        conversation_state = await self._load_conversation_state(turn_input.conversation_id)
        customer = await self._load_customer(conversation.get("customer_id"))
        messages = await self._load_messages(turn_input.conversation_id)
        active_agent = await self._load_agent(
            conversation.get("assigned_agent_id") or turn_input.metadata.get("agent_id")
        )
        contact_fields = await self._load_contact_fields(
            turn_input.tenant_id,
            visible_keys=active_agent.visible_contact_field_keys if active_agent else None,
        )
        runtime_v2_config = await self._load_agent_runtime_v2_config(turn_input.tenant_id)
        default_voice = await self._load_tenant_default_voice(turn_input.tenant_id)
        tenant_config = _tenant_config_from_runtime_config(
            runtime_v2_config,
            tenant_id=turn_input.tenant_id,
            agent_id=active_agent.id if active_agent else None,
            default_voice=default_voice,
        )
        evidence = await self._retrieve_knowledge(
            tenant_id=turn_input.tenant_id,
            query=turn_input.inbound_text,
            agent_id=active_agent.id if active_agent else None,
            source_ids=active_agent.enabled_knowledge_source_ids if active_agent else None,
        )

        if not any(message.text == turn_input.inbound_text for message in messages):
            messages.append(MessageContext(role="customer", text=turn_input.inbound_text))

        return TurnContext(
            tenant_id=turn_input.tenant_id,
            conversation_id=turn_input.conversation_id,
            inbound_text=turn_input.inbound_text,
            customer=customer,
            messages=messages,
            contact_fields=contact_fields,
            lifecycle=LifecycleContext(
                stage=_maybe_str(conversation.get("current_stage")),
                status=_maybe_str(conversation.get("status")),
                metadata={"source": "conversations"},
            ),
            memory=_memory_from_state_and_metadata(
                conversation_state,
                turn_input.metadata,
            ),
            tenant_config=tenant_config,
            active_agent=active_agent,
            knowledge_citations=_citations_from_evidence(evidence),
            metadata={
                **turn_input.metadata,
                "context_builder": "db",
                "knowledge": _knowledge_metadata(evidence),
                "tenant_config": tenant_config.model_dump(),
                **tenant_domain_trace_metadata(
                    TurnContext(
                        tenant_id=turn_input.tenant_id,
                        conversation_id=turn_input.conversation_id,
                        inbound_text=turn_input.inbound_text,
                        tenant_config=tenant_config,
                    )
                ),
                "structured_reliability": dict(
                    runtime_v2_config.get("structured_reliability") or {}
                ),
            },
        )

    async def _retrieve_knowledge(
        self,
        *,
        tenant_id: Any,
        query: str,
        agent_id: Any | None = None,
        source_ids: list[str] | None = None,
    ) -> Any | None:
        if self._knowledge_provider is None:
            return None
        try:
            return await self._knowledge_provider.retrieve(
                tenant_id=tenant_id,
                query=query,
                agent_id=agent_id,
                top_k=5,
                source_ids=source_ids,
            )
        except TypeError:
            return await self._knowledge_provider.retrieve(
                tenant_id=tenant_id,
                query=query,
                agent_id=agent_id,
                top_k=5,
            )
        except Exception:
            return None

    async def _load_conversation(self, conversation_id: str) -> dict[str, Any]:
        row = (
            await self._session.execute(
                text(
                    """SELECT customer_id, current_stage, status, assigned_agent_id, tags
                    FROM conversations
                    WHERE id = :conversation_id"""
                ),
                {"conversation_id": conversation_id},
            )
        ).mappings().first()
        return dict(row or {})

    async def _load_customer(self, customer_id: Any) -> CustomerContext:
        if customer_id is None:
            return CustomerContext()
        row = (
            await self._session.execute(
                text(
                    """SELECT id, name, phone_e164, email, attrs, tags
                    FROM customers
                    WHERE id = :customer_id"""
                ),
                {"customer_id": customer_id},
            )
        ).mappings().first()
        if row is None:
            return CustomerContext(id=_maybe_str(customer_id))
        return CustomerContext(
            id=_maybe_str(row["id"]),
            name=row["name"],
            phone_e164=row["phone_e164"],
            email=row["email"],
            attrs=dict(row["attrs"] or {}),
            tags=[str(tag) for tag in (row["tags"] or [])],
        )

    async def _load_conversation_state(self, conversation_id: str) -> dict[str, Any]:
        row = (
            await self._session.execute(
                text(
                    """SELECT extracted_data, pending_confirmation, last_intent
                    FROM conversation_state
                    WHERE conversation_id = :conversation_id"""
                ),
                {"conversation_id": conversation_id},
            )
        ).mappings().first()
        return dict(row or {})

    async def _load_messages(self, conversation_id: str) -> list[MessageContext]:
        rows = (
            await self._session.execute(
                text(
                    """SELECT direction, text, sent_at, metadata_json
                    FROM messages
                    WHERE conversation_id = :conversation_id
                    ORDER BY sent_at DESC
                    LIMIT :limit"""
                ),
                {"conversation_id": conversation_id, "limit": self._history_limit},
            )
        ).mappings().all()
        messages: list[MessageContext] = []
        for row in reversed(rows):
            messages.append(
                MessageContext(
                    role=_direction_to_role(row["direction"]),
                    text=row["text"],
                    sent_at=row["sent_at"].isoformat() if row["sent_at"] else None,
                    metadata=dict(row["metadata_json"] or {}),
                )
            )
        return messages

    async def _load_contact_fields(
        self,
        tenant_id: str,
        *,
        visible_keys: list[str] | None = None,
    ) -> list[ContactFieldDefinitionContext]:
        rows = (
            await self._session.execute(
                text(
                    """SELECT key, label, field_type, field_options
                    FROM customer_field_definitions
                    WHERE tenant_id = :tenant_id
                    ORDER BY ordering ASC, label ASC"""
                ),
                {"tenant_id": tenant_id},
            )
        ).mappings().all()
        allowed = set(visible_keys or [])
        return [
            ContactFieldDefinitionContext(
                key=row["key"],
                label=row["label"],
                field_type=row["field_type"],
                options=dict(row["field_options"]) if row["field_options"] else None,
            )
            for row in rows
            if not allowed or row["key"] in allowed
        ]

    async def _load_agent(self, agent_id: Any) -> ActiveAgentContext | None:
        if agent_id is None:
            return None
        row = (
            await self._session.execute(
                text(
                    """SELECT id, name, role, behavior_mode, status, system_prompt,
                              tone, voice, language, knowledge_config, auto_actions,
                              extraction_config, flow_mode_rules, ops_config
                    FROM agents
                    WHERE id = :agent_id"""
                ),
                {"agent_id": agent_id},
            )
        ).mappings().first()
        if row is None:
            return ActiveAgentContext(id=_maybe_str(agent_id))
        studio_config = agent_studio_config_from_values(
            role=row["role"],
            system_prompt=row["system_prompt"],
            tone=row["tone"],
            language=row["language"],
            knowledge_config=dict(row["knowledge_config"] or {}),
            auto_actions=dict(row["auto_actions"] or {}),
            extraction_config=dict(row["extraction_config"] or {}),
            flow_mode_rules=dict(row["flow_mode_rules"] or {}),
            ops_config=dict(row["ops_config"] or {}),
        )
        return ActiveAgentContext(
            id=_maybe_str(row["id"]),
            name=row["name"],
            role=row["role"],
            behavior_mode=row["behavior_mode"],
            instructions=studio_config["instructions"],
            tone=studio_config["tone"],
            voice=dict(row["voice"] or {}),
            language_policy=studio_config["language_policy"],
            enabled_knowledge_source_ids=studio_config["enabled_knowledge_source_ids"],
            enabled_action_ids=studio_config["enabled_action_ids"],
            visible_contact_field_keys=studio_config["visible_contact_field_keys"],
            allowed_lifecycle_stage_ids=studio_config["allowed_lifecycle_stage_ids"],
            escalation_policy=studio_config["escalation_policy"],
            metadata={
                "status": row["status"],
                "template": studio_config["template"],
                "enabled_action_ids": studio_config["enabled_action_ids"],
                "enabled_knowledge_source_ids": studio_config["enabled_knowledge_source_ids"],
                "agent_studio_v2": studio_config["metadata"],
            },
        )

    async def _load_agent_runtime_v2_config(self, tenant_id: str) -> dict[str, Any]:
        row = (
            await self._session.execute(
                text("SELECT config FROM tenants WHERE id = :tenant_id"),
                {"tenant_id": tenant_id},
            )
        ).scalar_one_or_none()
        if not isinstance(row, dict):
            return {}
        raw = row.get("agent_runtime_v2") or row.get("agent_runtime_v2_rollout") or {}
        return dict(raw) if isinstance(raw, dict) else {}

    async def _load_tenant_default_voice(self, tenant_id: str) -> dict[str, Any]:
        row = (
            await self._session.execute(
                text("SELECT voice FROM tenant_branding WHERE tenant_id = :tenant_id"),
                {"tenant_id": tenant_id},
            )
        ).scalar_one_or_none()
        return dict(row) if isinstance(row, dict) else {}


def _direction_to_role(direction: str) -> str:
    if direction == "inbound":
        return "customer"
    if direction == "outbound":
        return "agent"
    return "system"


def _maybe_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _citations_from_evidence(evidence: Any | None) -> list[KnowledgeCitation]:
    if evidence is None:
        return []
    citations = getattr(evidence, "citations", []) or []
    out: list[KnowledgeCitation] = []
    for citation in citations:
        source_id = getattr(citation, "source_id", None)
        if source_id is None:
            continue
        out.append(
            KnowledgeCitation(
                source_id=str(source_id),
                title=getattr(citation, "title", None),
                snippet=getattr(citation, "snippet", None),
                score=getattr(citation, "score", None),
                metadata={
                    "item_id": str(getattr(citation, "item_id", "")),
                    "chunk_id": str(getattr(citation, "chunk_id", "")),
                    "source_type": getattr(citation, "source_type", None),
                    "content_type": getattr(citation, "content_type", None),
                    **(getattr(citation, "metadata", {}) or {}),
                },
            )
        )
    return out


def _knowledge_metadata(evidence: Any | None) -> dict[str, Any]:
    if evidence is None:
        return {"enabled": False, "answerable": False, "citation_count": 0}
    retrieval_log_id = evidence.retrieval_log_id
    return {
        "enabled": True,
        "answerable": bool(getattr(evidence, "answerable", False)),
        "confidence": float(getattr(evidence, "confidence", 0.0) or 0.0),
        "citation_count": len(getattr(evidence, "citations", []) or []),
        "retrieval_log_id": str(retrieval_log_id) if retrieval_log_id else None,
    }


def _memory_from_metadata(metadata: dict[str, Any]) -> ConversationMemoryContext:
    return ConversationMemoryContext(
        summary=_maybe_str(metadata.get("conversation_summary")),
        salient_facts=_dict(metadata.get("salient_facts")),
        last_quote_snapshot=_optional_dict(
            metadata.get("last_quote_snapshot")
            or metadata.get("quote_snapshot")
            or metadata.get("last_quote")
        ),
        last_pending_question=_maybe_str(metadata.get("last_pending_question")),
        documents=_dict(metadata.get("documents") or metadata.get("documents_state")),
        metadata=_dict(metadata.get("memory_metadata")),
    )


def _memory_from_state_and_metadata(
    state: dict[str, Any],
    metadata: dict[str, Any],
) -> ConversationMemoryContext:
    extracted_data = _dict(state.get("extracted_data"))
    memory = _memory_from_metadata(metadata)
    salient_facts = {
        **_salient_facts_from_extracted_data(extracted_data),
        **memory.salient_facts,
    }
    last_quote = (
        memory.last_quote_snapshot
        or _field_value(extracted_data, "Ultima_Cotizacion")
        or _field_value(extracted_data, "last_quote")
    )
    documents = {
        **_documents_from_extracted_data(extracted_data),
        **memory.documents,
    }
    return memory.model_copy(
        update={
            "salient_facts": salient_facts,
            "last_quote_snapshot": _optional_dict(last_quote),
            "last_pending_question": memory.last_pending_question
            or _maybe_str(state.get("pending_confirmation")),
            "documents": documents,
            "metadata": {
                **memory.metadata,
                "source": "conversation_state",
                "last_intent_signal": _maybe_str(state.get("last_intent")),
            },
        }
    )


def _tenant_config_from_metadata(
    metadata: dict[str, Any],
    *,
    tenant_id: str,
    agent_id: str | None = None,
) -> TenantRuntimeConfigContext:
    raw = _dict(metadata.get("tenant_config"))
    config = TenantRuntimeConfigContext(
        ruleset=_dict(raw.get("ruleset") or metadata.get("tenant_ruleset")),
        tools=_dict(raw.get("tools") or metadata.get("tenant_tools")),
        default_voice=_dict(
            raw.get("default_voice")
            or raw.get("voice")
            or metadata.get("tenant_default_voice")
            or metadata.get("tenant_voice")
        ),
        knowledge_sources=[
            str(item)
            for item in (raw.get("knowledge_sources") or metadata.get("knowledge_sources") or [])
        ],
        metadata=_dict(raw.get("metadata")),
    )
    contract_raw = (
        raw.get("tenant_domain_contract")
        or raw.get("domain_contract")
        or metadata.get("tenant_domain_contract")
        or metadata.get("domain_contract")
    )
    result = load_tenant_domain_contract(
        contract_raw,
        tenant_id=str(tenant_id),
        agent_id=agent_id,
    )
    return apply_tenant_domain_contract(config, result)


def _tenant_config_from_runtime_config(
    runtime_config: dict[str, Any],
    *,
    tenant_id: str,
    agent_id: str | None = None,
    default_voice: dict[str, Any] | None = None,
) -> TenantRuntimeConfigContext:
    tenant_config = _dict(runtime_config.get("tenant_config"))
    config = TenantRuntimeConfigContext(
        ruleset=_dict(
            tenant_config.get("ruleset")
            or runtime_config.get("ruleset")
            or runtime_config.get("operational_state")
        ),
        tools=_dict(tenant_config.get("tools") or runtime_config.get("tools")),
        default_voice=_dict(
            default_voice
            or tenant_config.get("default_voice")
            or tenant_config.get("voice")
            or runtime_config.get("tenant_default_voice")
        ),
        knowledge_sources=[
            str(item)
            for item in (
                tenant_config.get("knowledge_sources")
                or runtime_config.get("knowledge_sources")
                or []
            )
        ],
        metadata={
            **_dict(tenant_config.get("metadata")),
            "source": "agent_runtime_v2_config",
        },
    )
    contract_raw = (
        tenant_config.get("tenant_domain_contract")
        or tenant_config.get("domain_contract")
        or runtime_config.get("tenant_domain_contract")
        or runtime_config.get("domain_contract")
    )
    result = load_tenant_domain_contract(
        contract_raw,
        tenant_id=str(tenant_id),
        agent_id=agent_id,
    )
    return apply_tenant_domain_contract(config, result)


def _salient_facts_from_extracted_data(extracted_data: dict[str, Any]) -> dict[str, Any]:
    facts: dict[str, Any] = {}
    for key, _raw in extracted_data.items():
        if str(key).startswith("_"):
            continue
        value = _field_value(extracted_data, str(key))
        if value not in (None, ""):
            facts[str(key)] = value
    return facts


def _documents_from_extracted_data(extracted_data: dict[str, Any]) -> dict[str, Any]:
    documents: dict[str, Any] = {}
    for key in ("Docs_Checklist", "documents", "documents_state"):
        value = _field_value(extracted_data, key)
        if value not in (None, ""):
            documents[key] = value
    return documents


def _field_value(data: dict[str, Any], key: str) -> Any:
    raw = data.get(key)
    if isinstance(raw, dict) and "value" in raw:
        return raw.get("value")
    return raw


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _optional_dict(value: Any) -> dict[str, Any] | None:
    return dict(value) if isinstance(value, dict) else None
