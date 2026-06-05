from __future__ import annotations

import re
import unicodedata
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from atendia.contracts.nlu_result import Intent
from atendia.contracts.turn_resolution import Evidence, ResolverAttempt, TurnResolverInput
from atendia.db.models.customer_fields import CustomerFieldDefinition
from atendia.tools.base import ToolNoDataResult
from atendia.tools.search_catalog import search_catalog

_CATALOG_BOUND_FIELD_TYPES = frozenset({"catalog_item", "product", "producto"})
_CATALOG_QUERY_STOPWORDS = frozenset(
    {
        "a",
        "al",
        "buenas",
        "con",
        "cotizar",
        "cuanto",
        "credito",
        "creditos",
        "de",
        "el",
        "esa",
        "ese",
        "financiamiento",
        "financiar",
        "gusta",
        "hola",
        "info",
        "informacion",
        "interesa",
        "interesado",
        "la",
        "las",
        "le",
        "los",
        "me",
        "modelo",
        "modelos",
        "moto",
        "motos",
        "motocicleta",
        "opciones",
        "para",
        "quiero",
        "que",
        "sale",
        "tal",
        "tendras",
        "tienes",
        "una",
        "un",
        "ver",
    }
)
_ASK_INFO_PRODUCT_MARKERS = (
    "me interesa",
    "quiero info",
    "quiero informacion",
    "tienes",
    "tendras",
    "me gusta",
    "que tal sale",
    "cuanto sale",
    "cuanto cuesta",
)
_SHORT_CONFIRMATION_TOKENS = frozenset(
    {"si", "no", "ok", "va", "sale", "claro", "simon"}
)
_REAL_CATALOG_CATEGORY_TOKENS = frozenset(
    {
        "chopper",
        "cuatrimoto",
        "cuatrimotos",
        "deportiva",
        "deportivas",
        "doble",
        "motocarro",
        "motocarros",
        "motoneta",
        "motonetas",
        "proposito",
        "scooter",
        "trabajo",
    }
)
_NON_PRODUCT_CONTEXT_TOKENS = frozenset(
    {
        "ano",
        "anos",
        "antiguedad",
        "atraso",
        "atrasos",
        "aval",
        "buro",
        "documento",
        "documentos",
        "domicilio",
        "direccion",
        "enganche",
        "empleo",
        "entrega",
        "liquidacion",
        "liquidar",
        "laboral",
        "mes",
        "meses",
        "mensualidad",
        "mensualidades",
        "pago",
        "pagos",
        "quincena",
        "quincenal",
        "quincenas",
        "requisito",
        "requisitos",
        "trabajo",
        "ubicacion",
    }
)


def _recent_catalog_or_quote_context(
    history: list[tuple[str, str]],
    *,
    inbound_text: str,
) -> bool:
    looks_like_model_request = _looks_like_product_reference(inbound_text) or _looks_like_model_alias_query(
        inbound_text
    )
    for role, text in reversed(history[-6:]):
        if role != "outbound" or not text:
            continue
        normalized = _normalize_catalog_text(text)
        if (
            "catalogo" in normalized
            or "opciones" in normalized
            or "modelo" in normalized
            or (
                looks_like_model_request
                and "$" in str(text)
                and any(marker in normalized for marker in ("enganche", "quincenal", "contado", "plazo"))
            )
        ):
            return True
    return False


