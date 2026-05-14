"""Public webhook entry point for the ``webhook_received`` workflow trigger.

Each workflow with ``trigger_type == "webhook_received"`` carries a unique
``webhook_token``. External systems POST JSON to
``/api/v1/webhooks/workflow/{token}``; we emit a ``webhook_received`` event
which the workflow engine consumes (see ``evaluate_event``).

Design notes:

- No tenant header required: the token IS the auth. Brute-forcing is
  impractical because tokens are 24-byte URL-safe randoms (~192 bits).
- We accept any JSON shape; the workflow operator decides which keys to read
  via JSONPath-style variable mappings (planned). For now the whole payload
  lands in ``event.payload["body"]``.
- Bodies are capped at 64KB to protect the event row.
- We deliberately don't enroll a specific contact yet — that requires a
  ``contact_id``/``email``/``phone`` mapper which is its own feature.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from atendia.contracts.event import EventType
from atendia.db.models.workflow import Workflow
from atendia.db.session import get_db_session
from atendia.state_machine.event_emitter import EventEmitter

router = APIRouter()

# Hard cap on raw body bytes. A real webhook body lives well under 4KB; this
# is just a runaway-payload guard.
MAX_BODY_BYTES = 64 * 1024


@router.post("/workflow/{token}", status_code=status.HTTP_202_ACCEPTED)
async def workflow_webhook(
    token: str,
    request: Request,
):
    """Accept a JSON POST and turn it into a ``webhook_received`` event.

    Returns ``202 Accepted`` so the caller doesn't wait for workflow
    execution. Returns ``404`` (not ``401``) for unknown tokens so we
    don't leak which tokens exist via timing.
    """
    if len(token) < 16 or len(token) > 48:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown webhook")

    raw = await request.body()
    if len(raw) > MAX_BODY_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "payload too large")

    # We don't depend-inject the session because we want to commit
    # independently of the caller's transaction (this is a public endpoint).
    async for session in get_db_session():  # type: ignore[func-returns-value]
        workflow = (
            await session.execute(
                select(Workflow).where(
                    Workflow.webhook_token == token,
                    Workflow.trigger_type == "webhook_received",
                    Workflow.active.is_(True),
                )
            )
        ).scalar_one_or_none()
        if workflow is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown webhook")

        try:
            body_json = await request.json()
        except Exception:
            body_json = None

        emitter = EventEmitter(session)
        await emitter.emit(
            conversation_id=None,
            tenant_id=workflow.tenant_id,
            event_type=EventType.WEBHOOK_RECEIVED,
            payload={
                "workflow_id": str(workflow.id),
                "body": body_json,
                "raw_size": len(raw),
                "content_type": request.headers.get("content-type"),
            },
        )
        await session.commit()
        return {"accepted": True, "workflow_id": str(workflow.id)}
