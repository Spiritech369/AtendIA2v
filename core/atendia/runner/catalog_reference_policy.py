from __future__ import annotations

import re
import unicodedata


CATALOG_BROWSE_PHRASES: frozenset[str] = frozenset(
    {
        "a ver las motos",
        "ver las motos",
        "ver motos",
        "muestrame motos",
        "muestrame las motos",
        "mostrar motos",
        "motos disponibles",
        "modelos disponibles",
        "opciones de motos",
        "que motos tienes",
        "que motos manejan",
        "que opciones tienes",
        "que opciones manejan",
        "opciones tienes",
        "opciones manejan",
        "cuales motos tienes",
        "cuales motos manejan",
        "dame motos",
        "pasa motos",
    }
)
CATALOG_FULL_PHRASES: frozenset[str] = frozenset(
    {
        "catalogo",
        "catalog",
        "catalogo completo",
        "dame el catalogo",
        "mandame el catalogo",
        "pasa el catalogo",
        "quiero el catalogo",
    }
)
CATALOG_MORE_PHRASES: frozenset[str] = frozenset(
    {
        "solo esas",
        "son todas",
        "esas son todas",
        "solo tienen esas",
        "no hay mas",
        "hay mas",
        "tienes mas",
        "mas opciones",
        "otras motos",
        "otros modelos",
    }
)
_ALTERNATIVE_OPTION_TERMS: frozenset[str] = frozenset(
    {
        "otra",
        "otro",
        "opcion",
        "opciones",
        "alternativa",
        "alternativas",
    }
)
_ALTERNATIVE_PRICE_TERMS: frozenset[str] = frozenset(
    {
        "barata",
        "barato",
        "baratas",
        "baratos",
        "economica",
        "economico",
        "economicas",
        "economicos",
        "mas",
        "menos",
        "mejor",
    }
)
_ALTERNATIVE_VERBS: frozenset[str] = frozenset(
    {
        "quiero",
        "tienes",
        "hay",
        "ver",
        "revisar",
        "buscar",
        "cotizar",
    }
)
CATALOG_STYLE_TERMS: frozenset[str] = frozenset(
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
        "naked",
        "scooter",
        "trabajo",
        "urbana",
        "urbanas",
    }
)
CATALOG_BROWSE_RESULT_LIMIT = 50
CATALOG_BROWSE_PREVIEW_LIMIT = 10


def catalog_text_key(text_value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", str(text_value or "").casefold())
    without_accents = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", without_accents)).strip()


def catalog_text_tokens(text_value: str) -> list[str]:
    normalized = catalog_text_key(text_value)
    return [token for token in normalized.split(" ") if token]


def catalog_style_query(text_value: str) -> str | None:
    tokens = catalog_text_tokens(text_value)
    aliases = {
        "cuatrimotos": "cuatrimoto",
        "deportivas": "deportiva",
        "motocarros": "motocarro",
        "motonetas": "motoneta",
        "scooter": "motoneta",
        "urbanas": "urbana",
    }
    for token in tokens:
        if token in CATALOG_STYLE_TERMS:
            return aliases.get(token, token)
    if "doble proposito" in catalog_text_key(text_value):
        return "doble proposito"
    return None


def catalog_ad_reference(text_value: str) -> bool:
    tokens = set(catalog_text_tokens(text_value))
    if not tokens:
        return False
    reference = any(token.startswith("anunci") or token.startswith("public") for token in tokens)
    if not reference:
        return False
    catalog_nouns = {"moto", "motos", "motocicleta", "modelo", "modelos", "opcion", "opciones"}
    return bool(tokens & catalog_nouns) or bool(tokens & {"quiero", "busco", "interesa"})


def history_looks_like_catalog_options(history: list[tuple[str, str]]) -> bool:
    for role, text_value in reversed(history[-4:]):
        if role != "outbound" or not text_value:
            continue
        normalized = catalog_text_key(text_value)
        if (
            "catalogo" in normalized
            or ("moto" in normalized and ("opciones" in normalized or "modelo" in normalized))
            or (
                "opciones" in normalized
                and any(term in normalized for term in CATALOG_STYLE_TERMS)
            )
        ):
            return True
    return False


def history_looks_like_recent_quote(history: list[tuple[str, str]]) -> bool:
    for role, text_value in reversed(history[-6:]):
        if role != "outbound" or not text_value:
            continue
        normalized = catalog_text_key(text_value)
        if "$" in str(text_value) and (
            "enganche" in normalized
            or "quincenal" in normalized
            or "contado" in normalized
            or "plazo" in normalized
        ):
            return True
    return False


def alternative_quote_request(
    *,
    inbound_text: str,
    history: list[tuple[str, str]],
) -> bool:
    tokens = set(catalog_text_tokens(inbound_text))
    if not tokens or not history_looks_like_recent_quote(history):
        return False
    has_alternative_signal = bool(tokens & _ALTERNATIVE_OPTION_TERMS)
    has_price_signal = bool(tokens & _ALTERNATIVE_PRICE_TERMS)
    has_followup_verb = bool(tokens & _ALTERNATIVE_VERBS) or "?" in str(inbound_text or "")
    return (has_alternative_signal and has_price_signal) or (
        has_alternative_signal and has_followup_verb
    )


def catalog_browse_request_type(
    *,
    inbound_text: str,
    history: list[tuple[str, str]],
) -> str | None:
    normalized = catalog_text_key(inbound_text)
    if not normalized:
        return None
    if catalog_ad_reference(inbound_text):
        return "ad_reference"
    if any(phrase in normalized for phrase in CATALOG_FULL_PHRASES):
        return "full_catalog"
    if any(phrase in normalized for phrase in CATALOG_BROWSE_PHRASES):
        return "catalog_overview"
    if catalog_style_query(inbound_text):
        return "catalog_style"
    if alternative_quote_request(inbound_text=inbound_text, history=history):
        return "catalog_more"
    if (
        any(phrase in normalized for phrase in CATALOG_MORE_PHRASES)
        and history_looks_like_catalog_options(history)
    ):
        return "catalog_more"
    return None


def catalog_browse_query(
    *,
    browse_intent: str | None,
    inbound_text: str,
    history: list[tuple[str, str]],
) -> str:
    if browse_intent == "catalog_style":
        return catalog_style_query(inbound_text) or ""
    if browse_intent == "catalog_more":
        for role, text_value in reversed(history[-6:]):
            if role == "outbound":
                query = catalog_style_query(text_value)
                if query:
                    return query
        for role, text_value in reversed(history[-6:]):
            if role == "inbound":
                query = catalog_style_query(text_value)
                if query:
                    return query
    return ""


__all__ = [
    "CATALOG_BROWSE_PREVIEW_LIMIT",
    "CATALOG_BROWSE_RESULT_LIMIT",
    "catalog_browse_query",
    "catalog_browse_request_type",
]
