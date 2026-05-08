# Conversations Scope Gaps Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Close 6 remaining v1→v2 Conversations page gaps: assigned agent, unread tracking, context menu actions (change stage + soft delete), free-form tags, and AI agent sidebar grouping.

**Architecture:** Single Alembic migration adds `assigned_user_id`, `unread_count`, `tags`, `deleted_at` columns to `conversations`. Three new endpoints (PATCH, DELETE, mark-read) plus list endpoint filter extensions. Frontend wires new mailbox tabs, unread badges, tag chips, context menu actions, and an AI agent sidebar section.

**Tech Stack:** FastAPI, SQLAlchemy 2.0 async, Alembic, PostgreSQL 15, React 19, TanStack Query v5, TanStack Router v1, shadcn/ui, Tailwind CSS 4, Zustand.

---

## Task 1: Database Migration

**Files:**
- Create: `core/atendia/db/migrations/versions/024_conversations_scope_gaps.py`

**Step 1: Create migration file**

```python
"""024_conversations_scope_gaps

Revision ID: a1b2c3d4e5f6
Revises: f9a0b1c2d3e4
Create Date: 2026-05-08

Adds assigned_user_id, unread_count, tags, deleted_at to conversations
for v1 parity: agent assignment, unread badges, free-form tags, soft delete.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: str | Sequence[str] | None = "f9a0b1c2d3e4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "conversations",
        sa.Column(
            "assigned_user_id",
            sa.UUID(),
            sa.ForeignKey("tenant_users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "conversations",
        sa.Column("unread_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "conversations",
        sa.Column(
            "tags",
            sa.dialects.postgresql.JSONB(),
            nullable=False,
            server_default="[]",
        ),
    )
    op.add_column(
        "conversations",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "idx_conversations_assigned_user_id",
        "conversations",
        ["assigned_user_id"],
    )
    op.create_index(
        "idx_conversations_not_deleted",
        "conversations",
        ["tenant_id"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("idx_conversations_not_deleted")
    op.drop_index("idx_conversations_assigned_user_id")
    op.drop_column("conversations", "deleted_at")
    op.drop_column("conversations", "tags")
    op.drop_column("conversations", "unread_count")
    op.drop_column("conversations", "assigned_user_id")
```

**Step 2: Run the migration**

Run: `cd core && .venv/Scripts/python.exe -m alembic upgrade head`
Expected: `Running upgrade f9a0b1c2d3e4 -> a1b2c3d4e5f6, 024_conversations_scope_gaps`

**Step 3: Verify columns exist**

Run: `cd core && .venv/Scripts/python.exe -c "import asyncio; from sqlalchemy import text; from sqlalchemy.ext.asyncio import create_async_engine; from atendia.config import get_settings; e = create_async_engine(get_settings().database_url); asyncio.run((lambda: e.begin().__aenter__())() if False else asyncio.sleep(0))"`

Or just verify by checking the table structure in psql.

**Step 4: Commit**

```bash
git add core/atendia/db/migrations/versions/024_conversations_scope_gaps.py
git commit -m "feat(db): migration 024 — assigned_user_id, unread_count, tags, deleted_at on conversations"
```

---

## Task 2: Update SQLAlchemy Model

**Files:**
- Modify: `core/atendia/db/models/conversation.py`

**Step 1: Add four new columns to Conversation class**

After the `last_activity_at` column (line 22), add:

```python
    assigned_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("tenant_users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    unread_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    tags: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
```

Existing imports already include `JSONB`, `ForeignKey`, `Integer`, `DateTime`. No new imports needed.

**Step 2: Commit**

```bash
git add core/atendia/db/models/conversation.py
git commit -m "feat(model): add assigned_user_id, unread_count, tags, deleted_at to Conversation"
```

---

## Task 3: Add EventType values

**Files:**
- Modify: `core/atendia/contracts/event.py`

**Step 1: Add two new enum members**

After `ERROR_OCCURRED` (line 16), add:

```python
    CONVERSATION_UPDATED = "conversation_updated"
    CONVERSATION_DELETED = "conversation_deleted"
```

**Step 2: Commit**

```bash
git add core/atendia/contracts/event.py
git commit -m "feat(contracts): add CONVERSATION_UPDATED, CONVERSATION_DELETED event types"
```

---

## Task 4: PATCH /conversations/:id endpoint

**Files:**
- Modify: `core/atendia/api/conversations_routes.py`
- Test: `core/tests/api/test_conversations_patch.py`

**Step 1: Write the failing tests**

Create `core/tests/api/test_conversations_patch.py`:

