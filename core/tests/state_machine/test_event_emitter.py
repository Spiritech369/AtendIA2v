import pytest
from sqlalchemy import text

from atendia.contracts.event import EventType
from atendia.state_machine.event_emitter import EventEmitter


@pytest.mark.asyncio
async def test_emit_persists_event(db_session):
    res = await db_session.execute(
        text("INSERT INTO tenants (name) VALUES ('test_emitter') RETURNING id")
    )
    tenant_id = res.scalar()
    res2 = await db_session.execute(
        text(
            "INSERT INTO customers (tenant_id, phone_e164) VALUES (:tid, '+5215555555555') RETURNING id"
        ),
        {"tid": tenant_id},
    )
    customer_id = res2.scalar()
    res3 = await db_session.execute(
        text("INSERT INTO conversations (tenant_id, customer_id) VALUES (:tid, :cid) RETURNING id"),
        {"tid": tenant_id, "cid": customer_id},
    )
    conversation_id = res3.scalar()
    await db_session.commit()

    emitter = EventEmitter(db_session)
    await emitter.emit(
        conversation_id=conversation_id,
        tenant_id=tenant_id,
        event_type=EventType.STAGE_ENTERED,
        payload={"stage": "qualify"},
    )
    await db_session.commit()

    res4 = await db_session.execute(
        text("SELECT type, payload FROM events WHERE conversation_id = :cid"),
        {"cid": conversation_id},
    )
    rows = res4.fetchall()
    assert len(rows) == 1
    assert rows[0][0] == "stage_entered"
    assert rows[0][1] == {"stage": "qualify"}

    await db_session.execute(text("DELETE FROM tenants WHERE id = :tid"), {"tid": tenant_id})
    await db_session.commit()
