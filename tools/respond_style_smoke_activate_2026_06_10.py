"""Phase 20 activation step — writes the section-8 smoke flags + the literal
human approval text into the deployment metadata. Does NOT stamp preflight
(that is the preflight tool's job) and sends nothing by itself.

    uv run python activate.py <deployment_id>
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import UTC, datetime
from uuid import UUID

from atendia.db.models.product_agent import AgentDeployment
from atendia.db.session import _get_factory
from atendia.product_agents.smoke_policy import APPROVED_SCOPE, EXACT_APPROVAL_TEXT


async def main() -> int:
    deployment_id = UUID(sys.argv[1])
    factory = _get_factory()
    async with factory() as session:
        deployment = await session.get(AgentDeployment, deployment_id)
        if deployment is None:
            print(json.dumps({"error": "deployment_not_found"}))
            return 1
        metadata = dict(deployment.metadata_json or {})
        metadata.update(
            {
                "respond_style_live_send_enabled": True,
                "respond_style_send_scope": APPROVED_SCOPE,
                "respond_style_live_allowed_phones": ["8128889241"],
                "respond_style_workflows_enabled": False,
                "respond_style_actions_enabled": False,
                "respond_style_legacy_fallback_enabled": False,
                "respond_style_fail_closed_notify_operator": True,
                "respond_style_rollback_active": False,
                "respond_style_smoke_approval_text": EXACT_APPROVAL_TEXT,
                "respond_style_smoke_approved_at": datetime.now(UTC).isoformat(),
            }
        )
        deployment.metadata_json = metadata
        # Canonical columns: metadata alone never arms sends (Phase 20.1).
        deployment.send_enabled = True
        deployment.outbox_enabled = True
        deployment.live_send_enabled = True
        deployment.single_contact_smoke_enabled = True
        await session.commit()
        print(
            json.dumps(
                {
                    "activation_flags_written": True,
                    "deployment_id": str(deployment.id),
                    "metadata": {
                        k: v
                        for k, v in metadata.items()
                        if k != "respond_style_smoke_approval_text"
                    },
                    "approval_text_set": metadata[
                        "respond_style_smoke_approval_text"
                    ]
                    == EXACT_APPROVAL_TEXT,
                    "note": "preflight stamp still required before any send",
                },
                ensure_ascii=False,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
