from __future__ import annotations

import json

from atendia.api.conversations_routes import _customer_field_presentation


def test_simulation_fields_are_debug_grouped() -> None:
    payload = _customer_field_presentation("simulation_run_id", "run-1")

    assert payload["group"] == "debug"
    assert payload["is_debug"] is True
    assert payload["display_order"] >= 200


def test_quote_and_docs_have_structured_render_modes() -> None:
    quote = _customer_field_presentation(
        "Ultima_Cotizacion",
        json.dumps({"status": "ok", "moto": "R4 250 CC"}),
    )
    docs = _customer_field_presentation(
        "Docs_Checklist",
        json.dumps([{"key": "INE", "status": "accepted"}]),
    )

    assert quote["group"] == "tecnicos"
    assert quote["render_mode"] == "quote_card"
    assert quote["render_payload"]["moto"] == "R4 250 CC"
    assert docs["group"] == "tecnicos"
    assert docs["render_mode"] == "document_checklist"
    assert docs["render_payload"][0]["key"] == "INE"