```python
"""Tests for PATCH /api/v1/conversations/:id — partial update."""
from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from atendia.config import get_settings


def _seed_conversation(tid: str) -> str:
    """Create a customer + conversation, return conversation_id."""
    async def _do() -> str:
        engine = create_async_engine(get_settings().database_url)
        async with engine.begin() as conn:
            cust_id = (await conn.execute(
                text("INSERT INTO customers (tenant_id, phone_e164) VALUES (:t, :p) RETURNING id"),
                {"t": tid, "p": f"+521{uuid4().hex[:10]}"},
            )).scalar()
            conv_id = (await conn.execute(
                text("INSERT INTO conversations (tenant_id, customer_id) VALUES (:t, :c) RETURNING id"),
                {"t": tid, "c": cust_id},
            )).scalar()
            await conn.execute(
                text("INSERT INTO conversation_state (conversation_id) VALUES (:c)"),
                {"c": conv_id},
            )
        await engine.dispose()
        return str(conv_id)
    return asyncio.run(_do())


class TestPatchConversation:
    def test_update_stage(self, client_operator):
        conv_id = _seed_conversation(client_operator.tenant_id)
        resp = client_operator.patch(
            f"/api/v1/conversations/{conv_id}",
            json={"current_stage": "quoted"},
        )
        assert resp.status_code == 200
        assert resp.json()["current_stage"] == "quoted"

    def test_update_tags(self, client_operator):
        conv_id = _seed_conversation(client_operator.tenant_id)
        resp = client_operator.patch(
            f"/api/v1/conversations/{conv_id}",
            json={"tags": ["vip", "urgent"]},
        )
        assert resp.status_code == 200
        assert resp.json()["tags"] == ["vip", "urgent"]

    def test_assign_user(self, client_operator):
        conv_id = _seed_conversation(client_operator.tenant_id)
        resp = client_operator.patch(
            f"/api/v1/conversations/{conv_id}",
            json={"assigned_user_id": client_operator.user_id},
        )
        assert resp.status_code == 200
        assert resp.json()["assigned_user_id"] == client_operator.user_id

    def test_unassign_user(self, client_operator):
        conv_id = _seed_conversation(client_operator.tenant_id)
        # First assign
        client_operator.patch(
            f"/api/v1/conversations/{conv_id}",
            json={"assigned_user_id": client_operator.user_id},
        )
        # Then unassign
        resp = client_operator.patch(
            f"/api/v1/conversations/{conv_id}",
            json={"assigned_user_id": None},
        )
        assert resp.status_code == 200
        assert resp.json()["assigned_user_id"] is None

    def test_404_cross_tenant(self, client_operator):
        fake_id = str(uuid4())
        resp = client_operator.patch(
            f"/api/v1/conversations/{fake_id}",
            json={"current_stage": "quoted"},
        )
        assert resp.status_code == 404

    def test_empty_body_is_noop(self, client_operator):
        conv_id = _seed_conversation(client_operator.tenant_id)
        resp = client_operator.patch(
            f"/api/v1/conversations/{conv_id}",
            json={},
        )
        assert resp.status_code == 200

    def test_401_unauthenticated(self, client):
        resp = client.patch(
            f"/api/v1/conversations/{uuid4()}",
            json={"current_stage": "quoted"},
        )
        assert resp.status_code == 401
```

**Step 2: Run tests to verify they fail**

Run: `cd core && .venv/Scripts/python.exe -m pytest tests/api/test_conversations_patch.py -v`
Expected: FAIL — 405 Method Not Allowed (no PATCH handler yet)

**Step 3: Implement the PATCH endpoint**

In `core/atendia/api/conversations_routes.py`, add after the `resume_bot` endpoint (line 511):

