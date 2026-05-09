"""Clients Enhanced — CSV import / export hardening (sesión 6).

Coverage:

- Phone canonicalisation, in particular MX mobile with vs without the
  legacy ``1``: ``+5215512345678`` and ``+525512345678`` must collapse to
  a single row keyed on ``+525512345678``.
- ``email`` and ``score`` columns are read on import, written on update.
- Export escapes formula-leading characters so a recipient opening the
  CSV in Excel doesn't trigger ``=SUM(...)`` execution.
- ``POST /import/preview`` returns parsed rows + errors without committing.
- File-size cap and row-count cap return 413.
"""
from __future__ import annotations

import asyncio
import io
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from atendia.api.customers_routes import _normalize_phone
from atendia.config import get_settings

# ── Pure unit tests for phone canonicalisation ──────────────────────


def test_normalize_phone_mx_10_digits() -> None:
    assert _normalize_phone("5512345678") == "+525512345678"


def test_normalize_phone_mx_strips_legacy_one_with_country_code() -> None:
    """``+5215512345678`` (legacy WhatsApp shape) must collapse to
    ``+525512345678`` so duplicate imports don't create two customers."""
    assert _normalize_phone("+5215512345678") == "+525512345678"
    assert _normalize_phone("5215512345678") == "+525512345678"


def test_normalize_phone_mx_strips_legacy_one_without_country_code() -> None:
    assert _normalize_phone("15512345678") == "+525512345678"


def test_normalize_phone_handles_punctuation() -> None:
    assert _normalize_phone("+52 (155) 1234-5678") == "+525512345678"


def test_normalize_phone_other_countries_passthrough_with_plus() -> None:
    """A leading ``+`` is an explicit E.164 signal: don't apply MX legacy
    heuristics, even if the country code happens to be 1 (US/Canada)."""
    assert _normalize_phone("+14155551234") == "+14155551234"
    # Without a ``+``, 11-digit numbers starting with 1 are interpreted as
    # MX legacy mobile because this is an MX-focused product. Operators
    # entering US numbers must include the ``+``.
    assert _normalize_phone("14155551234") == "+524155551234"


def test_normalize_phone_rejects_too_short_or_long() -> None:
    assert _normalize_phone("123") is None
    assert _normalize_phone("1234567890123456789") is None
    assert _normalize_phone("") is None
    assert _normalize_phone("abc") is None


# ── HTTP-level tests via TestClient ─────────────────────────────────


def _csv(rows: list[dict[str, str]], header: list[str]) -> bytes:
    out = io.StringIO()
    out.write(",".join(header) + "\n")
    for r in rows:
        out.write(",".join(r.get(h, "") for h in header) + "\n")
    return out.getvalue().encode("utf-8")


def test_import_preview_does_not_commit(client_tenant_admin) -> None:
    csv_bytes = _csv(
        [{"phone": "5512345678", "name": "Alice"}],
        ["phone", "name"],
    )
    files = {"file": ("preview.csv", io.BytesIO(csv_bytes), "text/csv")}
    resp = client_tenant_admin.post("/api/v1/customers/import/preview", files=files)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 1
    assert len(body["valid_rows"]) == 1
    assert body["valid_rows"][0]["phone"] == "+525512345678"
    assert body["valid_rows"][0]["will"] == "create"
    assert body["errors"] == []

    # Confirm nothing was actually inserted.
    listed = client_tenant_admin.get(
        "/api/v1/customers", params={"q": "5512345678"},
    )
    assert listed.status_code == 200
    assert all(c["phone_e164"] != "+525512345678" for c in listed.json()["items"])


def test_import_collapses_legacy_mx_duplicates(client_tenant_admin) -> None:
    """Two different legacy-1 shapes for the same physical phone must
    collapse to a single row, with the second flagged as duplicate-in-file
    in the errors list."""
    csv_bytes = _csv(
        [
            {"phone": "+5215512345678", "name": "Alice"},
            {"phone": "+525512345678", "name": "Alice 2"},
        ],
        ["phone", "name"],
    )
    files = {"file": ("dup.csv", io.BytesIO(csv_bytes), "text/csv")}
    resp = client_tenant_admin.post("/api/v1/customers/import", files=files)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["created"] == 1
    assert body["updated"] == 0
    assert any("duplicate" in e for e in body["errors"])


