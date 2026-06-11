"""Phase 20 — Single-contact smoke ROLLBACK (immediate, no restart needed).

Runs INSIDE the backend container:
    uv run python rollback.py <deployment_id>

The runtime gate reads deployment metadata on EVERY turn, so flipping the
flags here stops sends on the very next inbound — no service restart. Shadow
observation stays enabled. Also clears any takeover markers, verifies outbox
and side-effect baselines, and exports the last hour of traces as the
incident record.
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import text

from atendia.db.models.product_agent import AgentDeployment
from atendia.db.session import _get_factory


async def main() -> int:
    deployment_id = UUID(sys.argv[1])
    factory = _get_factory()
    async with factory() as session:
        deployment = await session.get(AgentDeployment, deployment_id)
        if deployment is None:
            print(json.dumps({"rollback": "FAILED", "error": "deployment_not_found"}))
            return 1
        metadata = dict(deployment.metadata_json or {})
        metadata.update(
            {
                "respond_style_live_send_enabled": False,
                "respond_style_send_scope": "no_send",
                "respond_style_live_allowed_phones": [],
                "respond_style_rollback_active": True,
                "respond_style_preflight_passed_at": None,
                "respond_style_rollback_at": datetime.now(UTC).isoformat(),
            }
        )
        deployment.metadata_json = metadata
        deployment.send_enabled = False
        deployment.outbox_enabled = False
        deployment.live_send_enabled = False
        deployment.single_contact_smoke_enabled = False
        # Clear takeover markers so post-rollback shadow observation resumes.
        await session.execute(
            text(
                "UPDATE respond_style_shadow_fields SET takeover_pending = false "
                "WHERE tenant_id = :t"
            ),
            {"t": str(deployment.tenant_id)},
        )
        await session.commit()

        outbox_pending = (
            await session.execute(
                text(
                    "SELECT COUNT(*) FROM outbound_outbox "
                    "WHERE status IN ('pending','retry')"
                )
            )
        ).scalar()
        smoke_outbox = (
            await session.execute(
                text(
                    "SELECT COUNT(*) FROM outbound_outbox WHERE "
                    "payload->'metadata'->>'source' = "
                    "'respond_style_single_contact_smoke'"
                )
            )
        ).scalar()
        recent_actions = (
            await session.execute(
                text(
                    "SELECT COUNT(*) FROM workflow_executions "
                    "WHERE started_at > now() - interval '1 hour'"
                )
            )
        ).scalar()
        traces = (
            await session.execute(
                text(
                    "SELECT id, created_at, conversation_id, inbound_text, "
                    "router_trigger FROM turn_traces WHERE tenant_id = :t "
                    "AND created_at > now() - interval '1 hour' "
                    "ORDER BY created_at"
                ),
                {"t": str(deployment.tenant_id)},
            )
        ).mappings()
        incident = [dict(row) for row in traces]

    print(
        json.dumps(
            {
                "rollback": "DONE",
                "live_send_enabled": False,
                "send_scope": "no_send",
                "allowed_phones_cleared": True,
                "takeover_markers_cleared": True,
                "outbox_pending_retry": outbox_pending,
                "smoke_outbox_rows_total": smoke_outbox,
                "workflow_executions_last_hour": recent_actions,
                "incident_trace_count": len(incident),
                "incident_traces": incident,
            },
            ensure_ascii=False,
            default=str,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