def _normalize_catalog_text(value: str) -> str:
    text = unicodedata.normalize("NFKD", value or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return text.casefold()


def catalog_binding_config(field_definition: Any) -> dict[str, Any] | None:
    options = getattr(field_definition, "field_options", None) or {}
    binding = options.get("catalog_binding") if isinstance(options, dict) else None
    field_type = str(getattr(field_definition, "field_type", "") or "").casefold()
    if field_type in _CATALOG_BOUND_FIELD_TYPES:
        base = binding if isinstance(binding, dict) else {}
        return {"enabled": True, **base}
    if isinstance(binding, dict) and binding.get("enabled") is True:
        return binding
    return None


def catalog_binding_queries(inbound_text: str) -> list[str]:
    raw = (inbound_text or "").strip()
    normalized = _normalize_catalog_text(raw)
    queries: list[str] = []

    def add(value: str) -> None:
        query = value.strip()
        if query and query not in queries:
            queries.append(query)

    add(raw)
    tokens = [
        token
        for token in re.findall(r"[\w-]+", normalized, flags=re.UNICODE)
        if token not in _CATALOG_QUERY_STOPWORDS
        and (len(token) >= 2 or any(ch.isdigit() for ch in token))
    ]
    if tokens:
        add(" ".join(tokens))
    for size in (3, 2):
        for index in range(0, max(0, len(tokens) - size + 1)):
            add(" ".join(tokens[index : index + size]))
    for token in tokens:
        add(token)
    return queries[:8]


def _catalog_tokens(value: str) -> list[str]:
    return [
        token
        for token in re.findall(
            r"[\w-]+",
            _normalize_catalog_text(value or ""),
            flags=re.UNICODE,
        )
        if token not in _CATALOG_QUERY_STOPWORDS
        and (len(token) >= 2 or any(ch.isdigit() for ch in token))
    ]


def _query_safe_for_auto_write(inbound_text: str, query: str) -> bool:
    input_tokens = _catalog_tokens(inbound_text)
    query_tokens = _catalog_tokens(query)
    if not input_tokens or not query_tokens:
        return False
    if len(input_tokens) >= 3 and len(query_tokens) == 1:
        return False
    return len(query_tokens) / len(input_tokens) >= 0.5


def _looks_like_product_reference(inbound_text: str) -> bool:
    normalized = _normalize_catalog_text(inbound_text)
    tokens = _catalog_tokens(normalized)
    if not tokens:
        return False
    token_set = set(tokens)
    if token_set & _NON_PRODUCT_CONTEXT_TOKENS:
        return False
    if any(any(ch.isdigit() for ch in token) for token in tokens):
        return True
    if token_set & _REAL_CATALOG_CATEGORY_TOKENS:
        return False
    return any(marker in normalized for marker in _ASK_INFO_PRODUCT_MARKERS) and len(tokens) > 0


def _looks_like_model_alias_query(inbound_text: str) -> bool:
    tokens = _catalog_tokens(inbound_text)
    if not tokens or len(tokens) > 4:
        return False
    token_set = set(tokens)
    if token_set & _REAL_CATALOG_CATEGORY_TOKENS:
        return False
    if token_set & _NON_PRODUCT_CONTEXT_TOKENS:
        return False
    return all(len(token) >= 3 or any(ch.isdigit() for ch in token) for token in tokens)


def _catalog_candidate_names(result: Any) -> list[str]:
    if isinstance(result, ToolNoDataResult):
        return []
    names: list[str] = []
    for item in result:
        name = str(getattr(item, "name", None) or "").strip()
        if name and name not in names:
            names.append(name)
    return names[:3]


def _catalog_options_clarification(candidates: list[str]) -> str:
    options = "\n".join(
        f"{index}. {candidate}" for index, candidate in enumerate(candidates[:3], start=1)
    )
    return f"Encontre varias opciones parecidas:\n{options}\n\nCual modelo quieres revisar?"


def _catalog_single_candidate_clarification(candidate: str) -> str:
    return (
        "Creo que encontre una opcion parecida:\n"
        f"- {candidate}\n\n"
        "Si es esa, dime si. Si no, mandame el modelo exacto."
    )


def _looks_like_short_confirmation(inbound_text: str) -> bool:
    tokens = _catalog_tokens(inbound_text)
    return len(tokens) == 1 and tokens[0] in _SHORT_CONFIRMATION_TOKENS


def _catalog_resolution_allowed(input: TurnResolverInput) -> bool:
    if input.nlu.intent in {Intent.UNCLEAR, Intent.ASK_PRICE, Intent.BUY}:
        return True
    if input.nlu.confidence < 0.7:
        return True
    return input.nlu.intent == Intent.ASK_INFO and (
        _looks_like_product_reference(input.inbound_text)
        or _looks_like_model_alias_query(input.inbound_text)
    )


def _flat_extracted_values(extracted_data: dict[str, Any]) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for key, value in (extracted_data or {}).items():
        if isinstance(value, dict) and "value" in value:
            values[key] = value.get("value")
        else:
            values[key] = value
    return values


def _canonical_value(match: Any, binding: dict[str, Any]) -> str | None:
    canonical_field = str(binding.get("canonical_field") or "name").strip() or "name"
    payload = match.model_dump(mode="json") if hasattr(match, "model_dump") else {}
    value = getattr(match, canonical_field, None)
    if value is None and isinstance(payload, dict):
        value = payload.get(canonical_field)
    if value is None:
        value = getattr(match, "name", None) or (
            payload.get("name") if isinstance(payload, dict) else None
        )
    if value is None:
        return None
    text_value = str(value).strip()
    return text_value or None


def _match_confidence(match: Any, min_score: float) -> float:
    raw_score = getattr(match, "score", None)
    try:
        score = float(raw_score)
    except (TypeError, ValueError):
        score = min_score
    if min_score <= 0:
        return 1.0
    return max(0.0, min(1.0, score / min_score))


def _tool_result_payload(query: str, result: Any) -> dict[str, Any]:
    if isinstance(result, ToolNoDataResult):
        return {
            "tool": "search_catalog",
            "query": query,
            "status": "no_data",
            "output": result.model_dump(mode="json"),
        }
    return {
        "tool": "search_catalog",
        "query": query,
        "status": "ok",
        "output": [item.model_dump(mode="json") for item in result],
    }


class CatalogResolver:
    name = "catalog_resolver"

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def resolve(self, input: TurnResolverInput) -> ResolverAttempt | None:
        if re.fullmatch(r"\s*\d{1,2}\s*%?\s*", input.inbound_text or ""):
            return None
        if _looks_like_short_confirmation(input.inbound_text):
            return None
        if not _catalog_resolution_allowed(input):
            return None

        candidates = await self._catalog_bound_candidates(input)
        if len(candidates) != 1:
            if len(candidates) > 1:
                return ResolverAttempt(
                    resolver=self.name,
                    input=input.inbound_text,
                    confidence=0.0,
                    can_write_state=False,
                    blocked_reason="multiple_catalog_bound_fields",
                )
            return None

        field, binding = candidates[0]
        min_score = float(binding.get("min_score") or 1)
        no_match_results: list[dict[str, Any]] = []
        for query in catalog_binding_queries(input.inbound_text):
            result = await search_catalog(
                session=self._session,
                tenant_id=input.tenant_id,
                query=query,
                embedding=None,
                limit=3,
            )
            tool_result = _tool_result_payload(query, result)
            if isinstance(result, ToolNoDataResult):
                no_match_results.append(tool_result)
                continue
            if len(result) != 1:
                candidates = _catalog_candidate_names(result)
                return ResolverAttempt(
                    resolver=self.name,
                    input=input.inbound_text,
                    understood_as="multiple_catalog_matches",
                    confidence=0.55,
                    can_write_state=False,
                    requires_confirmation=True,
                    suggested_clarification=_catalog_options_clarification(candidates),
                    blocked_reason="multiple_catalog_matches",
                    tool_results=[tool_result],
                    evidence=[
                        Evidence(
                            type="tool_result",
                            source="search_catalog",
                            value="multiple_matches",
                            confidence=0.55,
                            metadata={
                                "query": query,
                                "count": len(result),
                                "catalog_candidates": candidates,
                            },
                        )
                    ],
                )

            match = result[0]
            try:
                score = float(match.score)
            except (TypeError, ValueError):
                score = min_score
            if score < min_score:
                return ResolverAttempt(
                    resolver=self.name,
                    input=input.inbound_text,
                    understood_as=getattr(match, "name", None),
                    confidence=_match_confidence(match, min_score),
                    can_write_state=False,
                    requires_confirmation=True,
                    suggested_clarification=_catalog_single_candidate_clarification(
                        str(getattr(match, "name", None) or "").strip()
                    ),
                    blocked_reason="catalog_match_below_threshold",
                    tool_results=[tool_result],
                    evidence=[
                        Evidence(
                            type="catalog_match",
                            source="search_catalog",
                            value=getattr(match, "name", None),
                            confidence=_match_confidence(match, min_score),
                            metadata={
                                "query": query,
                                "catalog_candidates": _catalog_candidate_names([match]),
                            },
                        )
                    ],
                )

            if not _query_safe_for_auto_write(input.inbound_text, query):
                return ResolverAttempt(
                    resolver=self.name,
                    input=input.inbound_text,
                    understood_as=getattr(match, "name", None),
                    confidence=0.64,
                    can_write_state=False,
                    requires_confirmation=True,
                    suggested_clarification=_catalog_single_candidate_clarification(
                        str(getattr(match, "name", None) or "").strip()
                    ),
                    blocked_reason="catalog_query_low_coverage",
                    tool_results=[tool_result],
                    evidence=[
                        Evidence(
                            type="catalog_match",
                            source="search_catalog",
                            value=getattr(match, "name", None),
                            confidence=0.64,
                            metadata={
                                "query": query,
                                "catalog_candidates": _catalog_candidate_names([match]),
                            },
                        )
                    ],
                )

            value = _canonical_value(match, binding)
            if value is None:
                return ResolverAttempt(
                    resolver=self.name,
                    input=input.inbound_text,
                    confidence=0.0,
                    can_write_state=False,
                    blocked_reason="catalog_match_missing_canonical_value",
                    tool_results=[tool_result],
                )

            confidence = _match_confidence(match, min_score)
            return ResolverAttempt(
                resolver=self.name,
                input=input.inbound_text,
                understood_as=value,
                evidence=[
                    Evidence(
                        type="catalog_unique_match",
                        source="search_catalog",
                        value=value,
                        confidence=confidence,
                    metadata={
                        "query": query,
                        "sku": getattr(match, "sku", None),
                        "field": field.key,
                        "catalog_candidates": _catalog_candidate_names([match]),
                    },
                )
            ],
                tool_results=[tool_result],
                confidence=confidence,
                can_write_state=True,
                requires_confirmation=False,
                field_updates={field.key: value},
                next_action="quote_or_ask_missing_plan",
            )

        return ResolverAttempt(
            resolver=self.name,
            input=input.inbound_text,
            understood_as="catalog_no_match",
            confidence=0.0,
            can_write_state=False,
            requires_confirmation=False,
            suggested_clarification=(
                "No ubique ese modelo con seguridad. "
                "Dime el nombre exacto o te paso opciones por categoria."
            ),
            blocked_reason="no_catalog_match",
            tool_results=no_match_results,
        )

    async def _catalog_bound_candidates(
        self,
        input: TurnResolverInput,
    ) -> list[tuple[CustomerFieldDefinition, dict[str, Any]]]:
        rows = (
            (
                await self._session.execute(
                    select(CustomerFieldDefinition)
                    .where(CustomerFieldDefinition.tenant_id == input.tenant_id)
                    .order_by(
                        CustomerFieldDefinition.ordering.asc(),
                        CustomerFieldDefinition.created_at.asc(),
                    )
                )
            )
            .scalars()
            .all()
        )
        flat_values = _flat_extracted_values(input.extracted_data)
        candidates: list[tuple[CustomerFieldDefinition, dict[str, Any]]] = []
        for row in rows:
            if row.key in input.nlu.entities:
                continue
            if row.key in flat_values:
                if not (
                    row.key == "MOTO"
                    and _recent_catalog_or_quote_context(
                        input.history,
                        inbound_text=input.inbound_text,
                    )
                ):
                    continue
            binding = catalog_binding_config(row)
            if binding is not None:
                candidates.append((row, binding))
        return candidates
