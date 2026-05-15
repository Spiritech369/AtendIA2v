"""Seed ~20 varied conversations across all pipeline stages so the
operator can drag stuff around the kanban and feel the UX.

Distribution targets:
- nuevo: 6
- interesado: 7
- cotizado: 4
- cerrado: 3
- 2 of those go stale (entered the stage > timeout_hours ago)
- 1 ends up in an INVALID stage so the orphan column shows
"""

from __future__ import annotations

import asyncio
import random

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from atendia.config import get_settings

NAMES = [
    "Carlos Mendoza",
    "Ana García",
    "Luis Hernández",
    "Sofía Ramírez",
    "Diego Torres",
    "Valentina Cruz",
    "Mateo Flores",
    "Camila Vargas",
    "Sebastián Rojas",
    "Renata Silva",
    "Emilio Castro",
    "Isabella Núñez",
    "Joaquín Reyes",
    "Lucía Ortega",
    "Andrés Domínguez",
    "Gabriela Soto",
    "Tomás Aguilar",
    "Mariana Cortés",
    "Bruno Salazar",
    "Paula Méndez",
]

INBOUND_OPENERS = [
    "Hola, me interesa una Galgo 150",
    "Buenas, ¿qué precio tiene la Rayo 180?",
    "Buen día, quiero info de motos a crédito",
    "Hola! Vi su anuncio, me interesa",
    "¿Tienen Turbo 400 disponible?",
    "Quiero saber requisitos para crédito",
    "¿Cuánto sale el enganche?",
    "Hola, ¿siguen abiertos hoy?",
]

OUTBOUND_REPLIES = [
    "¡Claro! Tenemos varios modelos. ¿Te interesa contado o crédito?",
    "Te paso opciones: Galgo 150 a $38,900 contado o $1,450/mes a 36 meses.",
    "Para crédito necesitamos INE, comprobante de domicilio reciente y de ingresos.",
    "¿Cuánto tienes pensado dar de enganche?",
    "Perfecto, con eso te alcanza para varios planes. ¿Cuál te interesa?",
    "Te invito a la sucursal para que veas la moto en persona.",
]


