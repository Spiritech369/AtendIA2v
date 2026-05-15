import pytest
from sqlalchemy import text

from atendia.tools.escalate import EscalateToHumanTool


@pytest.mark.asyncio
async def test_escalate_creates_handoff_row(db_session):
    tid = (
        await db_session.execute(
            text("INSERT INTO tenants (name) VALUES ('test_t33_esc') RETURNING id")
        )
    ).scalar()
    cid = (
        await db_session.execute(
            text(
                "INSERT INTO customers (tenant_id, phone_e164) VALUES (:t, '+5215555550033') RETURNING id"
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

    tool = EscalateToHumanTool()
    result = await tool.run(
        db_session,
        tenant_id=tid,
        conversation_id=conv_id,
        reason="sentiment negative for 4 turns",
    )
    await db_session.commit()

    assert "handoff_id" in result
    assert result["status"] == "open"

    rows = (
        await db_session.execute(
            text("SELECT reason, status FROM human_handoffs WHERE conversation_id = :c"),
            {"c": conv_id},
        )
    ).fetchall()
    assert len(rows) == 1
    assert rows[0][0] == "sentiment negative for 4 turns"
    assert rows[0][1] == "open"

    await db_session.execute(text("DELETE FROM tenants WHERE id = :tid"), {"tid": tid})
    await db_session.commit()
