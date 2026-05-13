"""One-shot seed: create a fresh tenant + superadmin user.

For manual QA — gives the user a clean slate to walk through the whole
product. The new tenant has `is_demo=False` so it does NOT receive the
auto-seeded demo customers / agents / workflows that the demo tenant
gets.

Run from `core/`:
    uv run python scripts/seed_zored_user.py
"""
from __future__ import annotations

import asyncio
import sys
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from atendia.api._auth_helpers import hash_password
from atendia.config import get_settings

EMAIL = "dele.zored@hotmail.com"
PASSWORD = "dinamo123"
ROLE = "superadmin"
TENANT_NAME = "Zored QA Workspace"


async def main() -> None:
    engine = create_async_engine(get_settings().database_url)
    async with engine.begin() as conn:
        # Check if user already exists
        existing = (
            await conn.execute(
                text("SELECT id, tenant_id FROM tenant_users WHERE email = :e"),
                {"e": EMAIL},
            )
        ).first()
        if existing is not None:
            uid, tid = existing
            # Update password just in case
            await conn.execute(
                text(
                    "UPDATE tenant_users SET password_hash = :h, role = :r "
                    "WHERE id = :u"
                ),
                {"h": hash_password(PASSWORD), "r": ROLE, "u": uid},
            )
            print(f"User already exists: {EMAIL}")
            print(f"  tenant_id: {tid}")
            print(f"  user_id:   {uid}")
            print(f"  password reset to: {PASSWORD}")
            return

        # Create a fresh tenant — explicitly NOT a demo so no auto-seeding.
        tenant_id = (
            await conn.execute(
                text(
                    "INSERT INTO tenants (name, is_demo) "
                    "VALUES (:n, false) RETURNING id"
                ),
                {"n": TENANT_NAME},
            )
        ).scalar()

        user_id = (
            await conn.execute(
                text(
                    "INSERT INTO tenant_users (tenant_id, email, role, password_hash) "
                    "VALUES (:t, :e, :r, :h) RETURNING id"
                ),
                {
                    "t": tenant_id,
                    "e": EMAIL,
                    "r": ROLE,
                    "h": hash_password(PASSWORD),
                },
            )
        ).scalar()

        # Seed a minimal tenant_branding row so the branding API doesn't 404.
        await conn.execute(
            text("INSERT INTO tenant_branding (tenant_id) VALUES (:t)"),
            {"t": tenant_id},
        )

    await engine.dispose()

    print("Created fresh workspace + superadmin user.")
    print(f"  email:     {EMAIL}")
    print(f"  password:  {PASSWORD}")
    print(f"  role:      {ROLE}")
    print(f"  tenant_id: {tenant_id}")
    print(f"  user_id:   {user_id}")
    print()
    print("This tenant has NO seeded data. Conversations, customers, ")
    print("workflows, agents, knowledge — todo empieza vacío.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(130)
