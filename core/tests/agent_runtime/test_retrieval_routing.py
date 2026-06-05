from __future__ import annotations

from uuid import uuid4

from atendia.simulation.run_dinamo_provider_battery import _routed_source_ids


def test_generic_credit_no_catalog_citations() -> None:
    catalog = uuid4()
    requisitos = uuid4()
    faq = uuid4()
    routed = _routed_source_ids(
        "quiero una moto a credito",
        {
            "catalogo_dinamo": catalog,
            "requisitos_dinamo": requisitos,
            "faq_dinamo": faq,
        },
        {catalog, requisitos, faq},
    )
    assert routed == {requisitos}


def test_catalog_intent_uses_faq_for_plain_link() -> None:
    catalog = uuid4()
    requisitos = uuid4()
    faq = uuid4()
    routed = _routed_source_ids(
        "me pasas catalogo?",
        {
            "catalogo_dinamo": catalog,
            "requisitos_dinamo": requisitos,
            "faq_dinamo": faq,
        },
        {catalog, requisitos, faq},
    )
    assert routed == {faq}


def test_model_and_recommendation_retrieve_catalog() -> None:
    catalog = uuid4()
    requisitos = uuid4()
    routed = _routed_source_ids(
        "quiero una moto barata para trabajar",
        {"catalogo_dinamo": catalog, "requisitos_dinamo": requisitos},
        {catalog, requisitos},
    )
    assert routed == {catalog}

