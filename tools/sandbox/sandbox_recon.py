"""Read-only recon: which real tenant is best for a high-fidelity sandbox run.

Lists tenants with their default agent (system_prompt?), active pipeline,
catalog/FAQ counts, and a sample conversation id. NO writes.
"""

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CORE = ROOT / "core"
if str(CORE) not in sys.path:
    sys.path.insert(0, str(CORE))

from sqlalchemy import text

from atendia.config import get_settings
from atendia.db.session import _get_factory


async def main() -> None:
    print("DB:", get_settings().database_url)
    factory = _get_factory()
    session = factory()
    try:
        tenants = (
            await session.execute(
                text("SELECT id, name FROM tenants ORDER BY created_at NULLS LAST")
            )
        ).fetchall()
        print(f"\n{len(tenants)} tenants\n" + "=" * 60)
        for tid, name in tenants:
            agent = (
                await session.execute(
                    text(
                        "SELECT name, is_default, "
                        "(system_prompt IS NOT NULL AND length(trim(system_prompt))>0) "
                        "FROM agents WHERE tenant_id=:t ORDER BY is_default DESC LIMIT 1"
                    ),
                    {"t": tid},
                )
            ).fetchone()
            pipe = (
                await session.execute(
                    text(
                        "SELECT version FROM tenant_pipelines "
                        "WHERE tenant_id=:t AND active=true LIMIT 1"
                    ),
                    {"t": tid},
                )
            ).scalar()
            n_cat = (
                await session.execute(
                    text("SELECT count(*) FROM tenant_catalogs WHERE tenant_id=:t"),
                    {"t": tid},
                )
            ).scalar()
            n_faq = (
                await session.execute(
                    text("SELECT count(*) FROM tenant_faqs WHERE tenant_id=:t"),
                    {"t": tid},
                )
            ).scalar()
            n_conv = (
                await session.execute(
                    text("SELECT count(*) FROM conversations WHERE tenant_id=:t"),
                    {"t": tid},
                )
            ).scalar()
            sample_conv = (
                await session.execute(
                    text(
                        "SELECT id, current_stage FROM conversations "
                        "WHERE tenant_id=:t ORDER BY created_at DESC LIMIT 1"
                    ),
                    {"t": tid},
                )
            ).fetchone()
            print(
                f"\ntenant {name!r}  id={tid}"
                f"\n  agent={agent!r}  active_pipeline_v={pipe}"
                f"\n  catalog={n_cat}  faqs={n_faq}  conversations={n_conv}"
                f"\n  sample_conv={sample_conv!r}"
            )
    finally:
        await session.rollback()
        await session.close()


if __name__ == "__main__":
    asyncio.run(main())
