from __future__ import annotations

# ruff: noqa: E402,E501,I001

import asyncio
import json
import sys
from pathlib import Path
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

ROOT = Path(__file__).resolve().parents[1]
CORE_ROOT = ROOT / "core"
if str(CORE_ROOT) not in sys.path:
    sys.path.insert(0, str(CORE_ROOT))

from atendia.config import get_settings

TENANT_ID = UUID("6ad78236-1fc9-467a-858d-90d248d57ee5")
AGENT_ID = "ef541266-376c-4f77-92bb-6087133d674e"


STRUCTURED_RELIABILITY = {
    "field_update_rules": [
        {
            "id": "income_nomina",
            "field_key": "income_type",
            "kind": "term_value",
            "any_terms": ["nomina", "nómina", "me depositan", "tarjeta"],
            "value": "Nomina",
            "confidence": 0.92,
            "reason": "Customer explicitly described payroll/card income.",
        },
        {
            "id": "credito_nomina",
            "field_key": "CREDITO",
            "kind": "term_value",
            "any_terms": ["nomina", "nómina", "me depositan", "tarjeta"],
            "value": "Nomina",
            "confidence": 0.9,
            "reason": "Customer explicitly described payroll/card income.",
        },
        {
            "id": "income_sin_comprobantes",
            "field_key": "income_type",
            "kind": "term_value",
            "any_terms": ["efectivo", "por fuera", "sin comprobantes"],
            "value": "Sin Comprobantes",
            "confidence": 0.92,
            "reason": "Customer explicitly described informal income.",
        },
        {
            "id": "credito_sin_comprobantes",
            "field_key": "CREDITO",
            "kind": "term_value",
            "any_terms": ["efectivo", "por fuera", "sin comprobantes"],
            "value": "Sin Comprobantes",
            "confidence": 0.9,
            "reason": "Customer explicitly described informal income.",
        },
        {
            "id": "income_pensionado",
            "field_key": "income_type",
            "kind": "term_value",
            "any_terms": ["pensionado", "pensionada", "pensión", "pension"],
            "value": "Pensionado",
            "confidence": 0.92,
            "reason": "Customer explicitly said they are pensioned.",
        },
        {
            "id": "credito_pensionado",
            "field_key": "CREDITO",
            "kind": "term_value",
            "any_terms": ["pensionado", "pensionada", "pensión", "pension"],
            "value": "Pensionado",
            "confidence": 0.9,
            "reason": "Customer explicitly said they are pensioned.",
        },
        {
            "id": "income_guardia",
            "field_key": "income_type",
            "kind": "term_value",
            "any_terms": ["guardia", "seguridad"],
            "value": "Guardia de Seguridad",
            "confidence": 0.92,
            "reason": "Customer explicitly said they work in security.",
        },
        {
            "id": "credito_guardia",
            "field_key": "CREDITO",
            "kind": "term_value",
            "any_terms": ["guardia", "seguridad"],
            "value": "Guardia de Seguridad",
            "confidence": 0.9,
            "reason": "Customer explicitly said they work in security.",
        },
        {
            "id": "income_negocio_sat",
            "field_key": "income_type",
            "kind": "term_value",
            "all_terms": ["sat"],
            "any_terms": ["negocio", "sat"],
            "value": "Negocio SAT",
            "confidence": 0.9,
            "reason": "Customer explicitly mentioned SAT business income.",
        },
        {
            "id": "down_payment",
            "field_key": "ENGANCHE",
            "kind": "money_amount",
            "any_terms": ["enganche", "de enganche", "tengo"],
            "context_terms": ["credito", "crédito", "enganche", "cotizar"],
            "confidence": 0.9,
            "reason": "Customer explicitly provided down payment amount.",
        },
        {
            "id": "buro_status",
            "field_key": "buro_status",
            "kind": "term_value",
            "any_terms": ["buro", "buró"],
            "value": "en_buro",
            "confidence": 0.9,
            "reason": "Customer explicitly mentioned credit bureau.",
        },
        {
            "id": "ine_frente",
            "field_key": "INE_FRENTE",
            "kind": "term_value",
            "any_terms": [
                "ya mande mi ine",
                "ya mandé mi ine",
                "mande mi ine",
                "mandé mi ine",
                "te mande mi ine",
                "te mandé mi ine",
                "ya envie mi ine",
                "ya envié mi ine",
            ],
            "value": "received_pending_review",
            "confidence": 0.86,
            "reason": "Customer said INE was sent and needs review.",
        },
        {
            "id": "color_preference",
            "field_key": "color_preference",
            "kind": "value_map",
            "values": [
                {"terms": ["roja", "rojo"], "value": "roja"},
                {"terms": ["azul"], "value": "azul"},
                {"terms": ["negra", "negro"], "value": "negra"},
                {"terms": ["blanca", "blanco"], "value": "blanca"},
            ],
            "confidence": 0.85,
            "reason": "Customer explicitly stated preferred color.",
        },
        {
            "id": "preferred_date",
            "field_key": "preferred_appointment_date",
            "kind": "value_map",
            "values": [
                {"terms": ["mañana", "manana"], "value": "manana"},
                {"terms": ["hoy"], "value": "hoy"},
            ],
            "context_terms": ["cita", "agenda", "ir", "visita"],
            "confidence": 0.82,
            "reason": "Customer explicitly stated preferred appointment date.",
        },
    ],
    "lifecycle_rules": [
        {
            "id": "credit_flow",
            "target_stage": "credito",
            "any_terms": [
                "credito",
                "crédito",
                "nomina",
                "nómina",
                "pensionado",
                "guardia",
                "por fuera",
                "buro",
                "buró",
            ],
            "confidence": 0.85,
            "reason": "Customer entered credit qualification flow.",
        },
        {
            "id": "document_incomplete",
            "target_stage": "doc_incompleta",
            "any_terms": [
                "ya mande mi ine",
                "ya mandé mi ine",
                "mande mi ine",
                "mandé mi ine",
                "te mande mi ine",
                "te mandé mi ine",
                "borrosa",
            ],
            "confidence": 0.85,
            "reason": "Customer is in document review flow.",
        },
    ],
    "handoff_terms": ["asesor", "persona", "alguien real", "humano", "hablar con alguien"],
    "handoff_rules": [
        {"id": "seniority_risk", "any_terms": ["un mes", "poco tiempo", "antiguedad"]},
        {"id": "no_job", "any_terms": ["sin trabajo", "no tengo trabajo"]},
        {"id": "third_party_docs", "any_terms": ["de mi mama", "de mi mamá", "estado de cuenta de mi mama"]},
        {"id": "excel_payroll", "any_terms": ["excel"]},
    ],
}


