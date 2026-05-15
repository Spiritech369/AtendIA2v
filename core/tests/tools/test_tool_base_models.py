"""T8 — Pydantic result models for the real-data tools (Phase 3c.1).

`Quote` is what `quote()` returns when it finds a SKU. `FAQMatch` is a single
hit from `lookup_faq()`. `CatalogResult` is one row of `search_catalog()`'s
ranked list (lighter than `Quote` — no full ficha técnica).
"""

from decimal import Decimal

import pytest
from pydantic import ValidationError

from atendia.tools.base import CatalogResult, FAQMatch, Quote


def test_quote_status_is_literal_ok() -> None:
    """Quote always discriminates as status='ok' so the Composer router
    can branch on payload['status'] without re-introspecting the type."""
    q = Quote(
        sku="adventure-150-cc",
        name="Adventure 150 CC",
        category="Motoneta",
        price_lista_mxn=Decimal("31395"),
        price_contado_mxn=Decimal("29900"),
        planes_credito={"plan_10": {"enganche": 3140}},
        ficha_tecnica={"motor_cc": 150},
    )
    assert q.status == "ok"
    assert q.sku == "adventure-150-cc"
    assert q.price_contado_mxn == Decimal("29900")


def test_quote_rejects_explicit_non_ok_status() -> None:
    """Literal["ok"] is the only valid status — anything else must fail."""
    with pytest.raises(ValidationError):
        Quote(
            status="error",  # type: ignore[arg-type]
            sku="x",
            name="X",
            category="y",
            price_lista_mxn=Decimal("0"),
            price_contado_mxn=Decimal("0"),
            planes_credito={},
            ficha_tecnica={},
        )


def test_quote_requires_all_money_fields() -> None:
    """Money fields are required — Composer prompt assumes both prices exist."""
    with pytest.raises(ValidationError):
        Quote(  # type: ignore[call-arg]
            sku="x",
            name="X",
            category="y",
            price_lista_mxn=Decimal("100"),
            # price_contado_mxn missing
            planes_credito={},
            ficha_tecnica={},
        )


def test_faq_match_score_validation() -> None:
    """FAQMatch carries the raw cosine similarity for downstream filtering."""
    m = FAQMatch(pregunta="¿Qué documentos necesito?", respuesta="INE + comprobante", score=0.85)
    assert m.score == pytest.approx(0.85)
    assert m.pregunta.startswith("¿")


def test_faq_match_score_must_be_float() -> None:
    """Scores are float — strings or non-numerics must be rejected."""
    with pytest.raises(ValidationError):
        FAQMatch(pregunta="x", respuesta="y", score="high")  # type: ignore[arg-type]


def test_catalog_result_minimal() -> None:
    """search_catalog() returns CatalogResult — slimmer than Quote so we can
    rank many results without paying the full ficha-técnica round-trip."""
    r = CatalogResult(
        sku="adventure-150-cc",
        name="Adventure 150 CC",
        category="Motoneta",
        price_contado_mxn=Decimal("29900"),
        score=1.0,
    )
    assert r.sku == "adventure-150-cc"
    assert r.score == 1.0
    assert r.price_contado_mxn == Decimal("29900")


def test_catalog_result_score_required() -> None:
    """Score is required — CatalogResult must always be rankable."""
    with pytest.raises(ValidationError):
        CatalogResult(  # type: ignore[call-arg]
            sku="x",
            name="X",
            category="y",
            price_contado_mxn=Decimal("0"),
        )
