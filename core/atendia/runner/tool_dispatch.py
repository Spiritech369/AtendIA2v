from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from atendia.tools.base import ToolNoDataResult
from atendia.tools.deterministic import list_catalog
from atendia.tools.embeddings import generate_embedding
from atendia.tools.lookup_faq import lookup_faq
from atendia.tools.quote import quote
from atendia.tools.search_catalog import search_catalog


def _jsonable(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, (datetime, Decimal, UUID)):
        return str(obj)
    return obj


def _tool_call_log(
    *,
    tool_name: str,
    input_payload: dict[str, Any],
    output_payload: Any,
    started_at: float,
    error: str | None = None,
) -> dict[str, Any]:
    return {
        "tool_name": tool_name,
        "input_payload": _jsonable(input_payload),
        "output_payload": _jsonable(output_payload),
        "latency_ms": int((time.perf_counter() - started_at) * 1000),
        "error": error,
    }


@dataclass
class ToolDispatchResult:
    action_payload: dict[str, Any] = field(default_factory=dict)
    tool_cost_usd: Decimal = Decimal("0")
    executed_tools: list[dict[str, Any]] = field(default_factory=list)
    tool_call_logs: list[dict[str, Any]] = field(default_factory=list)
    decision_payload: dict[str, Any] | None = None

    def facts_only(self) -> "ToolDispatchResult":
        self.action_payload = facts_only_tool_payload(self.action_payload)
        return self


_CUSTOMER_VISIBLE_TOOL_KEYS: frozenset[str] = frozenset(
    {
        "customer_visible_text",
        "draft_text",
        "final_message",
        "message",
        "messages",
        "natural_response",
        "prompt_override",
        "response_text",
    }
)


