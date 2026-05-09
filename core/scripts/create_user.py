"""Create dele.zored@hotmail.com as superadmin. Run from core/:
    uv run python scripts/create_user.py
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from atendia.api._auth_helpers import hash_password
from atendia.config import get_settings


async def main() -> None:
    engine = create_async_engine(get_settings().database_url)
    try:
        async with engine.begin() as conn:
            tid = (await conn.execute(text("SELECT id FROM tenants LIMIT 1"))).scalar()
            print(f"Tenant: {tid}")

            existing = (
                await conn.execute(
                    text("SELECT id FROM tenant_users WHERE email = :e"),
                    {"e": "dele.zored@hotmail.com"},
                )
            ).scalar()

            if existing:
                print(f"User already exists: {existing}")
            else:
                await conn.execute(
                    text(
                        "INSERT INTO tenant_users (tenant_id, email, role, password_hash) "
                        "VALUES (:t, :e, :r, :h)"
                    ),
                    {
                        "t": tid,
                        "e": "dele.zored@hotmail.com",
                        "r": "superadmin",
                        "h": hash_password("admin123"),
                    },
                )
                print("Created dele.zored@hotmail.com as superadmin")

            rows = (
                await conn.execute(
                    text("SELECT email, role FROM tenant_users ORDER BY created_at")
                )
            ).fetchall()
            print("\nAll users:")
            for r in rows:
                print(f"  {r[0]} -> {r[1]}")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
