# Conversations Scope Gaps — v1 Parity Design

**Date:** 2026-05-08
**Branch:** claude/cool-lamport-8260e1
**Scope:** 6 features closing the remaining v1→v2 Conversations page gaps

## Context

Steps 1–6 of the conversations rebuild are complete. Six features remain that
require backend model changes: assigned agent, unread tracking, context menu
actions (change stage + delete), tags, and AI agent sidebar grouping.

Audit result: v1 has **no standalone pages** beyond Conversations — Handoffs,
Customers, Analytics, Config, etc. already exist only in v2. No other-page gaps
to close.

## Approach: Lean Columns (Option A)

Single migration, columns on `conversations`, free-form JSONB tags, soft delete,
per-conversation unread count reset on open. AI agent grouping derived from
tenant config client-side.

## 1. Database Migration

Single migration adds four columns to `conversations`:

| Column             | Type                          | Default  | Notes                                      |
|--------------------|-------------------------------|----------|--------------------------------------------|
| assigned_user_id   | UUID FK → tenant_users.id     | NULL     | NULL = unassigned                          |
| unread_count       | INTEGER                       | 0        | Bumped on inbound, reset to 0 on open      |
| tags               | JSONB                         | '[]'     | Array of strings, e.g. ["vip","urgent"]    |
| deleted_at         | TIMESTAMPTZ                   | NULL     | Non-null = soft-deleted, excluded from list |

Indexes:
- `idx_conversations_assigned_user_id` on assigned_user_id
- `idx_conversations_not_deleted` partial on (tenant_id) WHERE deleted_at IS NULL

Unread bump: in `_persist_inbound` (meta_routes.py), after inserting the message:
`UPDATE conversations SET unread_count = unread_count + 1 WHERE id = :conv_id`

Unread reset: `POST /conversations/:id/mark-read` sets `unread_count = 0`.

## 2. API Endpoints

Four new endpoints on conversations_routes.py:

| Method | Path                             | Body                                          | Effect                                          |
|--------|----------------------------------|-----------------------------------------------|--------------------------------------------------|
| PATCH  | /conversations/:id               | { current_stage?, assigned_user_id?, tags? }  | Partial update, validates stage vs pipeline config |
| DELETE | /conversations/:id               | —                                             | Sets deleted_at = now(), returns 204              |
| POST   | /conversations/:id/mark-read     | —                                             | Sets unread_count = 0, returns 204                |
| GET    | /conversations (modified)        | +assigned_user_id, +unassigned, +tag params   | Existing list gains 3 filters, excludes deleted   |

Response shape changes — ConversationItem gains:
- assigned_user_id: str | null
- assigned_user_email: str | null (joined from tenant_users)
- unread_count: int
- tags: list[str]

Audit trail: PATCH and DELETE emit CONVERSATION_UPDATED / CONVERSATION_DELETED
via the existing EventEmitter.

## 3. Frontend — Conversation List

Mailbox tabs replace current "all | handoffs | paused":

| Tab         | API filter                          | Badge |
|-------------|-------------------------------------|-------|
| Todos       | {}                                  | total |
| Mios        | assigned_user_id={current_user_id}  | count |
| Sin asignar | unassigned=true                     | count |
| Handoffs    | has_pending_handoff=true            | count |
| Pausados    | bot_paused=true                     | count |

Persisted to localStorage.

ConversationRow gains:
- Unread badge: blue circle with count, bold text when unread_count > 0
- Tag chips: small badges after stage badge, max 2 + "+N" overflow
- Assigned user indicator: small avatar/initials when assigned

Context menu wiring:
- "Mover a etapa" submenu → pipeline stages from config → PATCH { current_stage }
- "Eliminar" with confirmation → DELETE
- "Asignar a mi" / "Desasignar" → PATCH { assigned_user_id }

Mark-read: ConversationDetail calls POST /conversations/:id/mark-read on mount,
invalidates list query so badge clears.

## 4. Frontend — AI Agent Sidebar Grouping

StageSidebar gains a second section above stages:
- Heading: "Agentes IA"
- Groups conversations by AI agent name from tenant pipeline config
- Each row: agent name + count badge
- Click to filter list by agent
- Hidden when tenant has only one agent

Client-side grouping on already-fetched data — no new endpoint.

## Decisions

- **Unread reset**: on conversation open (not scroll-aware)
- **Tags**: free-form JSONB array (no predefined taxonomy)
- **Delete**: soft delete via deleted_at (reversible)
- **AI agent grouping**: derived from config, not stored on conversation
- **Per-user unread**: not needed — single operator per tenant assumption
