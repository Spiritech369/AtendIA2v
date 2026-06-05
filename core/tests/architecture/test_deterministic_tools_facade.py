from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from atendia.commercial_catalog_service import publish_authoring_catalog
from atendia.credit_plan_invariants import build_credit_plan_menu
from atendia.contracts.pipeline_definition import PipelineDefinition
from atendia.db.models.commercial_catalog import Catalog, CatalogItem
from atendia.db.models.tenant import Tenant
from atendia.db.session import _get_factory
from atendia.tools.base import ToolNoDataResult
from atendia.tools.deterministic import (
    CatalogListResult,
    CreditPlanResolutionResult,
    MissingDocumentsResult,
    get_missing_documents,
    getMissingDocuments,
    list_catalog,
    listCatalog,
    resolve_credit_plan,
    resolveCreditPlan,
)


def test_facade_exports_camel_case_tool_contracts() -> None:
    assert listCatalog is list_catalog
    assert resolveCreditPlan is resolve_credit_plan
    assert getMissingDocuments is get_missing_documents


def test_resolve_credit_plan_returns_canonical_field_update() -> None:
    pipeline = _credit_pipeline()

    result = resolveCreditPlan(input_text="por fuera", pipeline=pipeline)
    numeric_result = resolveCreditPlan(input_text="20", pipeline=pipeline)

    assert isinstance(result, CreditPlanResolutionResult)
    assert result.selection_key == "Sin Comprobantes"
    assert result.selection_label == "Sin Comprobantes"
    assert result.field_name == "CREDITO"
    assert result.field_updates == {"CREDITO": "Sin Comprobantes", "ENGANCHE": "20%"}
    assert result.down_payment == "20%"
    assert result.source["tool"] == "resolveCreditPlan"

    assert isinstance(numeric_result, CreditPlanResolutionResult)
    assert numeric_result.selection_key == "Sin Comprobantes"
    assert numeric_result.matched_alias in {"20", "20%"}


def test_resolve_credit_plan_rejects_ambiguous_aliases() -> None:
    pipeline = _credit_pipeline(
        selection_catalog={
            "Sin Comprobantes": {"label": "Sin Comprobantes", "aliases": ["20%"]},
            "Nomina": {"label": "Nomina", "aliases": ["20%"]},
        }
    )

    result = resolveCreditPlan(input_text="20", pipeline=pipeline)

    assert isinstance(result, ToolNoDataResult)
    assert "could not resolve" in result.hint


def test_resolve_credit_plan_does_not_consume_plain_seniority_text() -> None:
    pipeline = _credit_pipeline()

    result = resolveCreditPlan(
        input_text="ya llevo 15 anos en lo mismo jaja",
        pipeline=pipeline,
    )

    assert isinstance(result, ToolNoDataResult)
    assert "could not resolve" in result.hint


def test_get_missing_documents_uses_pipeline_rules_and_current_state() -> None:
    pipeline = _credit_pipeline()

    result = getMissingDocuments(
        pipeline=pipeline,
        state={
            "extracted_data": {
                "CREDITO": {"value": "sin_comprobantes_20", "confidence": 1.0, "source_turn": 4},
                "INE_FRENTE": {"value": "ok", "confidence": 1.0, "source_turn": 5},
                "COMPROBANTE_DOMICILIO": {
                    "value": {
                        "status": "rejected",
                        "rejection_reason": {"value": "borroso"},
                    },
                    "confidence": 1.0,
                    "source_turn": 6,
                },
            }
        },
    )

    assert isinstance(result, MissingDocumentsResult)
    assert result.selection_field == "CREDITO"
    assert result.selection_key == "Sin Comprobantes"
    assert [doc.key for doc in result.received] == ["INE_FRENTE"]
    assert [(doc.key, doc.rejection_reason) for doc in result.rejected] == [
        ("COMPROBANTE_DOMICILIO", "borroso")
    ]
    assert [doc.key for doc in result.missing] == ["INE_ATRAS"]
    assert result.complete is False
    assert result.source["tool"] == "getMissingDocuments"


