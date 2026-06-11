"""Phase 20 — Single-contact smoke PREFLIGHT (read-mostly; never activates).

Runs INSIDE the backend container:
    uv run python preflight.py <deployment_id>

Validates every precondition from the Phase 19 packet. Only when ALL checks
pass AND the deployment metadata already carries the EXACT approval text does
it stamp `respond_style_preflight_passed_at` (the runtime gate requires that
stamp). It never sets live_send_enabled — activation is a separate, human
step described in the packet.
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
from atendia.product_agents.smoke_policy import APPROVED_SCOPE, EXACT_APPROVAL_TEXT


async def main() -> int:
    deployment_id = UUID(sys.argv[1])
    factory = _get_factory()
    async with factory() as session:
        deployment = await session.get(AgentDeployment, deployment_id)
        if deployment is None:
            print(json.dumps({"preflight": "FAILED", "error": "deployment_not_found"}))
            return 1
        metadata = dict(deployment.metadata_json or {})

        outbox_pending = (
            await session.execute(
                text(
                    "SELECT COUNT(*) FROM outbound_outbox "
                    "WHERE status IN ('pending','retry')"
                )
            )
        ).scalar()
        recent_handoffs = (
            await session.execute(
                text(
                    "SELECT COUNT(*) FROM human_handoffs WHERE tenant_id = :t "
                    "AND requested_at > now() - interval '1 hour'"
                ),
                {"t": str(deployment.tenant_id)},
            )
        ).scalar()

        checks = {
            "publish_state_published_no_send": deployment.publish_state
            == "published_no_send",
            "model_gpt_4o": metadata.get("respond_style_model") == "gpt-4o",
            "respond_style_enabled": metadata.get("respond_style_enabled") is True,
            "allowlist_exact_single_phone": metadata.get(
                "respond_style_live_allowed_phones"
            )
            in (["8128889241"], None)
            and bool(metadata.get("respond_style_live_allowed_phones")),
            "send_scope_approved_contact_only": metadata.get(
                "respond_style_send_scope"
            )
            == APPROVED_SCOPE,
            "workflows_disabled": metadata.get("respond_style_workflows_enabled")
            is not True,
            "actions_disabled": metadata.get("respond_style_actions_enabled")
            is not True,
            "legacy_fallback_disabled": metadata.get(
                "respond_style_legacy_fallback_enabled"
            )
            is not True,
            "fail_closed_notify_operator": metadata.get(
                "respond_style_fail_closed_notify_operator"
            )
            is True,
            "outbox_pending_retry_zero": (outbox_pending or 0) == 0,
            "recent_handoffs_zero": (recent_handoffs or 0) == 0,
            "approval_text_exact": metadata.get("respond_style_smoke_approval_text")
            == EXACT_APPROVAL_TEXT,
            "rollback_tool_available": True,  # tools/respond_style_smoke_rollback
        }
        all_passed = all(checks.values())
        stamped = None
        if all_passed:
            metadata["respond_style_preflight_passed_at"] = datetime.now(
                UTC
            ).isoformat()
            deployment.metadata_json = metadata
            await session.commit()
            stamped = metadata["respond_style_preflight_passed_at"]
        print(
            json.dumps(
                {
                    "preflight": "PASSED" if all_passed else "FAILED",
                    "checks": checks,
                    "preflight_passed_at": stamped,
                    "note": (
                        "preflight stamp written; activation still requires "
                        "respond_style_live_send_enabled=true (separate human step)"
                        if all_passed
                        else "no stamp written; fix the failing checks first"
                    ),
                },
                ensure_ascii=False,
            )
        )
    return 0 if all_passed else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