async def main() -> None:
    engine = create_async_engine(get_settings().database_url)
    try:
        async with engine.begin() as conn:
            current = (
                await conn.execute(
                    text("SELECT config FROM tenants WHERE id = :tenant_id"),
                    {"tenant_id": TENANT_ID},
                )
            ).scalar_one()
            config = dict(current or {})
            runtime = dict(config.get("agent_runtime_v2") or {})
            runtime.update(
                {
                    "runtime_v2_enabled": True,
                    "preview_enabled": True,
                    "shadow_mode_enabled": False,
                    "send_enabled": False,
                    "actions_enabled": False,
                    "workflow_events_enabled": False,
                    "model_provider_enabled": True,
                    "rollout_mode": "preview_only",
                    "allowed_agent_ids": [AGENT_ID],
                    "allowed_channel_ids": ["whatsapp", "whatsapp_meta"],
                    "structured_reliability": STRUCTURED_RELIABILITY,
                }
            )
            config["agent_runtime_v2"] = runtime
            await conn.execute(
                text("UPDATE tenants SET config = CAST(:config AS jsonb) WHERE id = :tenant_id"),
                {"tenant_id": TENANT_ID, "config": json.dumps(config)},
            )
    finally:
        await engine.dispose()
    print("structured reliability config applied")


if __name__ == "__main__":
    asyncio.run(main())
