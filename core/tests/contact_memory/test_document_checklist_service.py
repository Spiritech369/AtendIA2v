from __future__ import annotations

from atendia.contact_memory.document_checklist import (
    ACCEPTED,
    MISSING,
    RECEIVED,
    REJECTED,
    DocumentChecklistService,
)

REQUIREMENTS = {
    "Nómina Tarjeta": [
        "INE_AMBOS_LADOS",
        "COMPROBANTE_DOMICILIO",
        "ESTADOS_CUENTA_NOMINA",
        "NOMINA_1_MES_EN_ESTADOS",
    ],
    "Sin Comprobantes": ["INE_AMBOS_LADOS", "COMPROBANTE_DOMICILIO"],
}

CATALOG = [
    {"key": "INE_AMBOS_LADOS", "label": "INE vigente por ambos lados"},
    {"key": "COMPROBANTE_DOMICILIO", "label": "Comprobante de domicilio"},
    {"key": "ESTADOS_CUENTA_NOMINA", "label": "2 estados de cuenta"},
    {"key": "NOMINA_1_MES_EN_ESTADOS", "label": "Nómina reflejada de 1 mes"},
]


def test_builds_plan_aware_checklist_and_missing_documents():
    service = DocumentChecklistService(
        document_requirements=REQUIREMENTS,
        documents_catalog=CATALOG,
    )

    checklist = service.build_document_checklist("Nómina Tarjeta")

    assert [item["key"] for item in checklist] == REQUIREMENTS["Nómina Tarjeta"]
    assert checklist[0]["label"] == "INE vigente por ambos lados"
    assert {item["status"] for item in checklist} == {MISSING}
    assert service.compute_documentos_completos(checklist) is False


def test_marks_received_accepted_rejected_and_computes_complete():
    service = DocumentChecklistService(
        document_requirements=REQUIREMENTS,
        documents_catalog=CATALOG,
    )
    checklist = service.build_document_checklist("Sin Comprobantes")

    checklist = service.mark_document_received(
        checklist,
        "INE_AMBOS_LADOS",
        evidence=["photo-1"],
    )
    assert checklist[0]["status"] == RECEIVED
    assert checklist[0]["evidence"] == ["photo-1"]

    checklist = service.mark_document_accepted(checklist, "INE_AMBOS_LADOS")
    checklist = service.mark_document_rejected(
        checklist,
        "COMPROBANTE_DOMICILIO",
        reason="borroso",
    )
    assert checklist[0]["status"] == ACCEPTED
    assert checklist[1]["status"] == REJECTED
    assert service.compute_missing_documents(checklist) == ["COMPROBANTE_DOMICILIO"]
    assert service.compute_documentos_completos(checklist) is False

    checklist = service.mark_document_accepted(checklist, "COMPROBANTE_DOMICILIO")
    assert service.compute_documentos_completos(checklist) is True


def test_rebuilds_checklist_when_plan_changes_without_losing_shared_docs():
    service = DocumentChecklistService(
        document_requirements=REQUIREMENTS,
        documents_catalog=CATALOG,
    )
    previous = service.build_document_checklist("Sin Comprobantes")
    previous = service.mark_document_accepted(previous, "INE_AMBOS_LADOS")

    rebuilt = service.rebuild_checklist_on_plan_change(
        previous_checklist=previous,
        new_plan_id="Nómina Tarjeta",
    )

    assert [item["key"] for item in rebuilt] == REQUIREMENTS["Nómina Tarjeta"]
    assert rebuilt[0]["status"] == ACCEPTED
    assert rebuilt[2]["status"] == MISSING