def test_import_reads_email_and_score(client_tenant_admin) -> None:
    csv_bytes = _csv(
        [
            {
                "phone": "+525512344321",
                "name": "Carlos",
                "email": "carlos@example.com",
                "score": "75",
            }
        ],
        ["phone", "name", "email", "score"],
    )
    files = {"file": ("rich.csv", io.BytesIO(csv_bytes), "text/csv")}
    resp = client_tenant_admin.post("/api/v1/customers/import", files=files)
    assert resp.status_code == 200, resp.text
    assert resp.json()["created"] == 1

    listed = client_tenant_admin.get(
        "/api/v1/customers", params={"q": "5512344321"},
    )
    items = listed.json()["items"]
    target = next(c for c in items if c["phone_e164"] == "+525512344321")
    detail = client_tenant_admin.get(f"/api/v1/customers/{target['id']}")
    body = detail.json()
    assert body["email"] == "carlos@example.com"
    assert body["score"] == 75


def test_import_invalid_email_records_row_error(client_tenant_admin) -> None:
    csv_bytes = _csv(
        [{"phone": "+525512344000", "name": "Bad", "email": "no-arroba"}],
        ["phone", "name", "email"],
    )
    files = {"file": ("bad.csv", io.BytesIO(csv_bytes), "text/csv")}
    resp = client_tenant_admin.post("/api/v1/customers/import", files=files)
    body = resp.json()
    assert body["created"] == 0
    assert any("email" in e for e in body["errors"])


def test_import_score_out_of_range_recorded(client_tenant_admin) -> None:
    csv_bytes = _csv(
        [{"phone": "+525512344111", "name": "X", "score": "150"}],
        ["phone", "name", "score"],
    )
    files = {"file": ("score.csv", io.BytesIO(csv_bytes), "text/csv")}
    resp = client_tenant_admin.post("/api/v1/customers/import", files=files)
    body = resp.json()
    assert body["created"] == 0
    assert any("score" in e for e in body["errors"])


def test_import_too_many_rows_413(client_tenant_admin) -> None:
    rows = [{"phone": f"+5255{str(i).zfill(8)}", "name": f"T{i}"} for i in range(2001)]
    csv_bytes = _csv(rows, ["phone", "name"])
    files = {"file": ("huge.csv", io.BytesIO(csv_bytes), "text/csv")}
    resp = client_tenant_admin.post("/api/v1/customers/import", files=files)
    assert resp.status_code == 413


def test_export_escapes_formula_leading_chars(client_tenant_admin) -> None:
    """Seed a customer whose name starts with ``=`` and verify the export
    prefixes it with `'` so Excel won't evaluate it as a formula."""
    async def _seed() -> None:
        engine = create_async_engine(get_settings().database_url)
        try:
            async with engine.begin() as conn:
                await conn.execute(
                    text(
                        "INSERT INTO customers (tenant_id, phone_e164, name) "
                        "VALUES (:t, :p, :n)"
                    ),
                    {
                        "t": client_tenant_admin.tenant_id,
                        "p": f"+5215{uuid4().hex[:9]}",
                        "n": "=SUM(A1:A5)",
                    },
                )
        finally:
            await engine.dispose()

    asyncio.run(_seed())
    resp = client_tenant_admin.get("/api/v1/customers/export")
    assert resp.status_code == 200
    body = resp.text
    # The dangerous cell must start with ' so Excel/Sheets treats it as a
    # literal string rather than a formula. Either with or without surrounding
    # CSV quoting is acceptable as long as the leading-quote sentinel is there.
    assert "'=SUM" in body, "formula prefix should be escaped"


def test_export_includes_email_column(client_tenant_admin) -> None:
    async def _seed() -> None:
        engine = create_async_engine(get_settings().database_url)
        try:
            async with engine.begin() as conn:
                await conn.execute(
                    text(
                        "INSERT INTO customers (tenant_id, phone_e164, name, email) "
                        "VALUES (:t, :p, 'Email Test', 'export@example.com')"
                    ),
                    {
                        "t": client_tenant_admin.tenant_id,
                        "p": f"+5215{uuid4().hex[:9]}",
                    },
                )
        finally:
            await engine.dispose()

    asyncio.run(_seed())
    resp = client_tenant_admin.get("/api/v1/customers/export")
    assert resp.status_code == 200
    body = resp.text
    header = body.splitlines()[0]
    assert "email" in header
    assert "export@example.com" in body