```python
# ---------- Partial update (scope gaps) ----------


class ConversationPatchBody(BaseModel):
    current_stage: str | None = None
    assigned_user_id: UUID | None = "__unset__"  # sentinel: omitted ≠ null
    tags: list[str] | None = None

    class Config:
        # Allow the sentinel pattern: field absent → unchanged,
        # field = null → set to NULL in DB.
        json_schema_extra = {"examples": [{"tags": ["vip"]}]}


class ConversationPatchResponse(BaseModel):
    id: UUID
    current_stage: str
    assigned_user_id: UUID | None
    assigned_user_email: str | None
    tags: list[str]
    unread_count: int
    status: str


@router.patch("/{conversation_id}", response_model=ConversationPatchResponse)
async def patch_conversation(
    conversation_id: UUID,
    body: Request,
    user: AuthUser = Depends(current_user),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> ConversationPatchResponse:
    """Partial update: change stage, assign/unassign user, set tags."""
    raw = await body.json()

    own = (
        await session.execute(
            select(Conversation).where(
                Conversation.id == conversation_id,
                Conversation.tenant_id == tenant_id,
                Conversation.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if own is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "conversation not found")

    values: dict = {}
    if "current_stage" in raw and raw["current_stage"] is not None:
        values["current_stage"] = raw["current_stage"]
    if "assigned_user_id" in raw:
        values["assigned_user_id"] = raw["assigned_user_id"]  # None means unassign
    if "tags" in raw and raw["tags"] is not None:
        values["tags"] = raw["tags"]

    if values:
        await session.execute(
            update(Conversation)
            .where(Conversation.id == conversation_id)
            .values(**values)
        )

    # Emit audit event
    from atendia.contracts.event import EventType
    from atendia.state_machine.event_emitter import EventEmitter
    emitter = EventEmitter(session)
    await emitter.emit(
        conversation_id=conversation_id,
        tenant_id=tenant_id,
        event_type=EventType.CONVERSATION_UPDATED,
        payload={"fields": list(values.keys()), "by": str(user.user_id)},
    )

    await session.commit()

    # Re-fetch to return updated state with joined user email
    from atendia.db.models.user import TenantUser
    row = (await session.execute(
        select(
            Conversation.id,
            Conversation.current_stage,
            Conversation.assigned_user_id,
            Conversation.tags,
            Conversation.unread_count,
            Conversation.status,
            TenantUser.email.label("assigned_user_email"),
        )
        .select_from(Conversation)
        .outerjoin(TenantUser, TenantUser.id == Conversation.assigned_user_id)
        .where(Conversation.id == conversation_id)
    )).first()

    return ConversationPatchResponse(
        id=row.id,
        current_stage=row.current_stage,
        assigned_user_id=row.assigned_user_id,
        assigned_user_email=row.assigned_user_email,
        tags=row.tags or [],
        unread_count=row.unread_count,
        status=row.status,
    )
```

Note: Check the exact import path for `TenantUser`. Find it via:
`grep -r "class TenantUser" core/atendia/db/models/`

**Step 4: Run tests to verify they pass**

Run: `cd core && .venv/Scripts/python.exe -m pytest tests/api/test_conversations_patch.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add core/atendia/api/conversations_routes.py core/tests/api/test_conversations_patch.py
git commit -m "feat(api): PATCH /conversations/:id — update stage, assigned user, tags"
```

---

## Task 5: DELETE /conversations/:id endpoint (soft delete)

**Files:**
- Modify: `core/atendia/api/conversations_routes.py`
- Test: `core/tests/api/test_conversations_delete.py`

**Step 1: Write the failing tests**

Create `core/tests/api/test_conversations_delete.py`:

```python
"""Tests for DELETE /api/v1/conversations/:id — soft delete."""
from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from atendia.config import get_settings


def _seed_conversation(tid: str) -> str:
    async def _do() -> str:
        engine = create_async_engine(get_settings().database_url)
        async with engine.begin() as conn:
            cust_id = (await conn.execute(
                text("INSERT INTO customers (tenant_id, phone_e164) VALUES (:t, :p) RETURNING id"),
                {"t": tid, "p": f"+521{uuid4().hex[:10]}"},
            )).scalar()
            conv_id = (await conn.execute(
                text("INSERT INTO conversations (tenant_id, customer_id) VALUES (:t, :c) RETURNING id"),
                {"t": tid, "c": cust_id},
            )).scalar()
            await conn.execute(
                text("INSERT INTO conversation_state (conversation_id) VALUES (:c)"),
                {"c": conv_id},
            )
        await engine.dispose()
        return str(conv_id)
    return asyncio.run(_do())


class TestDeleteConversation:
    def test_soft_delete_returns_204(self, client_operator):
        conv_id = _seed_conversation(client_operator.tenant_id)
        resp = client_operator.delete(f"/api/v1/conversations/{conv_id}")
        assert resp.status_code == 204

    def test_deleted_excluded_from_list(self, client_operator):
        conv_id = _seed_conversation(client_operator.tenant_id)
        client_operator.delete(f"/api/v1/conversations/{conv_id}")
        resp = client_operator.get("/api/v1/conversations")
        ids = [c["id"] for c in resp.json()["items"]]
        assert conv_id not in ids

    def test_deleted_returns_404_on_detail(self, client_operator):
        conv_id = _seed_conversation(client_operator.tenant_id)
        client_operator.delete(f"/api/v1/conversations/{conv_id}")
        resp = client_operator.get(f"/api/v1/conversations/{conv_id}")
        assert resp.status_code == 404

    def test_delete_idempotent(self, client_operator):
        conv_id = _seed_conversation(client_operator.tenant_id)
        client_operator.delete(f"/api/v1/conversations/{conv_id}")
        resp = client_operator.delete(f"/api/v1/conversations/{conv_id}")
        assert resp.status_code == 404

    def test_404_cross_tenant(self, client_operator):
        resp = client_operator.delete(f"/api/v1/conversations/{uuid4()}")
        assert resp.status_code == 404
```