async def test_list_catalog_reads_real_published_catalog_from_postgres() -> None:
    factory = _get_factory()
    session = factory()
    tenant_id = uuid4()
    now = datetime.now(UTC)
    try:
        session.add(
            Tenant(
                id=tenant_id,
                name=f"pytest-facade-{tenant_id}",
                status="active",
                config={"knowledge_pack_version": "2026-05-23"},
            )
        )
        try:
            await session.flush()
        except ConnectionRefusedError:
            pytest.skip("Postgres no disponible en este entorno")
        catalog = Catalog(
            tenant_id=tenant_id,
            name="Catalogo facade pytest",
            vertical="motorcycles",
            currency="MXN",
            status="draft",
            updated_at=now,
        )
        session.add(catalog)
        await session.flush()
        session.add_all(
            [
                CatalogItem(
                    tenant_id=tenant_id,
                    catalog_id=catalog.id,
                    sku="WORK-200",
                    name="Trabajo 200 CC",
                    category="Trabajo",
                    base_price=Decimal("42000.00"),
                    list_price=Decimal("45000.00"),
                    stock_status="available",
                    stock_quantity=4,
                    status="active",
                    attributes_json={"alias_normalizados": ["trabajo 200"]},
                    ai_rules_json={"can_quote": True},
                    tags_json=["trabajo"],
                    updated_at=now,
                ),
                CatalogItem(
                    tenant_id=tenant_id,
                    catalog_id=catalog.id,
                    sku="SPORT-250",
                    name="Sport 250 CC",
                    category="Deportiva",
                    base_price=Decimal("62000.00"),
                    list_price=Decimal("65000.00"),
                    stock_status="available",
                    stock_quantity=2,
                    status="active",
                    attributes_json={"alias_normalizados": ["sport 250"]},
                    ai_rules_json={"can_quote": True},
                    tags_json=["deportiva"],
                    updated_at=now,
                ),
            ]
        )
        await session.flush()
        await publish_authoring_catalog(
            session,
            tenant_id=tenant_id,
            catalog_id=catalog.id,
            actor_user_id=None,
        )
        await session.flush()

        result = await listCatalog(
            session=session,
            tenant_id=tenant_id,
            category="Trabajo",
            limit=10,
        )

        assert isinstance(result, CatalogListResult)
        assert result.total_results == 1
        assert result.models[0].sku == "WORK-200"
        assert result.models[0].name == "Trabajo 200 CC"
        assert result.models[0].category == "Trabajo"
        assert result.models[0].cash_price_mxn == Decimal("42000.00")
        assert result.source["tool"] == "listCatalog"
        assert result.source["catalog_runtime"] == "commercial_catalog_published"
    finally:
        await session.rollback()
        await session.close()


@pytest.mark.parametrize(
    ("selection", "expected_plan", "expected_down_payment"),
    [
        ("1", "Nomina Tarjeta", "10%"),
        ("nomina tarjeta", "Nomina Tarjeta", "10%"),
        ("2", "Nomina Recibos", "15%"),
        ("recibos de nomina", "Nomina Recibos", "15%"),
        ("3", "Pensionados", "10%"),
        ("soy pensionado", "Pensionados", "10%"),
        ("4", "Negocio SAT", "15%"),
        ("tengo negocio registrado en sat", "Negocio SAT", "15%"),
        ("5", "Sin Comprobantes", "20%"),
        ("me pagan por fuera", "Sin Comprobantes", "20%"),
        ("6", "Guardia de Seguridad", "30%"),
        ("guardia de seguridad", "Guardia de Seguridad", "30%"),
    ],
)
def test_credit_plan_matrix_keeps_menu_parser_and_down_payment_in_sync(
    selection: str,
    expected_plan: str,
    expected_down_payment: str,
) -> None:
    pipeline = _credit_pipeline_all_plans()

    result = resolveCreditPlan(input_text=selection, pipeline=pipeline)

    assert isinstance(result, CreditPlanResolutionResult)
    assert result.selection_key == expected_plan
    assert result.down_payment == expected_down_payment
    assert result.field_updates == {
        "CREDITO": expected_plan,
        "ENGANCHE": expected_down_payment,
    }


def test_credit_plan_menu_uses_fixed_commercial_order() -> None:
    pipeline = _credit_pipeline_all_plans()

    menu = build_credit_plan_menu(pipeline)

    assert [(item["display_number"], item["canonical_credit_plan"], item["down_payment"]) for item in menu] == [
        (1, "Nomina Tarjeta", "10%"),
        (2, "Nomina Recibos", "15%"),
        (3, "Pensionados", "10%"),
        (4, "Negocio SAT", "15%"),
        (5, "Sin Comprobantes", "20%"),
        (6, "Guardia de Seguridad", "30%"),
    ]


