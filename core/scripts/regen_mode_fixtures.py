"""Generate all mode snapshot fixtures (Phase 3c.2 / T17).

Run once after MODE_PROMPTS or SYSTEM_PROMPT_TEMPLATE changes:

    PYTHONIOENCODING=utf-8 PYTHONPATH=. uv run python scripts/regen_mode_fixtures.py

The 13 fixtures land in tests/fixtures/composer/mode_*.txt and back the
parametrized byte-equality snapshot tests in test_composer_prompts.py.
"""
from pathlib import Path

from atendia.contracts.flow_mode import FlowMode
from atendia.contracts.tone import Tone
from atendia.runner.composer_prompts import build_composer_prompt
from atendia.runner.composer_protocol import ComposerInput

_DINAMO_TONE = Tone(
    register="informal_mexicano", use_emojis="sparingly",
    max_words_per_message=40, bot_name="Dinamo",
    forbidden_phrases=["estimado cliente", "le saluda atentamente"],
    signature_phrases=["¡qué onda!", "te paso"],
)
_BRAND = {
    "address": "Benito Juárez 801, Centro Monterrey",
    "approval_time_hours": "24",
    "buro_max_amount": "$50 mil",
    "catalog_url": "https://dinamomotos.com/catalogo.html",
    "delivery_time_days": "3-7",
    "human_agent_name": "Francisco",
    "post_completion_form": "https://forms.gle/U1MEueL63vgftiuZ8",
}
_FIX_DIR = Path("tests/fixtures/composer")


def _write(name: str, msgs: list[dict[str, str]]) -> None:
    out = _FIX_DIR / f"{name}.txt"
    out.write_text(msgs[0]["content"], encoding="utf-8", newline="")
    print(f"wrote {out} ({len(msgs[0]['content'])} chars)")