**Step 2: Run to verify failure**

Run: `cd core && .venv/Scripts/python.exe -m pytest tests/api/test_conversations_delete.py -v`
Expected: FAIL — 405 Method Not Allowed

**Step 3: Implement the DELETE endpoint**

In `core/atendia/api/conversations_routes.py`, add after the PATCH endpoint:

```python
@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(
    conversation_id: UUID,
    user: AuthUser = Depends(current_user),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> None:
    """Soft-delete: sets deleted_at, excluded from list/detail."""
    own = (
        await session.execute(
            select(Conversation.id).where(
                Conversation.id == conversation_id,
                Conversation.tenant_id == tenant_id,
                Conversation.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if own is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "conversation not found")

    await session.execute(
        update(Conversation)
        .where(Conversation.id == conversation_id)
        .values(deleted_at=datetime.now(UTC))
    )

    from atendia.contracts.event import EventType
    from atendia.state_machine.event_emitter import EventEmitter
    emitter = EventEmitter(session)
    await emitter.emit(
        conversation_id=conversation_id,
        tenant_id=tenant_id,
        event_type=EventType.CONVERSATION_DELETED,
        payload={"by": str(user.user_id)},
    )
    await session.commit()
```

Also update `list_conversations` and `get_conversation` to exclude soft-deleted rows.

In `list_conversations` (around line 176), add after `.where(Conversation.tenant_id == tenant_id)`:

```python
        .where(Conversation.deleted_at.is_(None))
```

In `get_conversation` (around line 265), add to the `.where()`:

```python
            Conversation.deleted_at.is_(None),
```

**Step 4: Run tests**

Run: `cd core && .venv/Scripts/python.exe -m pytest tests/api/test_conversations_delete.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add core/atendia/api/conversations_routes.py core/tests/api/test_conversations_delete.py
git commit -m "feat(api): DELETE /conversations/:id — soft delete with deleted_at"
```

---

## Task 6: POST /conversations/:id/mark-read endpoint

**Files:**
- Modify: `core/atendia/api/conversations_routes.py`
- Test: `core/tests/api/test_conversations_mark_read.py`

**Step 1: Write the failing tests**

Create `core/tests/api/test_conversations_mark_read.py`:

```python
"""Tests for POST /api/v1/conversations/:id/mark-read."""
from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from atendia.config import get_settings


def _seed_conversation_with_unread(tid: str, unread: int = 3) -> str:
    async def _do() -> str:
        engine = create_async_engine(get_settings().database_url)
        async with engine.begin() as conn:
            cust_id = (await conn.execute(
                text("INSERT INTO customers (tenant_id, phone_e164) VALUES (:t, :p) RETURNING id"),
                {"t": tid, "p": f"+521{uuid4().hex[:10]}"},
            )).scalar()
            conv_id = (await conn.execute(
                text(
                    "INSERT INTO conversations (tenant_id, customer_id, unread_count) "
                    "VALUES (:t, :c, :u) RETURNING id"
                ),
                {"t": tid, "c": cust_id, "u": unread},
            )).scalar()
            await conn.execute(
                text("INSERT INTO conversation_state (conversation_id) VALUES (:c)"),
                {"c": conv_id},
            )
        await engine.dispose()
        return str(conv_id)
    return asyncio.run(_do())


class TestMarkRead:
    def test_resets_to_zero(self, client_operator):
        conv_id = _seed_conversation_with_unread(client_operator.tenant_id, 5)
        resp = client_operator.post(f"/api/v1/conversations/{conv_id}/mark-read")
        assert resp.status_code == 204

    def test_unread_count_is_zero_after(self, client_operator):
        conv_id = _seed_conversation_with_unread(client_operator.tenant_id, 5)
        client_operator.post(f"/api/v1/conversations/{conv_id}/mark-read")
        detail = client_operator.get(f"/api/v1/conversations/{conv_id}")
        assert detail.json()["unread_count"] == 0

    def test_idempotent(self, client_operator):
        conv_id = _seed_conversation_with_unread(client_operator.tenant_id, 0)
        resp = client_operator.post(f"/api/v1/conversations/{conv_id}/mark-read")
        assert resp.status_code == 204

    def test_404_cross_tenant(self, client_operator):
        resp = client_operator.post(f"/api/v1/conversations/{uuid4()}/mark-read")
        assert resp.status_code == 404
```

