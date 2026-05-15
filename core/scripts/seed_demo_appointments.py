"""Seed ~12 demo appointments distributed across dates and statuses
so the agenda page has visible content out of the box.

Distribution targets (per first tenant):
- 1 in the past, status=completed
- 1 in the past, status=no_show
- 1 in the past, status=cancelled
- 2 today (later in the day), scheduled
- 2 tomorrow, scheduled
- 3 within next 7 days, scheduled
- 2 within next 30 days, scheduled
- 1 conflict pair (same customer, same day, 15 min apart) — exercises the
  conflict-warning path on creation if re-run via API; here we just insert
  both rows to populate the UI

Idempotency: deletes existing demo rows tagged ``[demo]`` in notes before
re-seeding so the script can be re-run safely.
"""

from __future__ import annotations

import asyncio
import random
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from atendia.config import get_settings

SERVICES = [
    "Prueba de manejo Galgo 150",
    "Cotización financiamiento",
    "Entrega de unidad",
    "Revisión post-venta",
    "Firma de contrato",
    "Demostración Rayo 180",
    "Consulta de garantía",
]


async def main() -> None:
    engine = create_async_engine(get_settings().database_url)
    now = datetime.now(UTC)
    async with engine.begin() as conn:
        tenant_id = (
            await conn.execute(text("SELECT id FROM tenants ORDER BY created_at LIMIT 1"))
        ).scalar()
        if tenant_id is None:
            print("[seed_demo_appointments] no tenants — run create_user.py first")
            return

        # Need at least 4 customers to spread appointments across.
        customers = (
            await conn.execute(
                text(
                    "SELECT id FROM customers WHERE tenant_id = :t ORDER BY created_at DESC LIMIT 8"
                ),
                {"t": tenant_id},
            )
        ).all()
        if not customers:
            print("[seed_demo_appointments] no customers — run seed_demo_data.py first")
            return

        cust_ids = [row[0] for row in customers]

        # Wipe previous demo rows.
        await conn.execute(
            text("DELETE FROM appointments WHERE tenant_id = :t AND notes LIKE '[demo]%'"),
            {"t": tenant_id},
        )

        plan = [
            ("completed", now - timedelta(days=3, hours=2)),
            ("no_show", now - timedelta(days=2, hours=5)),
            ("cancelled", now - timedelta(days=1, hours=3)),
            ("scheduled", now + timedelta(hours=3)),
            ("scheduled", now + timedelta(hours=6)),
            ("scheduled", now + timedelta(days=1, hours=10)),
            ("scheduled", now + timedelta(days=1, hours=14)),
            ("scheduled", now + timedelta(days=3, hours=11)),
            ("scheduled", now + timedelta(days=4, hours=16)),
            ("scheduled", now + timedelta(days=6, hours=9)),
            ("scheduled", now + timedelta(days=12, hours=10)),
            ("scheduled", now + timedelta(days=20, hours=15)),
        ]

        for i, (status, when) in enumerate(plan):
            cid = cust_ids[i % len(cust_ids)]
            await conn.execute(
                text(
                    "INSERT INTO appointments (id, tenant_id, customer_id, scheduled_at, "
                    "service, status, notes, created_by_type) "
                    "VALUES (:id, :t, :c, :s, :svc, :st, :n, 'user')"
                ),
                {
                    "id": uuid4(),
                    "t": tenant_id,
                    "c": cid,
                    "s": when,
                    "svc": random.choice(SERVICES),
                    "st": status,
                    "n": f"[demo] cita {i + 1}",
                },
            )

        # Conflict pair: same customer, same window.
        conflict_when = now + timedelta(days=2, hours=10)
        await conn.execute(
            text(
                "INSERT INTO appointments (id, tenant_id, customer_id, scheduled_at, "
                "service, status, notes, created_by_type) "
                "VALUES (:id, :t, :c, :s, :svc, 'scheduled', :n, 'user')"
            ),
            {
                "id": uuid4(),
                "t": tenant_id,
                "c": cust_ids[0],
                "s": conflict_when,
                "svc": "Prueba de manejo Galgo 150",
                "n": "[demo] cita conflicto A",
            },
        )
        await conn.execute(
            text(
                "INSERT INTO appointments (id, tenant_id, customer_id, scheduled_at, "
                "service, status, notes, created_by_type) "
                "VALUES (:id, :t, :c, :s, :svc, 'scheduled', :n, 'user')"
            ),
            {
                "id": uuid4(),
                "t": tenant_id,
                "c": cust_ids[0],
                "s": conflict_when + timedelta(minutes=15),
                "svc": "Cotización financiamiento",
                "n": "[demo] cita conflicto B",
            },
        )

    await engine.dispose()
    print(f"[seed_demo_appointments] inserted {len(plan) + 2} demo appointments")


if __name__ == "__main__":
    asyncio.run(main())
