import pytest
from sqlalchemy import text

from atendia.tools.lookup_faq import LookupFAQTool


@pytest.mark.asyncio
async def test_lookup_faq_matches_question(db_session):
    tid = (await db_session.execute(
        text("INSERT INTO tenants (name) VALUES ('test_t32_faq') RETURNING id")
    )).scalar()
    await db_session.execute(
        text("INSERT INTO tenant_faqs (tenant_id, question, answer) "
             "VALUES (:t, '¿Cuánto cuesta el envío?', 'Gratis en pedidos +$500')"),
        {"t": tid},
    )
    await db_session.execute(
        text("INSERT INTO tenant_faqs (tenant_id, question, answer) "
             "VALUES (:t, '¿Cuál es el horario?', 'Lunes a viernes 9-18')"),
        {"t": tid},
    )
    await db_session.commit()

    tool = LookupFAQTool()
    result = await tool.run(db_session, tenant_id=tid, question="envío")
    assert "matches" in result
    assert len(result["matches"]) == 1
    assert "Gratis" in result["matches"][0]["answer"]

    await db_session.execute(text("DELETE FROM tenants WHERE id = :tid"), {"tid": tid})
    await db_session.commit()


@pytest.mark.asyncio
async def test_lookup_faq_returns_empty_when_no_match(db_session):
    tid = (await db_session.execute(
        text("INSERT INTO tenants (name) VALUES ('test_t32_faq_empty') RETURNING id")
    )).scalar()
    await db_session.commit()

    tool = LookupFAQTool()
    result = await tool.run(db_session, tenant_id=tid, question="cualquier cosa")
    assert result["matches"] == []

    await db_session.execute(text("DELETE FROM tenants WHERE id = :tid"), {"tid": tid})
    await db_session.commit()