**Step 2: Run to verify failure**

Run: `cd core && .venv/Scripts/python.exe -m pytest tests/api/test_conversations_mark_read.py -v`
Expected: FAIL — 404 or 405

**Step 3: Implement the mark-read endpoint**

In `core/atendia/api/conversations_routes.py`, add:

```python
@router.post("/{conversation_id}/mark-read", status_code=status.HTTP_204_NO_CONTENT)
async def mark_read(
    conversation_id: UUID,
    user: AuthUser = Depends(current_user),  # noqa: ARG001
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> None:
    """Reset unread_count to 0 — called when operator opens a conversation."""
    own = (
        await session.execute(
            select(Conversation.id).where(
                Conversation.id == conversation_id,
                Conversation.tenant_id == tenant_id,
                Conversation.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if own is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "conversation not found")

    await session.execute(
        update(Conversation)
        .where(Conversation.id == conversation_id)
        .values(unread_count=0)
    )
    await session.commit()
```

Also: update `ConversationDetail` response model (line 60) to include new fields:

```python
class ConversationDetail(BaseModel):
    id: UUID
    tenant_id: UUID
    customer_id: UUID
    customer_phone: str
    customer_name: str | None
    status: str
    current_stage: str
    bot_paused: bool
    last_activity_at: datetime
    created_at: datetime
    extracted_data: dict
    pending_confirmation: str | None
    last_intent: str | None
    # Scope gap fields
    assigned_user_id: UUID | None
    assigned_user_email: str | None
    unread_count: int
    tags: list[str]
```

And update `get_conversation` to select and return the new fields.

**Step 4: Run tests**

Run: `cd core && .venv/Scripts/python.exe -m pytest tests/api/test_conversations_mark_read.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add core/atendia/api/conversations_routes.py core/tests/api/test_conversations_mark_read.py
git commit -m "feat(api): POST /conversations/:id/mark-read — reset unread count"
```

---

## Task 7: Unread bump in webhook handler

**Files:**
- Modify: `core/atendia/webhooks/meta_routes.py`

**Step 1: Add unread_count increment**

In `_persist_inbound` (line ~227), after the message INSERT and before the event emit, add:

```python
    # Bump unread count for the badge (scope gap: unread tracking)
    await session.execute(
        text("UPDATE conversations SET unread_count = unread_count + 1 WHERE id = :c"),
        {"c": conv_id},
    )
```

**Step 2: Commit**

```bash
git add core/atendia/webhooks/meta_routes.py
git commit -m "feat(webhook): bump unread_count on inbound message"
```

---

## Task 8: Update list endpoint — new filters + response fields

**Files:**
- Modify: `core/atendia/api/conversations_routes.py`

**Step 1: Update ConversationListItem model**

Add after `has_pending_handoff` (line 52):

```python
    assigned_user_id: UUID | None
    assigned_user_email: str | None
    unread_count: int
    tags: list[str]
```

**Step 2: Add query params to list_conversations**

Add new params to `list_conversations` signature (after `bot_paused`):

```python
    assigned_user_id: UUID | None = Query(None),
    unassigned: bool = Query(False),
    tag: str | None = Query(None),
```

**Step 3: Update the SELECT to include new columns**

In the `stmt` select (line ~155), add to the selected columns:

```python
            Conversation.assigned_user_id,
            Conversation.unread_count,
            Conversation.tags,
```

Also add an outerjoin for TenantUser:

```python
from atendia.db.models.user import TenantUser
```

```python
        .outerjoin(TenantUser, TenantUser.id == Conversation.assigned_user_id)
```

And select `TenantUser.email.label("assigned_user_email")`.

**Step 4: Add filter clauses**

After the existing filters:

```python
    if assigned_user_id is not None:
        stmt = stmt.where(Conversation.assigned_user_id == assigned_user_id)

    if unassigned:
        stmt = stmt.where(Conversation.assigned_user_id.is_(None))

    if tag is not None:
        # JSONB contains check: tags @> '["vip"]'
        stmt = stmt.where(Conversation.tags.contains([tag]))
```

**Step 5: Update the serialization loop**

In the `items` list comprehension (line ~209), add:

```python
            assigned_user_id=r.assigned_user_id,
            assigned_user_email=r.assigned_user_email,
            unread_count=r.unread_count,
            tags=r.tags or [],
```

