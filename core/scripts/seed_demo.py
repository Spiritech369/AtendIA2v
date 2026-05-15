"""Idempotent seed: creates a 'demo' tenant + 'admin@demo.com' operator
with bcrypt password 'admin123'. Run from `core/`:

    uv run python scripts/seed_demo.py

Re-running is safe — the script checks for existing rows and skips inserts
if found. The password is NOT updated on re-run; if you forgot it, delete
the user row manually and re-seed.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# Ensure the project root (core/) is on sys.path so `import atendia` works
# when this script is launched as `uv run python scripts/seed_demo.py`.
# Python only auto-adds the script's directory; the package lives one up.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402

from atendia.api._auth_helpers import hash_password  # noqa: E402
from atendia.config import get_settings  # noqa: E402


DEMO_TENANT_NAME = "demo"
DEMO_EMAIL = "admin@demo.com"
DEMO_PASSWORD = "admin123"


async def main() -> None:
    engine = create_async_engine(get_settings().database_url)
    try:
        async with engine.begin() as conn:
            tid = (
                await conn.execute(
                    text("SELECT id FROM tenants WHERE name = :n"),
                    {"n": DEMO_TENANT_NAME},
                )
            ).scalar()
            if tid is None:
                tid = (
                    await conn.execute(
                        text("INSERT INTO tenants (name) VALUES (:n) RETURNING id"),
                        {"n": DEMO_TENANT_NAME},
                    )
                ).scalar()
                print(f"[OK] Created tenant '{DEMO_TENANT_NAME}' (id={tid})")
            else:
                print(f"[--] Tenant '{DEMO_TENANT_NAME}' already exists (id={tid})")

            uid = (
                await conn.execute(
                    text("SELECT id FROM tenant_users WHERE email = :e"),
                    {"e": DEMO_EMAIL},
                )
            ).scalar()
            if uid is None:
                await conn.execute(
                    text(
                        "INSERT INTO tenant_users "
                        "(tenant_id, email, role, password_hash) "
                        "VALUES (:t, :e, 'operator', :h)"
                    ),
                    {
                        "t": tid,
                        "e": DEMO_EMAIL,
                        "h": hash_password(DEMO_PASSWORD),
                    },
                )
                print(f"[OK] Created operator {DEMO_EMAIL} (password '{DEMO_PASSWORD}')")
            else:
                print(f"[--] User {DEMO_EMAIL} already exists (id={uid}; password unchanged)")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