def main() -> None:
    # ---- PLAN MODE — 3 fixtures ----------------------------------------
    _write("mode_PLAN_state_initial",
        build_composer_prompt(ComposerInput(
            action="micro_cotizacion", flow_mode=FlowMode.PLAN,
            current_stage="plan", turn_number=1,
            extracted_data={}, tone=_DINAMO_TONE, brand_facts=_BRAND,
        )))
    _write("mode_PLAN_state_antiguedad_set",
        build_composer_prompt(ComposerInput(
            action="ask_tipo_credito", flow_mode=FlowMode.PLAN,
            current_stage="plan", turn_number=2,
            extracted_data={"antigüedad_meses": "24"},
            tone=_DINAMO_TONE, brand_facts=_BRAND,
        )))
    _write("mode_PLAN_state_plan_assigned",
        build_composer_prompt(ComposerInput(
            action="ask_doc_ine", flow_mode=FlowMode.PLAN,
            current_stage="plan", turn_number=4,
            extracted_data={
                "antigüedad_meses": "24",
                "tipo_credito": "Nómina Tarjeta",
                "plan_credito": "10%",
            },
            tone=_DINAMO_TONE, brand_facts=_BRAND,
        )))

    # ---- SALES MODE — 3 fixtures ---------------------------------------
    _write("mode_SALES_state_quote_ok",
        build_composer_prompt(ComposerInput(
            action="quote", flow_mode=FlowMode.SALES,
            current_stage="sales", turn_number=5,
            action_payload={
                "status": "ok",
                "sku": "adventure-elite-150-cc",
                "name": "Adventure Elite 150 CC",
                "category": "Motoneta",
                "price_lista_mxn": "31395",
                "price_contado_mxn": "29900",
                "planes_credito": {"plan_10": {"enganche": 3140,
                                                "pago_quincenal": 1247,
                                                "quincenas": 72}},
                "ficha_tecnica": {"motor_cc": 150},
            },
            extracted_data={"plan_credito": "10%", "modelo_moto": "Adventure"},
            tone=_DINAMO_TONE, brand_facts=_BRAND,
        )))
    _write("mode_SALES_state_no_data",
        build_composer_prompt(ComposerInput(
            action="quote", flow_mode=FlowMode.SALES,
            current_stage="sales", turn_number=5,
            action_payload={"status": "no_data",
                            "hint": "no catalog match for 'lambretta'"},
            extracted_data={"plan_credito": "10%"},
            tone=_DINAMO_TONE, brand_facts=_BRAND,
        )))
    _write("mode_SALES_state_objection_caro",
        build_composer_prompt(ComposerInput(
            action="quote", flow_mode=FlowMode.SALES,
            current_stage="sales", turn_number=6,
            action_payload={"status": "objection", "type": "caro"},
            extracted_data={"plan_credito": "10%"},
            tone=_DINAMO_TONE, brand_facts=_BRAND,
        )))

    # ---- DOC MODE — 3 fixtures -----------------------------------------
    _write("mode_DOC_state_match",
        build_composer_prompt(ComposerInput(
            action="confirm_doc", flow_mode=FlowMode.DOC,
            current_stage="doc", turn_number=7,
            action_payload={
                "vision_result": {"category": "ine", "confidence": 0.95,
                                  "metadata": {"ambos_lados": True, "legible": True}},
                "expected_doc": "ine",
                "pending_after": ["comprobante", "estados_de_cuenta", "nomina"],
            },
            extracted_data={"plan_credito": "10%", "modelo_moto": "Adventure"},
            tone=_DINAMO_TONE, brand_facts=_BRAND,
        )))
    _write("mode_DOC_state_unrelated_image",
        build_composer_prompt(ComposerInput(
            action="reject_unrelated", flow_mode=FlowMode.DOC,
            current_stage="doc", turn_number=7,
            action_payload={
                "vision_result": {"category": "moto", "confidence": 0.92,
                                  "metadata": {"modelo": "Adventure 150"}},
                "expected_doc": "ine",
                "pending_after": [],
            },
            extracted_data={"plan_credito": "10%"},
            tone=_DINAMO_TONE, brand_facts=_BRAND,
        )))
    _write("mode_DOC_state_papeleria_completa",
        build_composer_prompt(ComposerInput(
            action="papeleria_completa", flow_mode=FlowMode.DOC,
            current_stage="doc", turn_number=10,
            action_payload={
                "vision_result": {"category": "recibo_nomina", "confidence": 0.93,
                                  "metadata": {"fecha_iso": "2026-04-30"}},
                "expected_doc": "nomina",
                "pending_after": [],
            },
            extracted_data={
                "plan_credito": "10%", "modelo_moto": "Adventure",
                "docs_ine": "true", "docs_comprobante": "true",
                "docs_estados_de_cuenta": "true",
            },
            tone=_DINAMO_TONE, brand_facts=_BRAND,
        )))

    # ---- OBSTACLE / RETENTION / SUPPORT --------------------------------
    _write("mode_OBSTACLE_state_initial",
        build_composer_prompt(ComposerInput(
            action="address_obstacle", flow_mode=FlowMode.OBSTACLE,
            current_stage="plan", turn_number=8,
            extracted_data={"plan_credito": "10%"},
            tone=_DINAMO_TONE, brand_facts={},
        )))
    _write("mode_RETENTION_state_initial",
        build_composer_prompt(ComposerInput(
            action="retention_pitch", flow_mode=FlowMode.RETENTION,
            current_stage="sales", turn_number=6,
            extracted_data={"plan_credito": "10%", "modelo_moto": "Adventure"},
            tone=_DINAMO_TONE, brand_facts={},
        )))
    _write("mode_SUPPORT_state_buro_question",
        build_composer_prompt(ComposerInput(
            action="explain_topic", flow_mode=FlowMode.SUPPORT,
            current_stage="plan", turn_number=2,
            action_payload={"status": "no_data", "hint": "no FAQ match"},
            extracted_data={},
            tone=_DINAMO_TONE, brand_facts=_BRAND,
        )))
    _write("mode_SUPPORT_state_faq_match",
        build_composer_prompt(ComposerInput(
            action="lookup_faq", flow_mode=FlowMode.SUPPORT,
            current_stage="plan", turn_number=2,
            action_payload={
                "matches": [{
                    "pregunta": "¿Cuál es el tiempo de aprobación?",
                    "respuesta": "24 horas con documentación completa.",
                    "score": 0.93,
                }],
            },
            extracted_data={},
            tone=_DINAMO_TONE, brand_facts=_BRAND,
        )))


if __name__ == "__main__":
    main()