**Step 6: Run existing tests to make sure nothing broke**

Run: `cd core && .venv/Scripts/python.exe -m pytest tests/api/test_conversations_routes.py -v`
Expected: All PASS (existing tests pass unchanged — new fields are additive)

**Step 7: Commit**

```bash
git add core/atendia/api/conversations_routes.py
git commit -m "feat(api): list conversations with assigned_user_id, unread, tags filters + fields"
```

---

## Task 9: Frontend types + API functions

**Files:**
- Modify: `frontend/src/features/conversations/api.ts`

**Step 1: Update ConversationListItem interface**

Add after `has_pending_handoff`:

```typescript
  assigned_user_id: string | null;
  assigned_user_email: string | null;
  unread_count: number;
  tags: string[];
```

**Step 2: Update ListConversationsParams**

Add:

```typescript
  assigned_user_id?: string;
  unassigned?: boolean;
  tag?: string;
```

**Step 3: Add new API functions**

```typescript
  patchConversation: async (
    id: string,
    body: { current_stage?: string; assigned_user_id?: string | null; tags?: string[] },
  ): Promise<unknown> => {
    const { data } = await api.patch(`/conversations/${id}`, body);
    return data;
  },
  deleteConversation: async (id: string): Promise<void> => {
    await api.delete(`/conversations/${id}`);
  },
  markRead: async (id: string): Promise<void> => {
    await api.post(`/conversations/${id}/mark-read`);
  },
```

**Step 4: Commit**

```bash
git add frontend/src/features/conversations/api.ts
git commit -m "feat(frontend): conversation API types + patch/delete/markRead functions"
```

---

## Task 10: Frontend ConversationList — mailbox tabs + unread badges + tag chips

**Files:**
- Modify: `frontend/src/features/conversations/components/ConversationList.tsx`

**Step 1: Update InboxTab type**

Change from:
```typescript
type InboxTab = "all" | "handoffs" | "paused";
```
To:
```typescript
type InboxTab = "all" | "mine" | "unassigned" | "handoffs" | "paused";
```

**Step 2: Update getStoredTab**

```typescript
function getStoredTab(): InboxTab {
  const stored = localStorage.getItem("conv_tab");
  if (stored === "mine" || stored === "unassigned" || stored === "handoffs" || stored === "paused") return stored;
  return "all";
}
```

**Step 3: Update filter mapping**

In the `filters` useMemo (line ~284), change to:

```typescript
  const user = useAuthStore((s) => s.user);

  const filters = useMemo(() => {
    const base = { limit: 100 };
    if (tab === "mine") return { ...base, assigned_user_id: user?.id };
    if (tab === "unassigned") return { ...base, unassigned: true };
    if (tab === "handoffs") return { ...base, has_pending_handoff: true as const };
    if (tab === "paused") return { ...base, bot_paused: true as const };
    return base;
  }, [tab, user?.id]);
```

Add import: `import { useAuthStore } from "@/stores/auth";`

**Step 4: Update counts useMemo**

```typescript
  const counts = useMemo(() => {
    const all = allItems;
    return {
      all: all.length,
      mine: tab === "mine" ? all.length : all.filter((c) => c.assigned_user_id === user?.id).length,
      unassigned: tab === "unassigned" ? all.length : all.filter((c) => c.assigned_user_id === null).length,
      handoffs: tab === "handoffs" ? all.length : all.filter((c) => c.has_pending_handoff).length,
      paused: tab === "paused" ? all.length : all.filter((c) => c.bot_paused).length,
    };
  }, [allItems, tab, user?.id]);
```

**Step 5: Update Tabs JSX**

Replace the TabsList with 5 tabs:

```tsx
<TabsList className="w-full">
  <TabsTrigger value="all" className="flex-1 gap-1">
    Todos <Badge variant="secondary" className="ml-1 h-4 px-1 text-[10px]">{counts.all}</Badge>
  </TabsTrigger>
  <TabsTrigger value="mine" className="flex-1 gap-1">
    Míos <Badge variant="secondary" className="ml-1 h-4 px-1 text-[10px]">{counts.mine}</Badge>
  </TabsTrigger>
  <TabsTrigger value="unassigned" className="flex-1 gap-1">
    Sin asignar
    {counts.unassigned > 0 && (
      <Badge variant="secondary" className="ml-1 h-4 px-1 text-[10px]">{counts.unassigned}</Badge>
    )}
  </TabsTrigger>
  <TabsTrigger value="handoffs" className="flex-1 gap-1">
    Handoffs
    {counts.handoffs > 0 && (
      <Badge variant="destructive" className="ml-1 h-4 px-1 text-[10px]">{counts.handoffs}</Badge>
    )}
  </TabsTrigger>
  <TabsTrigger value="paused" className="flex-1 gap-1">
    Pausados
    {counts.paused > 0 && (
      <Badge variant="secondary" className="ml-1 h-4 px-1 text-[10px]">{counts.paused}</Badge>
    )}
  </TabsTrigger>
</TabsList>
```