def facts_only_tool_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Strip final-copy fields from tool payloads while preserving facts.

    FAQ answers, catalog rows, quote numbers and requirement labels are facts.
    Free-form message/draft/prompt fields are not allowed to become tool output;
    final visible wording belongs to AgentFinalResponse.
    """

    if not isinstance(payload, dict):
        return payload
    cleaned = {
        key: value
        for key, value in payload.items()
        if str(key) not in _CUSTOMER_VISIBLE_TOOL_KEYS
    }
    contract = dict(cleaned.get("_tool_contract") or {})
    contract["facts_only"] = True
    cleaned["_tool_contract"] = contract
    return cleaned


class ToolDispatch:
    """Execute commercial tools while preserving the runner payload contract."""

    def __init__(self, *, session: AsyncSession, settings: Any) -> None:
        self._session = session
        self._settings = settings

    async def quote(
        self,
        *,
        tenant_id: UUID,
        candidate_queries: list[str],
        plan_code: str | None,
        collection_ids: list[UUID],
    ) -> ToolDispatchResult:
        result = ToolDispatchResult()
        last_hint: str | None = None
        for query_text in candidate_queries:
            tool_started = time.perf_counter()
            search_input = {
                "query": str(query_text),
                "embedding": None,
                "limit": 1,
                "collection_ids": [str(item) for item in collection_ids or []],
            }
            catalog_hits = await search_catalog(
                session=self._session,
                tenant_id=tenant_id,
                query=str(query_text),
                embedding=None,
                limit=1,
                collection_ids=collection_ids or None,
            )
            result.tool_call_logs.append(
                _tool_call_log(
                    tool_name="search_catalog",
                    input_payload=search_input,
                    output_payload=(
                        [hit.model_dump(mode="json") for hit in catalog_hits]
                        if isinstance(catalog_hits, list)
                        else catalog_hits.model_dump(mode="json")
                    ),
                    started_at=tool_started,
                )
            )
            result.executed_tools.append(
                {
                    "tool": "search_catalog",
                    "query": str(query_text),
                    "status": (
                        catalog_hits.get("status")
                        if isinstance(catalog_hits, dict)
                        else (
                            "ok"
                            if isinstance(catalog_hits, list) and catalog_hits
                            else "no_data"
                        )
                    ),
                }
            )
            if not (isinstance(catalog_hits, list) and catalog_hits):
                if isinstance(catalog_hits, ToolNoDataResult):
                    last_hint = catalog_hits.hint
                else:
                    last_hint = f"no catalog match for {query_text!r}"
                continue

            tool_started = time.perf_counter()
            quote_input = {
                "sku": catalog_hits[0].sku,
                "plan_code": plan_code,
            }
            quote_result = await quote(
                session=self._session,
                tenant_id=tenant_id,
                sku=catalog_hits[0].sku,
                plan_code=plan_code,
            )
            result.action_payload = quote_result.model_dump(mode="json")
            result.tool_call_logs.append(
                _tool_call_log(
                    tool_name="quote",
                    input_payload=quote_input,
                    output_payload=result.action_payload,
                    started_at=tool_started,
                )
            )
            result.executed_tools.append(
                {
                    "tool": "quote",
                    "sku": catalog_hits[0].sku,
                    "plan_code": plan_code,
                    "status": (
                        result.action_payload.get("status")
                        if isinstance(result.action_payload, dict)
                        else None
                    ),
                }
            )
            if isinstance(result.action_payload, dict):
                result.action_payload["resolved_query"] = query_text
                result.action_payload["resolved_sku"] = catalog_hits[0].sku
                if plan_code:
                    result.action_payload["requested_plan_code"] = plan_code
            break

        if not result.action_payload:
            result.action_payload = ToolNoDataResult(
                hint=last_hint or "no product candidate extracted yet",
            ).model_dump(mode="json")
        return result.facts_only()

    async def lookup_faq(
        self,
        *,
        tenant_id: UUID,
        inbound_text: str,
        collection_ids: list[UUID],
        pack_faq_probe: dict[str, Any] | None,
        pack_faq_probe_ok: bool,
    ) -> ToolDispatchResult:
        result = ToolDispatchResult()
        faq_tool_started = time.perf_counter()
        faq_tool_input = {
            "text": inbound_text,
            "top_k": 3,
            "collection_ids": [str(item) for item in collection_ids or []],
        }
        if isinstance(pack_faq_probe, dict) and pack_faq_probe_ok:
            result.action_payload = pack_faq_probe
            result.executed_tools.append(
                {
                    "tool": "answer_faq",
                    "source": "knowledge_pack",
                    "status": "ok",
                }
            )
            result.tool_call_logs.append(
                _tool_call_log(
                    tool_name="answer_faq",
                    input_payload={
                        **faq_tool_input,
                        "source": "knowledge_pack",
                    },
                    output_payload=result.action_payload,
                    started_at=faq_tool_started,
                )
            )
            result.decision_payload = {
                "decision": "faq_answered",
                "faq_topic": result.action_payload.get("topic"),
                "answer": result.action_payload.get("answer"),
                "source": result.action_payload.get("source"),
            }
        elif self._settings.openai_api_key:
            from openai import AsyncOpenAI

            client = AsyncOpenAI(api_key=self._settings.openai_api_key)
            embedding, _, emb_cost = await generate_embedding(
                client=client,
                text=inbound_text,
            )
            result.tool_cost_usd += emb_cost
            faq_result = await lookup_faq(
                session=self._session,
                tenant_id=tenant_id,
                embedding=embedding,
                top_k=3,
                collection_ids=collection_ids or None,
            )
            result.executed_tools.append({"tool": "lookup_faq", "status": "ok"})
            if isinstance(faq_result, list):
                result.action_payload = {
                    "matches": [m.model_dump(mode="json") for m in faq_result],
                }
            else:
                result.action_payload = faq_result.model_dump(mode="json")
            result.tool_call_logs.append(
                _tool_call_log(
                    tool_name="lookup_faq",
                    input_payload=faq_tool_input,
                    output_payload=result.action_payload,
                    started_at=faq_tool_started,
                )
            )
        else:
            result.action_payload = ToolNoDataResult(
                hint="openai api key missing; cannot embed query",
            ).model_dump(mode="json")
            result.executed_tools.append({"tool": "lookup_faq", "status": "no_data"})
            result.tool_call_logs.append(
                _tool_call_log(
                    tool_name="lookup_faq",
                    input_payload=faq_tool_input,
                    output_payload=result.action_payload,
                    started_at=faq_tool_started,
                )
            )
        return result.facts_only()

    async def search_catalog(
        self,
        *,
        tenant_id: UUID,
        query_text: str,
        result_limit: int,
        catalog_browse_intent: str | None,
        catalog_browse_preview_limit: int,
        catalog_url: str,
        collection_ids: list[UUID],
        exclude_model_names: list[str] | None = None,
    ) -> ToolDispatchResult:
        result = ToolDispatchResult()
        keyword_hits: Any = None
        normalized_exclusions = {
            str(name or "").strip().casefold()
            for name in (exclude_model_names or [])
            if str(name or "").strip()
        }
        if catalog_browse_intent:
            tool_started = time.perf_counter()
            browse_category = str(query_text).strip() or None
            list_input = {
                "category": browse_category,
                "query": "",
                "limit": result_limit,
                "collection_ids": [str(item) for item in collection_ids or []],
                "mode": "catalog_browse",
            }
            catalog_list = await list_catalog(
                session=self._session,
                tenant_id=tenant_id,
                category=browse_category,
                query="",
                limit=result_limit,
                collection_ids=collection_ids or None,
            )
            catalog_list_payload = catalog_list.model_dump(mode="json")
            result.tool_call_logs.append(
                _tool_call_log(
                    tool_name="listCatalog",
                    input_payload=list_input,
                    output_payload=catalog_list_payload,
                    started_at=tool_started,
                )
            )
            result.executed_tools.append(
                {
                    "tool": "listCatalog",
                    "query": str(query_text),
                    "mode": "catalog_browse",
                    "status": catalog_list_payload.get("status"),
                }
            )
            if catalog_list_payload.get("status") == "ok":
                serialized_hits = catalog_list_payload.get("models") or []
                if normalized_exclusions:
                    serialized_hits = [
                        item
                        for item in serialized_hits
                        if str(
                            (item.get("name") if isinstance(item, dict) else None)
                            or (item.get("sku") if isinstance(item, dict) else None)
                            or ""
                        ).strip().casefold()
                        not in normalized_exclusions
                    ]
                preview_hits = serialized_hits[:catalog_browse_preview_limit]
                result.action_payload = {
                    "status": "ok",
                    "request_type": "catalog_browse",
                    "browse_intent": catalog_browse_intent,
                    "query": query_text,
                    "total_results": len(serialized_hits),
                    "shown_results": len(preview_hits),
                    "has_more": len(serialized_hits) > len(preview_hits),
                    "catalog_url": catalog_url,
                    "results": preview_hits,
                    "source": catalog_list_payload.get("source"),
                }
            else:
                result.action_payload = ToolNoDataResult(
                    hint="no active catalog items available for browsing",
                ).model_dump(mode="json")
            keyword_hits = []

        if keyword_hits is None:
            tool_started = time.perf_counter()
            search_input = {
                "query": str(query_text),
                "embedding": None,
                "limit": result_limit,
                "collection_ids": [str(item) for item in collection_ids or []],
                "mode": "search",
            }
            keyword_hits = await search_catalog(
                session=self._session,
                tenant_id=tenant_id,
                query=query_text,
                embedding=None,
                limit=result_limit,
                collection_ids=collection_ids or None,
            )
            result.tool_call_logs.append(
                _tool_call_log(
                    tool_name="search_catalog",
                    input_payload=search_input,
                    output_payload=(
                        [hit.model_dump(mode="json") for hit in keyword_hits]
                        if isinstance(keyword_hits, list)
                        else keyword_hits.model_dump(mode="json")
                    ),
                    started_at=tool_started,
                )
            )
            result.executed_tools.append(
                {
                    "tool": "search_catalog",
                    "query": str(query_text),
                    "mode": "search",
                    "status": (
                        keyword_hits.get("status")
                        if isinstance(keyword_hits, dict)
                        else (
                            "ok"
                            if isinstance(keyword_hits, list) and keyword_hits
                            else "no_data"
                        )
                    ),
                }
            )

        if not catalog_browse_intent and isinstance(keyword_hits, list) and keyword_hits:
            serialized_hits = [r.model_dump(mode="json") for r in keyword_hits]
            result.action_payload = {
                "results": serialized_hits,
            }
        elif not catalog_browse_intent and self._settings.openai_api_key:
            from openai import AsyncOpenAI

            client = AsyncOpenAI(api_key=self._settings.openai_api_key)
            embedding, _, emb_cost = await generate_embedding(
                client=client,
                text=query_text,
            )
            result.tool_cost_usd += emb_cost
            tool_started = time.perf_counter()
            semantic_input = {
                "query": str(query_text),
                "embedding_generated": True,
                "limit": result_limit,
                "collection_ids": [str(item) for item in collection_ids or []],
                "mode": "catalog_browse" if catalog_browse_intent else "search",
            }
            semantic_hits = await search_catalog(
                session=self._session,
                tenant_id=tenant_id,
                query=query_text,
                embedding=embedding,
                limit=result_limit,
                collection_ids=collection_ids or None,
            )
            result.tool_call_logs.append(
                _tool_call_log(
                    tool_name="search_catalog_semantic",
                    input_payload=semantic_input,
                    output_payload=(
                        [hit.model_dump(mode="json") for hit in semantic_hits]
                        if isinstance(semantic_hits, list)
                        else semantic_hits.model_dump(mode="json")
                    ),
                    started_at=tool_started,
                )
            )
            result.executed_tools.append(
                {
                    "tool": "search_catalog_semantic",
                    "query": str(query_text),
                    "mode": "catalog_browse" if catalog_browse_intent else "search",
                    "status": (
                        semantic_hits.get("status")
                        if isinstance(semantic_hits, dict)
                        else (
                            "ok"
                            if isinstance(semantic_hits, list) and semantic_hits
                            else "no_data"
                        )
                    ),
                }
            )
            if isinstance(semantic_hits, list):
                serialized_hits = [r.model_dump(mode="json") for r in semantic_hits]
                if catalog_browse_intent:
                    preview_hits = serialized_hits[:catalog_browse_preview_limit]
                    result.action_payload = {
                        "status": "ok",
                        "request_type": "catalog_browse",
                        "browse_intent": catalog_browse_intent,
                        "query": query_text,
                        "total_results": len(serialized_hits),
                        "shown_results": len(preview_hits),
                        "has_more": len(serialized_hits) > len(preview_hits),
                        "catalog_url": catalog_url,
                        "results": preview_hits,
                    }
                else:
                    result.action_payload = {
                        "results": serialized_hits,
                    }
            else:
                result.action_payload = semantic_hits.model_dump(mode="json")
        elif not catalog_browse_intent:
            result.action_payload = ToolNoDataResult(
                hint=f"no alias match for {query_text!r}; openai key missing for semantic",
            ).model_dump(mode="json")
        return result.facts_only()