def _credit_pipeline(
    *,
    selection_catalog: dict[str, dict] | None = None,
) -> PipelineDefinition:
    return PipelineDefinition.model_validate(
        {
            "version": 1,
            "fallback": "ask_clarification",
            "document_requirements_field": "CREDITO",
            "document_requirements": {
                "Sin Comprobantes": [
                    "INE_FRENTE",
                    "COMPROBANTE_DOMICILIO",
                    "INE_ATRAS",
                ],
                "Nomina": ["INE_FRENTE"],
            },
            "selection_catalog": selection_catalog
            or {
                "Sin Comprobantes": {
                    "label": "Sin Comprobantes",
                    "aliases": [
                        "por fuera",
                        "me pagan por fuera",
                        "20%",
                        "sin_comprobantes_20",
                    ],
                },
                "Nomina": {
                    "label": "Nomina",
                    "aliases": ["recibo nomina", "5%"],
                },
            },
            "documents_catalog": [
                {
                    "key": "INE_FRENTE",
                    "label": "INE frente",
                    "hint": "Foto legible del frente.",
                },
                {
                    "key": "INE_ATRAS",
                    "label": "INE atras",
                    "hint": "Foto legible del reverso.",
                },
                {
                    "key": "COMPROBANTE_DOMICILIO",
                    "label": "Comprobante de domicilio",
                    "hint": "Menor a 2 meses.",
                },
            ],
            "stages": [{"id": "nuevo", "actions_allowed": ["ask_field"]}],
        }
    )


def _credit_pipeline_all_plans() -> PipelineDefinition:
    return PipelineDefinition.model_validate(
        {
            "version": 1,
            "fallback": "ask_clarification",
            "document_requirements_field": "CREDITO",
            "document_requirements": {
                "Nomina Tarjeta": ["INE_FRENTE", "INE_ATRAS", "COMPROBANTE_DOMICILIO"],
                "Nomina Recibos": ["INE_FRENTE", "INE_ATRAS", "COMPROBANTE_DOMICILIO"],
                "Pensionados": ["INE_FRENTE", "INE_ATRAS", "COMPROBANTE_DOMICILIO"],
                "Negocio SAT": ["INE_FRENTE", "INE_ATRAS", "COMPROBANTE_DOMICILIO"],
                "Sin Comprobantes": ["INE_FRENTE", "INE_ATRAS", "COMPROBANTE_DOMICILIO"],
                "Guardia de Seguridad": ["INE_FRENTE", "INE_ATRAS", "COMPROBANTE_DOMICILIO"],
            },
            "selection_catalog": {
                "Nomina Tarjeta": {
                    "label": "Nomina Tarjeta",
                    "aliases": ["me depositan nomina en tarjeta"],
                    "field_updates": {"CREDITO": "Nomina Tarjeta", "ENGANCHE": "10%"},
                },
                "Nomina Recibos": {
                    "label": "Nomina Recibos",
                    "aliases": ["me pagan con recibos de nomina"],
                    "field_updates": {"CREDITO": "Nomina Recibos", "ENGANCHE": "15%"},
                },
                "Pensionados": {
                    "label": "Pensionados",
                    "aliases": ["soy pensionado"],
                    "field_updates": {"CREDITO": "Pensionados", "ENGANCHE": "10%"},
                },
                "Negocio SAT": {
                    "label": "Negocio SAT",
                    "aliases": ["tengo negocio registrado en sat"],
                    "field_updates": {"CREDITO": "Negocio SAT", "ENGANCHE": "15%"},
                },
                "Sin Comprobantes": {
                    "label": "Sin Comprobantes",
                    "aliases": ["me pagan por fuera"],
                    "field_updates": {"CREDITO": "Sin Comprobantes", "ENGANCHE": "20%"},
                },
                "Guardia de Seguridad": {
                    "label": "Guardia de Seguridad",
                    "aliases": ["soy guardia de seguridad"],
                    "field_updates": {"CREDITO": "Guardia de Seguridad", "ENGANCHE": "30%"},
                },
            },
            "documents_catalog": [
                {"key": "INE_FRENTE", "label": "INE frente"},
                {"key": "INE_ATRAS", "label": "INE atras"},
                {"key": "COMPROBANTE_DOMICILIO", "label": "Comprobante de domicilio"},
            ],
            "stages": [{"id": "nuevo", "actions_allowed": ["ask_field"]}],
        }
    )
