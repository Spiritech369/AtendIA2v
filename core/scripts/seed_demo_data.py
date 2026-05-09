"""Seed rich demo data into the existing 'Dinamo Motos NL' tenant.

Idempotent-ish — uses ON CONFLICT DO NOTHING for FAQs / catalog / field
definitions. Re-running won't duplicate those, but it WILL add more
messages / notes / appointments each time.
"""
from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from atendia.config import get_settings


async def main() -> None:
    e = create_async_engine(get_settings().database_url)
    async with e.begin() as c:
        tid = (
            await c.execute(
                text("SELECT id FROM tenants WHERE name='Dinamo Motos NL' LIMIT 1")
            )
        ).scalar()
        uid = (
            await c.execute(
                text(
                    "SELECT id FROM tenant_users "
                    "WHERE email='admin@dinamomotos.com' LIMIT 1"
                )
            )
        ).scalar()
        if not tid:
            print("Tenant not found. Re-seed the admin account first.")
            return

        # ── FAQs ─────────────────────────────────────────────────────
        for q, a in [
            (
                "¿Cuánto tiempo dura el trámite?",
                "Una vez completados los documentos, la entrega es en 48-72 horas hábiles.",
            ),
            (
                "¿Necesito aval?",
                "Solo si tu antigüedad es menor a 6 meses o tu ingreso comprobable es <$8,000 mensuales.",
            ),
            (
                "¿Aceptan pago con tarjeta?",
                "Sí, aceptamos crédito y débito. Recargo del 3.5% en crédito sin promociones.",
            ),
            (
                "¿Qué cobertura incluye el seguro?",
                "Cobertura amplia: daños materiales, robo total, RC y gastos médicos. 12 meses incluidos.",
            ),
        ]:
            await c.execute(
                text(
                    "INSERT INTO tenant_faqs (tenant_id, question, answer) "
                    "VALUES (:t, :q, :a) ON CONFLICT DO NOTHING"
                ),
                {"t": tid, "q": q, "a": a},
            )

        # ── Catalog ──────────────────────────────────────────────────
        for sku, name, attrs in [
            ("GALGO150", "Galgo 150", {"cilindrada": "150cc", "precio_contado": 38900, "mensualidad_36m": 1450}),
            ("GALGO250", "Galgo 250", {"cilindrada": "250cc", "precio_contado": 52400, "mensualidad_36m": 1980}),
            ("RAYO180", "Rayo 180", {"cilindrada": "180cc", "precio_contado": 41200, "mensualidad_36m": 1560}),
            ("TURBO400", "Turbo 400", {"cilindrada": "400cc", "precio_contado": 78900, "mensualidad_36m": 2980}),
        ]:
            await c.execute(
                text(
                    "INSERT INTO tenant_catalogs "
                    "(tenant_id, sku, name, attrs, category) "
                    "VALUES (:t, :s, :n, :a, 'motos') ON CONFLICT DO NOTHING"
                ),
                {"t": tid, "s": sku, "n": name, "a": json.dumps(attrs)},
            )

        # ── Custom field definitions ─────────────────────────────────
        defs = [
            ("plan_credito", "Plan de crédito", "select", {"choices": ["12m", "24m", "36m", "48m"]}),
            ("antiguedad_meses", "Antigüedad laboral (meses)", "number", None),
            ("docs_ine", "Tiene INE", "checkbox", None),
            ("docs_comprobante", "Tiene comprobante de domicilio", "checkbox", None),
            (
                "preferencias",
                "Preferencias",
                "multiselect",
                {"choices": ["contado", "financiamiento", "seguro", "garantía extendida"]},
            ),
        ]
        for k, lbl, ft, opts in defs:
            # Some tables have ORM-level UUID defaults but no DB-level
            # ``gen_random_uuid()`` server_default — generate in Python
            # so raw SQL inserts work.
            await c.execute(
                text(
                    "INSERT INTO customer_field_definitions "
                    "(id, tenant_id, key, label, field_type, field_options, ordering) "
                    "VALUES (gen_random_uuid(), :t, :k, :l, :f, :o, 0) "
                    "ON CONFLICT DO NOTHING"
                ),
                {"t": tid, "k": k, "l": lbl, "f": ft, "o": json.dumps(opts) if opts else None},
            )

        # ── Customer references ─────────────────────────────────────
        cust1 = (
            await c.execute(
                text("SELECT id FROM customers WHERE tenant_id=:t AND name='Juan Pérez'"),
                {"t": tid},
            )
        ).scalar()
        cust2 = (
            await c.execute(
                text("SELECT id FROM customers WHERE tenant_id=:t AND name='María López'"),
                {"t": tid},
            )
        ).scalar()

        # Field values for Juan
        if cust1:
            for k, v in [
                ("plan_credito", "36m"),
                ("antiguedad_meses", "14"),
                ("docs_ine", "true"),
                ("docs_comprobante", "false"),
                ("preferencias", '["financiamiento","seguro"]'),
            ]:
                defn_id = (
                    await c.execute(
                        text(
                            "SELECT id FROM customer_field_definitions "
                            "WHERE tenant_id=:t AND key=:k"
                        ),
                        {"t": tid, "k": k},
                    )
                ).scalar()
                if defn_id:
                    await c.execute(
                        text(
                            "INSERT INTO customer_field_values "
                            "(customer_id, field_definition_id, value) "
                            "VALUES (:c, :d, :v) ON CONFLICT DO NOTHING"
                        ),
                        {"c": cust1, "d": defn_id, "v": v},
                    )

        # Juan: extracted_data + extra messages + notes
        if cust1:
            conv1 = (
                await c.execute(
                    text("SELECT id FROM conversations WHERE customer_id=:c"),
                    {"c": cust1},
                )
            ).scalar()
            await c.execute(
                text(
                    "UPDATE conversation_state SET extracted_data = :d "
                    "WHERE conversation_id = :c"
                ),
                {
                    "c": conv1,
                    "d": json.dumps(
                        {
                            "plan_credito": {"value": "36m", "confidence": 0.95, "source_turn": 2},
                            "modelo_moto": {"value": "Galgo 150", "confidence": 0.9, "source_turn": 1},
                            "docs_ine": True,
                            "docs_comprobante": False,
                        }
                    ),
                },
            )
            for i, (direction, txt) in enumerate([
                ("outbound", "Tenemos Galgo 150 a $38,900 al contado o $1,450 al mes a 36 meses. ¿Te interesa?"),
                ("inbound", "Sí, ¿qué necesito para sacarlo a crédito?"),
                ("outbound", "INE, comprobante de domicilio reciente y comprobante de ingresos. ¿Los tienes a la mano?"),
                ("inbound", "INE sí. Comprobante reciente no, el último es de hace 4 meses."),
                ("outbound", "Necesitamos uno de los últimos 3 meses. ¿Puedes pasar a la sucursal con un recibo de luz/agua nuevo?"),
                ("inbound", "Va, paso este sábado. ¿Necesito cita?"),
            ]):
                await c.execute(
                    text(
                        "INSERT INTO messages "
                        "(conversation_id, tenant_id, direction, text, sent_at) "
                        "VALUES (:c, :t, :d, :m, now() + make_interval(secs => :i))"
                    ),
                    {"c": conv1, "t": tid, "d": direction, "m": txt, "i": (i + 2) * 60},
                )
            await c.execute(
                text(
                    "INSERT INTO customer_notes "
                    "(id, customer_id, tenant_id, author_user_id, source, content, pinned) "
                    "VALUES (gen_random_uuid(), :c, :t, :u, 'manual', :n, true)"
                ),
                {
                    "c": cust1,
                    "t": tid,
                    "u": uid,
                    "n": "Cliente muy interesado en Galgo 150. Falta solo comprobante reciente.",
                },
            )
            await c.execute(
                text(
                    "INSERT INTO customer_notes "
                    "(id, customer_id, tenant_id, author_user_id, source, content, pinned) "
                    "VALUES (gen_random_uuid(), :c, :t, NULL, 'ai_summary', :n, false)"
                ),
                {
                    "c": cust1,
                    "t": tid,
                    "n": (
                        "Resumen AI\n\nCliente Juan está cotizando Galgo 150 a 36 meses. "
                        "Tiene INE pero le falta comprobante reciente. Va a pasar a "
                        "sucursal este sábado.\n\nhigh_water:placeholder\nmode:llm"
                    ),
                },
            )

        # María: handoff abierto
        if cust2:
            conv2 = (
                await c.execute(
                    text("SELECT id FROM conversations WHERE customer_id=:c"),
                    {"c": cust2},
                )
            ).scalar()
            await c.execute(
                text(
                    "INSERT INTO human_handoffs "
                    "(id, tenant_id, conversation_id, reason, status, payload) "
                    "VALUES (gen_random_uuid(), :t, :c, "
                    "'OBSTACLE_NO_SOLUTION', 'open', :p)"
                ),
                {
                    "t": tid,
                    "c": conv2,
                    "p": json.dumps(
                        {
                            "reason": "OBSTACLE_NO_SOLUTION",
                            "last_inbound_text": "Quiero un descuento del 30%",
                            "suggested_next_action": "Ofrecer plan a 48 meses con enganche menor",
                        }
                    ),
                },
            )

        # Default agent
        await c.execute(
            text(
                "INSERT INTO agents "
                "(id, tenant_id, name, role, goal, style, tone, "
                " max_sentences, is_default, active_intents) "
                "VALUES (gen_random_uuid(), :t, 'Asesor Galgo', 'sales', "
                "'Cerrar la venta de moto Galgo según interés del cliente', "
                "'asesor comercial mexicano amable', 'amigable', 5, true, :i)"
            ),
            {"t": tid, "i": json.dumps(["ASK_INFO", "ASK_PRICE", "BUY", "SCHEDULE"])},
        )

        # Appointment
        if cust1 and conv1:
            await c.execute(
                text(
                    "INSERT INTO appointments "
                    "(id, tenant_id, customer_id, conversation_id, "
                    " scheduled_at, service, status, created_by_id, created_by_type) "
                    "VALUES (gen_random_uuid(), :t, :c, :v, :s, "
                    "'Prueba de manejo Galgo 150', 'scheduled', :u, 'user')"
                ),
                {
                    "t": tid,
                    "c": cust1,
                    "v": conv1,
                    "s": datetime.now(UTC) + timedelta(days=2),
                    "u": uid,
                },
            )

    print("Demo data seeded:")
    print("  4 FAQs")
    print("  4 catalog items (Galgos + Rayo + Turbo)")
    print("  5 customer field definitions (incluye multiselect)")
    print("  Juan: 5 field values + extracted_data + 8 mensajes + 2 notas (1 AI summary)")
    print("  María: handoff abierto")
    print("  1 agente IA default (Asesor Galgo)")
    print("  1 cita agendada (en 2 días)")
    await e.dispose()


if __name__ == "__main__":
    asyncio.run(main())