**Step 6: Add unread badge + tag chips to ConversationRow**

In `ConversationRow`, update the customer name line to bold when unread:

```tsx
<span className={cn("truncate text-sm font-medium", row.unread_count > 0 && "font-bold")}>
  {row.customer_name ?? row.customer_phone}
</span>
```

Add unread badge after the time:

```tsx
{row.unread_count > 0 && (
  <Badge className="ml-1 h-4 min-w-4 justify-center rounded-full bg-blue-600 px-1 text-[10px] text-white">
    {row.unread_count}
  </Badge>
)}
```

Add tag chips in the badges row, after the existing badges:

```tsx
{row.tags?.slice(0, 2).map((tag) => (
  <Badge key={tag} variant="outline" className="h-4 px-1 text-[10px] border-blue-300 text-blue-700">
    {tag}
  </Badge>
))}
{(row.tags?.length ?? 0) > 2 && (
  <Badge variant="outline" className="h-4 px-1 text-[10px]">
    +{row.tags.length - 2}
  </Badge>
)}
```

**Step 7: Commit**

```bash
git add frontend/src/features/conversations/components/ConversationList.tsx
git commit -m "feat(ui): mailbox tabs (mine/unassigned), unread badges, tag chips in conversation list"
```

---

## Task 11: Frontend context menu — change stage + delete + assign

**Files:**
- Modify: `frontend/src/features/conversations/components/ConversationList.tsx`

**Step 1: Import useMutation and add dependencies**

```typescript
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { conversationsApi } from "@/features/conversations/api";
```

Also add: `AlertTriangle, ChevronRight, UserPlus, UserMinus` to lucide imports.

**Step 2: Add stage list query**

The pipeline stages come from tenant config. For now, use a hardcoded commonly-used list or fetch from config. The simplest approach: extract unique stages from the already-loaded conversations:

```typescript
const allStages = useMemo(() => {
  const set = new Set(allItems.map((c) => c.current_stage));
  return Array.from(set).sort();
}, [allItems]);
```

**Step 3: Rewrite ConversationContextMenu**

Replace the existing `ConversationContextMenu` with a version that has:
- "Abrir conversación" (existing)
- "Copiar teléfono" (existing)
- Separator
- "Mover a etapa →" submenu with stage list
- "Asignar a mí" / "Desasignar" toggle
- Separator
- "Eliminar" (red, with Trash2 icon) — shows confirm dialog before calling DELETE

The context menu component receives `allStages: string[]` and `currentUserId: string` as additional props.

Use `useMutation` calls:
```typescript
const queryClient = useQueryClient();
const patchMutation = useMutation({
  mutationFn: (args: { id: string; body: Record<string, unknown> }) =>
    conversationsApi.patchConversation(args.id, args.body),
  onSuccess: () => queryClient.invalidateQueries({ queryKey: ["conversations"] }),
});
const deleteMutation = useMutation({
  mutationFn: (id: string) => conversationsApi.deleteConversation(id),
  onSuccess: () => queryClient.invalidateQueries({ queryKey: ["conversations"] }),
});
```

Stage submenu appears on hover/click of "Mover a etapa →":
```tsx
{allStages.filter((s) => s !== menu.conv.current_stage).map((stage) => (
  <button
    key={stage}
    className="flex w-full items-center gap-2 rounded-sm px-2 py-1.5 text-sm hover:bg-accent"
    onClick={() => {
      patchMutation.mutate({ id: menu.conv.id, body: { current_stage: stage } });
      onClose();
    }}
  >
    {stage}
  </button>
))}
```

Delete button with confirmation via `window.confirm`:
```tsx
<button
  className="flex w-full items-center gap-2 rounded-sm px-2 py-1.5 text-sm text-destructive hover:bg-accent"
  onClick={() => {
    if (window.confirm("¿Eliminar esta conversación? Esta acción no se puede deshacer fácilmente.")) {
      deleteMutation.mutate(menu.conv.id);
    }
    onClose();
  }}
>
  <Trash2 className="h-4 w-4" /> Eliminar
</button>
```

**Step 4: Commit**

