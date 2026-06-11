"""Real-facts tool executor for Respond-Style visible turns (live/smoke).

Pure and synchronous like the dry executor, but grounded on REAL tenant
data preloaded by the caller (catalog items + Knowledge OS requirement
plans). Dispatch is data-driven: each tool binding declares
``real_source`` — which real dataset answers it — so tool NAMES stay
tenant configuration and this module stays vertical-agnostic.

Supported real_source values:
- ``catalog_search``: token-match the query against model aliases/labels/
  search text; returns matching models with real prices and plan options.
- ``catalog_quote``: resolve one model (payload or contact state) and
  return its real prices and credit plan table.
- ``knowledge_plans``: return the requirement/credit-plan records whose
  aliases match the customer's income description (or all, compact).
"""

from __future__ import annotations

import unicodedata
from typing import Any

from atendia.agent_runtime.respond_style_tool_loop import ToolExecutionResult
from atendia.agent_runtime.respond_style_turn_contract import (
    AgentContextPackage,
    LLMToolCallProposal,
)

JsonDict = dict[str, Any]


def _fold(value: Any) -> str:
    text = unicodedata.normalize("NFD", str(value or "").casefold())
    return "".join(ch for ch in text if not unicodedata.combining(ch))


class RealFactsToolExecutor:
    """Answers tool calls from preloaded REAL tenant facts."""

    def __init__(
        self,
        tool_bindings: list[JsonDict],
        facts: JsonDict,
    ) -> None:
        self._bindings: dict[str, JsonDict] = {}
        self._preconditions: dict[str, list[str]] = {}
        for binding in tool_bindings:
            if not isinstance(binding, dict):
                continue
            name = str(binding.get("name") or binding.get("tool_name") or "").strip()
            if not name:
                continue
            self._bindings[name] = binding
            self._preconditions[name] = [
                str(item) for item in binding.get("preconditions") or []
            ]
        self._models: list[JsonDict] = list(facts.get("models") or [])
        self._plans: list[JsonDict] = list(facts.get("requirement_plans") or [])

    def execute_tool(
        self,
        tool_call: LLMToolCallProposal,
        context: AgentContextPackage,
    ) -> ToolExecutionResult:
        binding = self._bindings.get(tool_call.tool_name)
        if binding is None:
            return self._skip(tool_call, "tool_not_available")
        resolved, missing = self._resolve_preconditions(tool_call, context)
        if missing:
            return self._skip(tool_call, f"missing_precondition:{missing[0]}")
        real_source = str(binding.get("real_source") or "")
        if real_source == "catalog_search":
            facts = self._catalog_search(tool_call, resolved)
            kind = "real_catalog"
        elif real_source == "catalog_quote":
            facts = self._catalog_quote(tool_call, resolved)
            kind = "real_catalog"
        elif real_source == "knowledge_plans":
            facts = self._knowledge_plans(tool_call, resolved)
            kind = "knowledge_os"
        else:
            return self._skip(tool_call, "real_source_not_configured")
        if facts is None:
            return self._skip(tool_call, "no_real_data_match")
        return ToolExecutionResult(
            tool_name=tool_call.tool_name,
            status="succeeded",
            facts=facts,
            citations=[f"{tool_call.tool_name}-{kind}"],
            source_refs=[tool_call.tool_name],
            is_required=tool_call.required,
            can_support_claims=True,
            source_kind=kind,
        )

    # --- real datasets --------------------------------------------------

    def _catalog_search(
        self, tool_call: LLMToolCallProposal, resolved: JsonDict
    ) -> JsonDict | None:
        if not self._models:
            return None
        query_parts = [
            str(value)
            for value in {**resolved, **dict(tool_call.arguments or {})}.values()
            if isinstance(value, (str, int, float)) and str(value).strip()
        ]
        tokens = [tok for part in query_parts for tok in _fold(part).split() if tok]
        scored: list[tuple[int, JsonDict]] = []
        for model in self._models:
            haystack = _fold(
                " ".join(
                    [
                        str(model.get("label") or ""),
                        str(model.get("category") or ""),
                        " ".join(model.get("aliases") or []),
                        " ".join(model.get("tags") or []),
                        str(model.get("search_text") or ""),
                    ]
                )
            )
            score = sum(1 for tok in tokens if tok in haystack)
            scored.append((score, model))
        scored.sort(key=lambda pair: -pair[0])
        top = [model for score, model in scored if score > 0][:5]
        if not top and not tokens:
            top = [model for _, model in scored][:5]
        return {
            "models": [self._model_summary(model) for model in top],
            "total_models_in_catalog": len(self._models),
        }

    def _catalog_quote(
        self, tool_call: LLMToolCallProposal, resolved: JsonDict
    ) -> JsonDict | None:
        wanted = None
        for key in ("selected_model", "model", "model_id", "modelo"):
            wanted = (dict(tool_call.arguments or {}).get(key)) or resolved.get(key)
            if wanted:
                break
        if not wanted:
            return None
        folded = _fold(wanted)
        for model in self._models:
            terms = [
                str(model.get("model_id") or ""),
                str(model.get("label") or ""),
                *(model.get("aliases") or []),
            ]
            if any(_fold(term) == folded for term in terms if term):
                return {
                    "model": self._model_summary(model),
                    "price_lista_mxn": model.get("price_lista_mxn"),
                    "price_contado_mxn": model.get("price_contado_mxn"),
                    "planes_credito": model.get("planes_credito") or {},
                }
        return None

    def _knowledge_plans(
        self, tool_call: LLMToolCallProposal, resolved: JsonDict
    ) -> JsonDict | None:
        if not self._plans:
            return None
        query_parts = [
            str(value)
            for value in {**resolved, **dict(tool_call.arguments or {})}.values()
            if isinstance(value, str) and value.strip()
        ]
        folded_query = _fold(" ".join(query_parts))
        matched: list[JsonDict] = []
        for plan in self._plans:
            aliases = [_fold(alias) for alias in plan.get("aliases_usuario") or []]
            tipo = _fold(plan.get("tipo_credito"))
            if folded_query and (
                any(alias and alias in folded_query for alias in aliases)
                or (tipo and tipo in folded_query)
            ):
                matched.append(plan)
        chosen = matched or self._plans
        return {
            "plans": [
                {
                    "tipo_credito": plan.get("tipo_credito"),
                    "plan_credito": plan.get("plan_credito"),
                    "detalle": plan.get("texto_retrieval"),
                }
                for plan in chosen[:6]
            ],
            "matched": bool(matched),
        }

    @staticmethod
    def _model_summary(model: JsonDict) -> JsonDict:
        plans = model.get("planes_credito") or {}
        return {
            "model_id": model.get("model_id"),
            "label": model.get("label"),
            "category": model.get("category"),
            "price_lista_mxn": model.get("price_lista_mxn"),
            "price_contado_mxn": model.get("price_contado_mxn"),
            "tags": model.get("tags") or [],
            "planes_disponibles": sorted(plans.keys()),
            "planes_credito": plans,
        }

    # --- shared helpers --------------------------------------------------

    def _resolve_preconditions(
        self,
        tool_call: LLMToolCallProposal,
        context: AgentContextPackage,
    ) -> tuple[JsonDict, list[str]]:
        contact_state = context.agent_identity.get("contact_state") or {}
        arguments = dict(tool_call.arguments or {})
        resolved: JsonDict = {}
        missing: list[str] = []
        for key in self._preconditions.get(tool_call.tool_name, []):
            value = arguments.get(key)
            if value in (None, ""):
                value = contact_state.get(key)
            if value in (None, ""):
                missing.append(key)
            else:
                resolved[key] = value
        return resolved, missing

    def _skip(
        self, tool_call: LLMToolCallProposal, reason: str
    ) -> ToolExecutionResult:
        return ToolExecutionResult(
            tool_name=tool_call.tool_name,
            status="skipped",
            facts={},
            error_code=reason,
            is_required=tool_call.required,
            can_support_claims=False,
            source_kind="real_catalog",
        )


__all__ = ["RealFactsToolExecutor"]
