from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from atendia.tools.book_appointment import BookAppointmentTool


@pytest.mark.asyncio
async def test_book_appointment_returns_canned_booking(db_session):
    tid = (await db_session.execute(
        text("INSERT INTO tenants (name) VALUES ('test_t32_book') RETURNING id")
    )).scalar()
    cid = (await db_session.execute(
        text("INSERT INTO customers (tenant_id, phone_e164) VALUES (:t, '+5215555550032') RETURNING id"),
        {"t": tid},
    )).scalar()
    await db_session.commit()

    slot = datetime.now(timezone.utc) + timedelta(days=1)
    tool = BookAppointmentTool()
    result = await tool.run(
        db_session,
        tenant_id=tid,
        customer_id=cid,
        slot=slot,
    )
    assert "booking_id" in result
    assert result["status"] == "confirmed"
    assert result["slot"] == slot.isoformat()

    await db_session.execute(text("DELETE FROM tenants WHERE id = :tid"), {"tid": tid})
    await db_session.commit()
