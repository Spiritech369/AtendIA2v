"""Coverage for the two CSV streaming endpoints under /api/v1/exports/*.

The endpoints are simple but skipping tests is dangerous because:
- Wrong content-type would block the browser from offering "Save as..."
- Wrong tenant scoping would leak other tenants' messages
- A missing Content-Disposition would surface as raw text in the browser

These tests pin the contract: 200, text/csv content-type, attachment
disposition, header row present, only the requesting tenant's rows
included, and date filters applied when provided.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from atendia.config import get_settings


def _seed_conversation_and_message(
    tenant_id: str,
    sent_at: datetime,
    text_body: str,
    *,
    created_at: datetime | None = None,
    extracted_data: dict | None = None,
) -> str:
    """Insert one customer + conversation + message, return conversation_id.

    Optional ``created_at`` lets a caller back-date the conversation row so that
    the conversation date-range filter can be exercised independently of the
    message date-range filter. Optional ``extracted_data`` lets a caller seed
    the JSONB column on ``conversation_state`` so the CSV writer's pluck of
    the ExtractedField shape is exercised.
    """

    async def _do() -> str:
        import json

        engine = create_async_engine(get_settings().database_url)
        try:
            async with engine.begin() as conn:
                cust_id = (
                    await conn.execute(
                        text(
                            "INSERT INTO customers (tenant_id, phone_e164, name) "
                            "VALUES (:t, :p, :n) RETURNING id"
                        ),
                        {
                            "t": tenant_id,
                            "p": f"+5215{uuid4().hex[:9]}",
                            "n": "Export Test",
                        },
                    )
                ).scalar()
                if created_at is not None:
                    conv_id = (
                        await conn.execute(
                            text(
                                "INSERT INTO conversations "
                                "(tenant_id, customer_id, current_stage, created_at) "
                                "VALUES (:t, :c, 'lead', :ca) RETURNING id"
                            ),
                            {"t": tenant_id, "c": cust_id, "ca": created_at},
                        )
                    ).scalar()
                else:
                    conv_id = (
                        await conn.execute(
                            text(
                                "INSERT INTO conversations "
                                "(tenant_id, customer_id, current_stage) "
                                "VALUES (:t, :c, 'lead') RETURNING id"
                            ),
                            {"t": tenant_id, "c": cust_id},
                        )
                    ).scalar()
                if extracted_data is not None:
                    await conn.execute(
                        text(
                            "INSERT INTO conversation_state "
                            "(conversation_id, extracted_data) "
                            "VALUES (:c, CAST(:d AS jsonb))"
                        ),
                        {"c": conv_id, "d": json.dumps(extracted_data)},
                    )
                await conn.execute(
                    text(
                        "INSERT INTO messages "
                        "(tenant_id, conversation_id, direction, text, sent_at, "
                        " channel_message_id) "
                        "VALUES (:t, :c, 'inbound', :body, :sent_at, :cmid)"
                    ),
                    {
                        "t": tenant_id,
                        "c": conv_id,
                        "body": text_body,
                        "sent_at": sent_at,
                        "cmid": f"test-{uuid4().hex[:10]}",
                    },
                )
                return str(conv_id)
        finally:
            await engine.dispose()

    return asyncio.run(_do())


def test_export_conversations_returns_csv_200(client_tenant_admin) -> None:
    _seed_conversation_and_message(
        client_tenant_admin.tenant_id,
        datetime.now(UTC),
        "hola desde el test",
    )
    resp = client_tenant_admin.get("/api/v1/exports/conversations.csv")
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("text/csv")
    assert "attachment" in resp.headers.get("content-disposition", "")
    assert "atendia-conversations-" in resp.headers["content-disposition"]
    header = resp.text.splitlines()[0]
    assert "conversation_id" in header
    assert "customer_phone" in header
    assert "current_stage" in header


def test_export_conversations_anonymous_is_unauthorized(client) -> None:
    resp = client.get("/api/v1/exports/conversations.csv")
    assert resp.status_code in {401, 403}


def test_export_messages_returns_csv_200(client_tenant_admin) -> None:
    _seed_conversation_and_message(
        client_tenant_admin.tenant_id,
        datetime.now(UTC),
        "este mensaje debe aparecer",
    )
    resp = client_tenant_admin.get("/api/v1/exports/messages.csv")
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("text/csv")
    assert "attachment" in resp.headers.get("content-disposition", "")
    body = resp.text
    header = body.splitlines()[0]
    assert "direction" in header
    assert "text" in header
    assert "este mensaje debe aparecer" in body


def test_export_messages_filters_by_date_range(client_tenant_admin) -> None:
    """The ``from``/``to`` query params must constrain results. Sending an
    ancient window should yield zero data rows even when data exists today."""
    _seed_conversation_and_message(
        client_tenant_admin.tenant_id,
        datetime.now(UTC),
        "mensaje de hoy",
    )
    ancient = (datetime.now(UTC) - timedelta(days=400)).date().isoformat()
    just_before = (datetime.now(UTC) - timedelta(days=399)).date().isoformat()
    resp = client_tenant_admin.get(f"/api/v1/exports/messages.csv?from={ancient}&to={just_before}")
    assert resp.status_code == 200, resp.text
    rows = [line for line in resp.text.splitlines() if line.strip()]
    # Header row only — no data rows for the empty window
    assert len(rows) == 1, f"expected header-only, got: {rows}"


def test_export_messages_does_not_leak_other_tenants(
    client_tenant_admin,
    superadmin_seed,
) -> None:
    """A message belonging to a different tenant must never appear in the
    requesting tenant's export. This is the most damaging possible bug here —
    pin it explicitly."""
    other_tid = superadmin_seed[0]
    _seed_conversation_and_message(
        other_tid,
        datetime.now(UTC),
        "SECRETO_DE_OTRO_TENANT_NO_DEBE_FUGARSE",
    )
    resp = client_tenant_admin.get("/api/v1/exports/messages.csv")
    assert resp.status_code == 200, resp.text
    assert "SECRETO_DE_OTRO_TENANT_NO_DEBE_FUGARSE" not in resp.text


def test_export_messages_anonymous_is_unauthorized(client) -> None:
    """Mirror of the conversations.csv auth test — both endpoints must require
    a session cookie to prevent unauthenticated bulk dumps."""
    resp = client.get("/api/v1/exports/messages.csv")
    assert resp.status_code in {401, 403}


def test_export_conversations_filters_by_date_range(client_tenant_admin) -> None:
    """The ``from``/``to`` query params on conversations.csv must filter by
    ``Conversation.created_at``. Sending an ancient window should yield only
    the header row even when data exists today."""
    _seed_conversation_and_message(
        client_tenant_admin.tenant_id,
        datetime.now(UTC),
        "conversación de hoy",
    )
    ancient = (datetime.now(UTC) - timedelta(days=400)).date().isoformat()
    just_before = (datetime.now(UTC) - timedelta(days=399)).date().isoformat()
    resp = client_tenant_admin.get(
        f"/api/v1/exports/conversations.csv?from={ancient}&to={just_before}"
    )
    assert resp.status_code == 200, resp.text
    rows = [line for line in resp.text.splitlines() if line.strip()]
    assert len(rows) == 1, f"expected header-only, got: {rows}"


def test_export_conversations_does_not_leak_other_tenants(
    client_tenant_admin,
    superadmin_seed,
) -> None:
    """A conversation belonging to a different tenant must never appear in
    the requesting tenant's export. Tenant isolation is enforced via the
    ``Conversation.tenant_id`` filter — pin it explicitly so a future query
    refactor can't silently widen the scope."""
    other_tid = superadmin_seed[0]
    leak_marker = f"+5215leak{uuid4().hex[:6]}"
    _seed_conversation_and_message(
        other_tid,
        datetime.now(UTC),
        f"otro tenant — {leak_marker}",
    )
    resp = client_tenant_admin.get("/api/v1/exports/conversations.csv")
    assert resp.status_code == 200, resp.text
    assert "otro tenant" not in resp.text
    assert leak_marker not in resp.text


def test_export_conversations_unpacks_extracted_field_values(client_tenant_admin) -> None:
    """The CSV emits flat columns (modelo_moto, plan_credito, papeleria_completa)
    by plucking ``.value`` from the ExtractedField dict stored in
    ``conversation_state.extracted_data``. If the writer ever regressed to
    serializing the whole dict, the operator's CSV would show ``{'value':
    'Italika 150z', ...}`` instead of ``Italika 150z`` — pin the unpack."""
    _seed_conversation_and_message(
        client_tenant_admin.tenant_id,
        datetime.now(UTC),
        "test extracted",
        extracted_data={
            "modelo_moto": {"value": "Italika 150z", "confidence": 0.9},
            "plan_credito": {"value": "12 meses", "confidence": 0.8},
            "papeleria_completa": {"value": "true", "confidence": 1.0},
        },
    )
    resp = client_tenant_admin.get("/api/v1/exports/conversations.csv")
    assert resp.status_code == 200, resp.text
    body = resp.text
    assert "Italika 150z" in body
    assert "12 meses" in body
    assert "papeleria_completa" in body.splitlines()[0]  # header has the column
    # And the raw dict shape must NOT leak into the CSV body.
    assert "'value':" not in body
    assert "{'confidence'" not in body
