from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from atendia.tools.followup import ScheduleFollowupTool


@pytest.mark.asyncio
async def test_schedule_followup_creates_pending_row(db_session):
    tid = (
        await db_session.execute(
            text("INSERT INTO tenants (name) VALUES ('test_t33_fu') RETURNING id")
        )
    ).scalar()
    cid = (
        await db_session.execute(
            text(
                "INSERT INTO customers (tenant_id, phone_e164) VALUES (:t, '+5215555550034') RETURNING id"
            ),
            {"t": tid},
        )
    ).scalar()
    conv_id = (
        await db_session.execute(
            text("INSERT INTO conversations (tenant_id, customer_id) VALUES (:t, :c) RETURNING id"),
            {"t": tid, "c": cid},
        )
    ).scalar()
    await db_session.commit()

    when = datetime.now(timezone.utc) + timedelta(hours=6)
    tool = ScheduleFollowupTool()
    result = await tool.run(
        db_session,
        tenant_id=tid,
        conversation_id=conv_id,
        when=when,
    )
    await db_session.commit()

    assert "followup_id" in result
    assert result["status"] == "pending"

    rows = (
        await db_session.execute(
            text("SELECT status, attempts FROM followups_scheduled WHERE conversation_id = :c"),
            {"c": conv_id},
        )
    ).fetchall()
    assert len(rows) == 1
    assert rows[0][0] == "pending"
    assert rows[0][1] == 0

    await db_session.execute(text("DELETE FROM tenants WHERE id = :tid"), {"tid": tid})
    await db_session.commit()