```bash
git add frontend/src/features/conversations/components/ConversationList.tsx
git commit -m "feat(ui): context menu with change stage, assign/unassign, delete actions"
```

---

## Task 12: Frontend ConversationDetail — mark-read on mount

**Files:**
- Modify: `frontend/src/features/conversations/components/ConversationDetail.tsx`

**Step 1: Add mark-read call on mount**

Import and add a useEffect:

```typescript
import { useEffect } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { conversationsApi } from "@/features/conversations/api";
```

Inside `ConversationDetail`, add:

```typescript
const queryClient = useQueryClient();

useEffect(() => {
  if (conversationId) {
    conversationsApi.markRead(conversationId).then(() => {
      queryClient.invalidateQueries({ queryKey: ["conversations"] });
    });
  }
}, [conversationId, queryClient]);
```

This fires once per conversation open, resets unread_count to 0 server-side, and invalidates the list query so the badge disappears.

**Step 2: Commit**

```bash
git add frontend/src/features/conversations/components/ConversationDetail.tsx
git commit -m "feat(ui): mark conversation read on detail mount"
```

---

## Task 13: Frontend StageSidebar — AI agent grouping section

**Files:**
- Modify: `frontend/src/features/conversations/components/ConversationList.tsx`

**Step 1: Add AgentSidebar section above StageSidebar**

Add a new component inside ConversationList.tsx:

```typescript
function AgentSidebar({
  items,
  activeAgent,
  onSelect,
}: {
  items: ConversationListItem[];
  activeAgent: string | null;
  onSelect: (agent: string | null) => void;
}) {
  // Group by assigned_user_email (null = unassigned = "Bot")
  const agentCounts = useMemo(() => {
    const map = new Map<string, number>();
    for (const c of items) {
      const key = c.assigned_user_email ?? "Bot";
      map.set(key, (map.get(key) ?? 0) + 1);
    }
    return Array.from(map.entries()).sort((a, b) => b[1] - a[1]);
  }, [items]);

  if (agentCounts.length <= 1) return null;

  return (
    <div className="space-y-0.5">
      <div className="px-2 pb-1 text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
        Agentes
      </div>
      <button
        type="button"
        className={cn(
          "flex w-full items-center justify-between rounded-sm px-2 py-1 text-xs hover:bg-accent",
          activeAgent === null && "bg-accent font-medium",
        )}
        onClick={() => onSelect(null)}
      >
        <span>Todos</span>
        <span className="text-muted-foreground">{items.length}</span>
      </button>
      {agentCounts.map(([agent, count]) => (
        <button
          key={agent}
          type="button"
          className={cn(
            "flex w-full items-center justify-between rounded-sm px-2 py-1 text-xs hover:bg-accent",
            activeAgent === agent && "bg-accent font-medium",
          )}
          onClick={() => onSelect(activeAgent === agent ? null : agent)}
        >
          <span className="truncate">{agent}</span>
          <Badge variant="secondary" className="ml-1 h-4 px-1 text-[10px]">
            {count}
          </Badge>
        </button>
      ))}
    </div>
  );
}
```

**Step 2: Add state + filter for activeAgent**

In `ConversationList`, add:

```typescript
const [activeAgent, setActiveAgent] = useState<string | null>(null);
```

In the `visibleItems` useMemo, add after stage filter:

```typescript
    if (activeAgent) {
      items = items.filter((c) => (c.assigned_user_email ?? "Bot") === activeAgent);
    }
```

**Step 3: Render AgentSidebar in the sidebar Card**

In the sidebar Card (around line 362), add above StageSidebar:

```tsx
<AgentSidebar items={allItems} activeAgent={activeAgent} onSelect={setActiveAgent} />
<Separator className="my-2" />
<StageSidebar items={allItems} activeStage={activeStage} onSelect={setActiveStage} />
```

**Step 4: Commit**

```bash
git add frontend/src/features/conversations/components/ConversationList.tsx
git commit -m "feat(ui): AI agent grouping sidebar section in conversation list"
```

---

## Final: Run all backend tests

Run: `cd core && .venv/Scripts/python.exe -m pytest tests/api/ -v`
Expected: All PASS

---

## Post-implementation: Browser verification

Start dev servers and verify in browser at `http://localhost:5173`:
1. List shows unread badges, tag chips, assigned user indicators
2. Five mailbox tabs work (Todos, Míos, Sin asignar, Handoffs, Pausados)
3. Right-click context menu has: change stage submenu, assign/unassign, delete with confirm
4. Opening a conversation clears its unread badge
5. AI agent sidebar section groups conversations (visible when >1 agent)
6. Soft-deleted conversations disappear from list
