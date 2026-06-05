from __future__ import annotations

import argparse
import asyncio
import os
from datetime import date
from pathlib import Path
from uuid import UUID

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from atendia.agent_runtime.model_provider import build_agent_turn_provider
from atendia.agent_runtime.provider_quality_gate import provider_external_allowed
from atendia.config import get_settings
from atendia.simulation.reporting import (
    write_legacy_cleanup_readiness_report,
    write_persistent_simulation_report,
)
from atendia.simulation.runner import SimulationLabRunner


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Dinamo persistent simulation lab.")
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--agent-id", required=True)
    parser.add_argument("--mode", default="simulation_apply")
    parser.add_argument("--provider", default="local_deterministic")
    parser.add_argument("--report-date", default="2026-06-01")
    parser.add_argument("--fixture", default=None)
    parser.add_argument("--no-whatsapp", action="store_true", default=False)
    parser.add_argument("--no-outbox", action="store_true", default=False)
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    if not args.no_whatsapp or not args.no_outbox:
        raise SystemExit("--no-whatsapp and --no-outbox are required")
    os.environ.setdefault("ATENDIA_V2_AGENT_RUNTIME_V2_ENABLED", "true")
    os.environ.setdefault("ATENDIA_V2_AGENT_RUNTIME_V2_SEND_ENABLED", "false")
    os.environ.setdefault("ATENDIA_V2_AGENT_RUNTIME_V2_ACTIONS_ENABLED", "false")
    os.environ.setdefault("ATENDIA_V2_AGENT_RUNTIME_V2_WORKFLOW_EVENTS_ENABLED", "false")
    os.environ.setdefault(
        "ATENDIA_V2_AGENT_RUNTIME_V2_MODEL_PROVIDER",
        "openai" if args.provider == "openai" else "disabled",
    )
    get_settings.cache_clear()
    settings = get_settings()
    report_date = date.fromisoformat(str(args.report_date).replace("_", "-"))
    provider = None
    if args.provider == "openai":
        approval = provider_external_allowed(
            tenant_id=args.tenant_id,
            agent_id=args.agent_id,
            provider="openai",
            settings=settings,
            report_date=report_date,
        )
        if not approval.approved:
            raise SystemExit(
                "openai provider blocked by provider quality gate: "
                + "; ".join(approval.reasons)
            )
        provider = build_agent_turn_provider(settings, model_provider_allowed=True)
    engine = create_async_engine(get_settings().database_url)
    try:
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as session:
            fixture_kwargs = (
                {"fixture_path": Path(args.fixture)}
                if args.fixture
                else {}
            )
            result = await SimulationLabRunner(
                session,
                provider_name=args.provider,
                provider=provider,
            ).run_fixture(
                tenant_id=UUID(args.tenant_id),
                agent_id=UUID(args.agent_id),
                mode=args.mode,
                **fixture_kwargs,
            )
            await session.commit()
            main_report = write_persistent_simulation_report(result, report_date=report_date)
            legacy_report = write_legacy_cleanup_readiness_report(
                result,
                report_date=report_date,
            )
            print(f"simulation_run_id={result['run'].id}")
            print(f"score={result['run'].metrics['score']}")
            print(f"main_report={main_report}")
            print(f"legacy_report={legacy_report}")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
