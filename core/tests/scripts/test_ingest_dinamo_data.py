"""T13 — Tests for the ingestion-helper functions (no IO).

`ingest_dinamo_data.py` exposes three pure helpers that the async
`_main` (T14) composes:

  * `_slugify(s)` — model name to SKU
  * `_flatten_catalog(json)` — categorised tree to flat list
  * `_embedding_text_for_catalog_item(item)` — concat fields for embedding

Tests are pure functions on dicts/strings, no DB, no API. T14 adds the
async `_main` and T15 runs it for real.
"""
from atendia.scripts.ingest_dinamo_data import (
    _embedding_text_for_catalog_item,
    _flatten_catalog,
    _slugify,
)


def test_slugify_simple_lowercase_with_hyphens() -> None:
    """Spaces become hyphens, all lowercased."""
    assert _slugify("Adventure Elite 150 CC") == "adventure-elite-150-cc"


def test_slugify_preserves_internal_hyphens() -> None:
    """Existing hyphens (e.g. 'Cab-R') survive — only whitespace is converted."""
    assert _slugify("Heavy Cab-R 200 CC") == "heavy-cab-r-200-cc"


def test_slugify_treats_slash_as_word_separator() -> None:
    """Slash should split words, not double-hyphenate them."""
    assert _slugify("MotoCross / Doble Propósito") == "motocross-doble-propósito"


def test_slugify_collapses_multiple_spaces() -> None:
    """Tabs / runs of spaces collapse to a single hyphen."""
    assert _slugify("X    Y\tZ") == "x-y-z"


def test_flatten_catalog_two_categories() -> None:
    """Each model in the tree becomes a flat row with `category` set."""
    sample = {
        "catalogo": [
            {"categoria": "Motoneta", "modelos": [
                {
                    "modelo": "X 100 CC",
                    "alias": ["x"],
                    "ficha_tecnica": {"motor_cc": 100},
                    "precios": {"lista": 20000, "contado": 19000},
                    "planes_credito": {"plan_10": {"enganche": 2000}},
                },
            ]},
            {"categoria": "Chopper", "modelos": [
                {
                    "modelo": "Y 200 CC",
                    "alias": ["y"],
                    "ficha_tecnica": {"motor_cc": 200},
                    "precios": {"lista": 30000, "contado": 28000},
                    "planes_credito": {},
                },
            ]},
        ],
    }
    items = _flatten_catalog(sample)
    assert len(items) == 2

    assert items[0]["sku"] == "x-100-cc"
    assert items[0]["name"] == "X 100 CC"
    assert items[0]["category"] == "Motoneta"
    assert items[0]["attrs"]["alias"] == ["x"]
    assert items[0]["attrs"]["precio_lista"] == "20000"
    assert items[0]["attrs"]["precio_contado"] == "19000"
    assert items[0]["attrs"]["planes_credito"] == {"plan_10": {"enganche": 2000}}
    assert items[0]["attrs"]["ficha_tecnica"] == {"motor_cc": 100}

    assert items[1]["sku"] == "y-200-cc"
    assert items[1]["category"] == "Chopper"
    assert items[1]["attrs"]["planes_credito"] == {}


def test_flatten_catalog_handles_missing_optional_keys() -> None:
    """Models with no `precios`/`planes_credito` get string '0' / empty defaults."""
    sample = {
        "catalogo": [
            {"categoria": "Otro", "modelos": [
                {"modelo": "Bare Model", "ficha_tecnica": {}, "alias": []},
            ]},
        ],
    }
    items = _flatten_catalog(sample)
    assert items[0]["attrs"]["precio_lista"] == "0"
    assert items[0]["attrs"]["precio_contado"] == "0"
    assert items[0]["attrs"]["planes_credito"] == {}
    assert items[0]["attrs"]["alias"] == []


def test_flatten_catalog_empty_input() -> None:
    """Missing or empty `catalogo` returns []."""
    assert _flatten_catalog({}) == []
    assert _flatten_catalog({"catalogo": []}) == []


def test_embedding_text_includes_all_signals() -> None:
    """The embedded text must include every signal we want queries to match."""
    item = {
        "name": "Adventure 150 CC",
        "category": "Motoneta",
        "attrs": {
            "alias": ["adventure", "elite"],
            "ficha_tecnica": {"motor_cc": 150, "potencia_hp": 9, "transmision": "Automática"},
            "precio_contado": "29900",
        },
    }
    text = _embedding_text_for_catalog_item(item)
    assert "Categoría: Motoneta" in text
    assert "Adventure 150 CC" in text
    assert "150" in text
    assert "29900" in text
    assert "adventure" in text
    assert "Automática" in text


def test_embedding_text_handles_missing_ficha_fields() -> None:
    """Items with partial ficha_tecnica still produce non-empty text."""
    item = {
        "name": "Spartan",
        "category": "Otro",
        "attrs": {"alias": [], "ficha_tecnica": {}, "precio_contado": "10000"},
    }
    text = _embedding_text_for_catalog_item(item)
    assert "Spartan" in text
    assert "10000" in text


# ----- T14: helpers added alongside _main ---------------------------------

from atendia.scripts.ingest_dinamo_data import (
    _embedding_text_for_faq,
    _vec_to_pg_text,
)


def test_embedding_text_for_faq_concatenates_q_and_a() -> None:
    """The text we embed must include both question and answer."""
    text = _embedding_text_for_faq({
        "pregunta": "¿Cuánto es el enganche?",
        "respuesta": "Depende del plan.",
    })
    assert "¿Cuánto es el enganche?" in text
    assert "Depende del plan." in text


def test_embedding_text_for_faq_includes_detalle_per_plan() -> None:
    """`detalle_por_plan` keys/values are flattened into the embedded text."""
    text = _embedding_text_for_faq({
        "pregunta": "¿Cuánto es el enganche?",
        "respuesta": "Depende del plan.",
        "detalle_por_plan": {"nomina_tarjeta": "10%", "sin_comprobar": "20%"},
    })
    assert "nomina_tarjeta: 10%" in text
    assert "sin_comprobar: 20%" in text


def test_embedding_text_for_faq_includes_documentos_list() -> None:
    """`documentos` list members are appended (one keyword per item)."""
    text = _embedding_text_for_faq({
        "pregunta": "¿Qué requisitos?",
        "respuesta": "Estos:",
        "documentos": ["INE vigente", "Comprobante de domicilio"],
    })
    assert "INE vigente" in text
    assert "Comprobante de domicilio" in text


def test_vec_to_pg_text_format() -> None:
    """Output must be the bracketed comma-separated form pgvector parses."""
    out = _vec_to_pg_text([0.1, -0.5, 1.0])
    # Brackets, no spaces (minimal), correct values.
    assert out.startswith("[")
    assert out.endswith("]")
    assert "0.1" in out
    assert "-0.5" in out
    assert "1.0" in out


def test_vec_to_pg_text_empty() -> None:
    """Edge: empty list still produces valid text (`[]`)."""
    assert _vec_to_pg_text([]) == "[]"