async def main() -> None:
    e = create_async_engine(get_settings().database_url)
    async with e.begin() as c:
        tid = (
            await c.execute(text("SELECT id FROM tenants WHERE name='Dinamo Motos NL' LIMIT 1"))
        ).scalar()
        uid = (
            await c.execute(
                text("SELECT id FROM tenant_users WHERE email='admin@dinamomotos.com' LIMIT 1")
            )
        ).scalar()
        if not tid:
            print("Tenant not found. Re-seed admin first.")
            return

        # Stages + how many conversations per stage. 1 of cotizado will be
        # stale (timeout_hours=48, stage_entered_at 60h ago). 1 will be in
        # an orphan stage to demo the rescue UX.
        plan = [
            ("nuevo", 6, 0),
            ("interesado", 7, 0),
            ("cotizado", 4, 0),
            ("cerrado", 3, 0),
        ]
        rng = random.Random(42)
        name_idx = 0

        def next_name() -> str:
            nonlocal name_idx
            name = NAMES[name_idx % len(NAMES)]
            if name_idx >= len(NAMES):
                name = f"{name} {name_idx // len(NAMES) + 1}"
            name_idx += 1
            return name

        for stage, count, _ in plan:
            for _ in range(count):
                name = next_name()
                phone = f"+5215{rng.randint(500000000, 599999999)}"
                cust = (
                    await c.execute(
                        text(
                            "INSERT INTO customers (tenant_id, phone_e164, name) "
                            "VALUES (:t, :p, :n) RETURNING id"
                        ),
                        {"t": tid, "p": phone, "n": name},
                    )
                ).scalar()
                conv = (
                    await c.execute(
                        text(
                            "INSERT INTO conversations "
                            "(tenant_id, customer_id, current_stage, last_activity_at) "
                            "VALUES (:t, :c, :s, now() - make_interval(mins => :m)) "
                            "RETURNING id"
                        ),
                        {
                            "t": tid,
                            "c": cust,
                            "s": stage,
                            "m": rng.randint(5, 600),
                        },
                    )
                ).scalar()
                await c.execute(
                    text(
                        "INSERT INTO conversation_state "
                        "(conversation_id, stage_entered_at) "
                        "VALUES (:c, now() - make_interval(mins => :m))"
                    ),
                    {"c": conv, "m": rng.randint(5, 600)},
                )
                # 2-4 messages
                turns = rng.randint(2, 4)
                for i in range(turns):
                    direction = "inbound" if i % 2 == 0 else "outbound"
                    body = (
                        rng.choice(INBOUND_OPENERS)
                        if direction == "inbound"
                        else rng.choice(OUTBOUND_REPLIES)
                    )
                    await c.execute(
                        text(
                            "INSERT INTO messages "
                            "(conversation_id, tenant_id, direction, text, sent_at) "
                            "VALUES (:c, :t, :d, :m, "
                            "now() - make_interval(mins => :mins))"
                        ),
                        {
                            "c": conv,
                            "t": tid,
                            "d": direction,
                            "m": body,
                            "mins": rng.randint(1, 120),
                        },
                    )

        # 2 explicitly stale: cotizado (timeout=48h), entered 60h ago
        for _ in range(2):
            name = next_name()
            phone = f"+5215{rng.randint(500000000, 599999999)}"
            cust = (
                await c.execute(
                    text(
                        "INSERT INTO customers (tenant_id, phone_e164, name) "
                        "VALUES (:t, :p, :n) RETURNING id"
                    ),
                    {"t": tid, "p": phone, "n": name},
                )
            ).scalar()
            conv = (
                await c.execute(
                    text(
                        "INSERT INTO conversations "
                        "(tenant_id, customer_id, current_stage, last_activity_at) "
                        "VALUES (:t, :c, 'cotizado', now() - interval '60 hours') "
                        "RETURNING id"
                    ),
                    {"t": tid, "c": cust},
                )
            ).scalar()
            await c.execute(
                text(
                    "INSERT INTO conversation_state "
                    "(conversation_id, stage_entered_at) "
                    "VALUES (:c, now() - interval '60 hours')"
                ),
                {"c": conv},
            )
            await c.execute(
                text(
                    "INSERT INTO messages "
                    "(conversation_id, tenant_id, direction, text, sent_at) "
                    "VALUES (:c, :t, 'inbound', :m, now() - interval '61 hours')"
                ),
                {
                    "c": conv,
                    "t": tid,
                    "m": "Quedé de pasar pero no he podido. ¿Sigue disponible?",
                },
            )

        # 1 orphan: stage that doesn't exist in the active pipeline
        name = next_name()
        phone = f"+5215{rng.randint(500000000, 599999999)}"
        cust = (
            await c.execute(
                text(
                    "INSERT INTO customers (tenant_id, phone_e164, name) "
                    "VALUES (:t, :p, :n) RETURNING id"
                ),
                {"t": tid, "p": phone, "n": name},
            )
        ).scalar()
        conv = (
            await c.execute(
                text(
                    "INSERT INTO conversations "
                    "(tenant_id, customer_id, current_stage) "
                    "VALUES (:t, :c, 'cancelado') RETURNING id"
                ),
                {"t": tid, "c": cust},
            )
        ).scalar()
        await c.execute(
            text("INSERT INTO conversation_state (conversation_id) VALUES (:c)"),
            {"c": conv},
        )
        await c.execute(
            text(
                "INSERT INTO messages "
                "(conversation_id, tenant_id, direction, text, sent_at) "
                "VALUES (:c, :t, 'inbound', 'Mejor lo dejamos para más adelante', now())"
            ),
            {"c": conv, "t": tid},
        )

        # Get total counts to print
        rows = (
            await c.execute(
                text(
                    "SELECT current_stage, count(*) AS n FROM conversations "
                    "WHERE tenant_id = :t GROUP BY current_stage ORDER BY current_stage"
                ),
                {"t": tid},
            )
        ).all()

    print("Seeded 23 extra conversations.")
    print("Stage distribution now:")
    for r in rows:
        print(f"  {r.current_stage}: {r.n}")
    print()
    print("Two cotizado entries stale (>48h since stage entry).")
    print("One entry in 'cancelado' will appear in the orphan column.")
    await e.dispose()


if __name__ == "__main__":
    asyncio.run(main())
