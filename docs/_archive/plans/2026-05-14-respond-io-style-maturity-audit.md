# AtendIA v2 — respond.io-style maturity audit (2026-05-14)

> **What this is.** A read-only audit of the four modules that carry the
> "respond.io for motorcycle credit" thesis: Pipeline Editor, AI Agent
> Editor, Workflow Builder, and the Conversation Surface (Inbox + Chat +
> Composer + ContactPanel + DebugPanel). For each: what exists today,
> what's still missing for a SaaS-grade feel, and a rough cost.
>
> **What this replaces.** `docs/handoffs/v1-v2-conversations-gap.md`
> (written 2026-05-08). Its still-open items have been absorbed into §4
> below. The old doc will be deleted after this one lands.
>
> **What this is NOT.** An implementation plan. No code. The user picks
> what to close and in what order. The working contract from the gap
> doc still applies (one component per session, no scope batches,
> verified before "done").

---

## Working contract (carried over from the 2026-05-08 gap doc)

| Rule | Why |
|---|---|
| **One component / one page per session.** Bigger scope → ask first. | Phase 4 shipped 60 tasks in one batch and oversold "complete" on every one. |
| **"Done" only when verified in the browser.** Scope-reduced ⇒ say so explicitly. | Multiple T-tasks landed at minimum-viable and were called done. |
| **The user picks what to cut.** Estimate cost (1h / 1d / 1w), they decide. | Previous session decided unilaterally to skip Tremor, Storybook, browser notifications, full E2E, etc. |
| **No green emojis until verified.** Summary = what changed + path + how to verify. | Self-celebratory tone hid that the deliverable was thin. |
| **No code-reviewer agent unless requested.** | Previous session ran review on Block A and C+D; rest got nothing. |
| **Branch per feature, show diff before merge.** | Previous session pushed straight to main. |

---

## Module 1 — Pipeline Editor

**Files audited:** `frontend/src/features/pipeline/components/{PipelineEditor.tsx (1954), PipelineKanbanPage.tsx (1345), RuleBuilder.tsx (486), DocumentRuleBuilder.tsx (289), StageDeleteDialog.tsx (236), AuditLogDrawer.tsx (175), UnsavedChangesGuard.tsx (30)}` + `api.ts`.

### What works today
- **Kanban view**: drag-drop between columns; KPI per stage (count, value_mxn, health_score, timeouts); orphan-stage detection with three rescue affordances.
- **Stage editor**: name/label/timeout/is_terminal/color; behavior_mode (PLAN/SALES/DOC/OBSTACLE/RETENTION/SUPPORT); pause_bot_on_enter + handoff_reason; allow_auto_backward; reorder; duplicate; delete with impact dialog + type-to-confirm.
- **Rule builder**: 10 operators (exists/equals/contains/greater_than/in/docs_complete_for_plan/…); AND-OR match logic; readable rule preview; JSON toggle.
- **Document catalog**: tenant-configurable DOCS_* with label + hint; auto-derive key from label; collision detection.
- **Plan-doc requirements**: docs_per_plan mapping; plan-aware `docs_complete_for_plan` operator.
- **Vision auto-write mapping**: classification → DOCS_* with per-category side order (INE frente/reverso).
- **Document Rule Builder** (M4 shorthand for "Papelería completa"): `all_validated` / `any_arrived` modes with checklist.
- **Audit log drawer**: event types (admin.pipeline.saved/deleted, stage_entered/exited); 50 rows + has_more.
- **Versioning hygiene**: dirty tracking, beforeunload guard, "Sin guardar" badge, version number in audit payload.
- **Stage delete impact**: queries `/pipeline/impacted-references/:id`, shows conversation count + workflow references, type-to-confirm only when impact > 0.

### Gaps for respond.io-grade maturity
| # | Sev | Gap | Cost |
|---|---|---|---|
| P1 | 🔴 | **Version rollback UI** — backend tracks versions, but no list/diff/restore UI. | 1-2d |
| P2 | 🔴 | **Test mode (simulate customer through pipeline)** — operators trial-and-error on live conversations. | ~1w |
| P3 | 🟠 | **Preview impact on in-flight conversations** when changing behavior_mode / rules. | 2-3d |
| P4 | 🟠 | **Per-stage permissions** (who can move customers into/out). | 3d |
| P5 | 🟠 | **Stage-level workflow trigger preview** ("when I enter this stage, these workflows fire"). | 1-2d |
| P6 | 🟠 | **Dependency view inside stage editor** (already queryable via impact endpoint, surface it). | 0.5d |
| P7 | 🟡 | **Bulk move N customers** (extend the orphan-rescue affordance). | 1d |
| P8 | 🟡 | **Stage templates / clone from another tenant**. | ~1w |
| P9 | 🟡 | **Confirmation dialog when toggling behavior_mode / pause_bot mid-pipeline**. | 1d |
| P10 | 🟡 | **Conflict detection** between auto-enter rules (warn if two stages match the same customer). | 1d |
| P11 | 🟡 | **Search / filter inside the editor** when pipeline grows beyond ~20 stages. | 0.5d |

### Don't touch
Rule builder design, doc catalog derivation, dirty-tracking, audit log structure, Vision mapping UX, stage-delete impact, JSON serialization round-trip.

---

## Module 2 — AI Agent Editor

**Files audited:** `frontend/src/features/agents/components/AgentsPage.tsx (2198)` + `api.ts`.

### What works today
- **Agent list / cards**: status (draft/validation/testing/production/paused), version, health score, intent icons, accuracy/risk metrics; search; **compare-mode** (pick two agents).
- **Identidad panel**: name/role/tone/style/language/max_sentences/objective/no_emoji/return_to_flow/is_default; 12 intent toggles.
- **Prompt maestro field**: textarea with explainer; collapsible "Prompt enviado al LLM" showing the assembled prompt.
- **Guardrails**: severity (critical/high/medium/low), enforcement_mode (block/rewrite/warn/handoff), allowed/forbidden examples, inline test; live "+ Agregar regla".
- **Knowledge source filter**: per-collection checkbox; default = full KB access.
- **LLM preview / test chat**: real `POST /agents/{id}/preview-response` with draftConfig → finalResponse, rawResponse, confidence, retrievedFragments, activatedGuardrails, extractedFields, supervisorDecision, trace.
- **Monitor**: active_conversations_24h, turns_24h, cost_24h, avg_latency_ms; turns_total, cost_total, last_turn_at; default-fallback warning.
- **Behavior modes**: normal/conservative/strict.
- **Validation pre-publish**: granular checks + summary.
- **Compare panel**: side-by-side agent diff + metrics.
- **Keyboard shortcuts**: ⌘K (palette), ⌘S (save), Esc (close), ? (help).
- **Lifecycle ops**: save (PATCH config), publish, rollback (latest only), disable, duplicate, export JSON.

### Gaps for respond.io-grade maturity
| # | Sev | Gap | Cost |
|---|---|---|---|
| A1 | 🔴 | **Version history + rollback picker** — API returns `versions[]` but UI never shows it. | 2-3d |
| A2 | 🔴 | **Side-by-side prompt diff** between versions. | 3-4d |
| A3 | 🔴 | **A/B test two prompt variants** against same input. | 4-5d |
| A4 | 🔴 | **Safe sandbox replay** — re-run last N real conversations against new prompt with no side effects. | 5-7d |
| A5 | 🟠 | **Per-action RBAC** (junior operator can toggle intents but not edit system prompt). | 3-4d |
| A6 | 🟠 | **Tool/action usage stats** (which tools the agent called, success rate). | 2-3d |
| A7 | 🟠 | **KB source priority order + per-source citation in test chat**. | 2-3d |
| A8 | 🟠 | **Token / cost meter per conversation** (Monitor only shows cost_24h). | 1-2d |
| A9 | 🟠 | **Latency budget / SLO alerts**. | 1d |
| A10 | 🟠 | **Cross-tenant prompt template library**. | 4-5d |
| A11 | 🟠 | **Audit log of prompt edits** with author + reason. | 2-3d |
| A12 | 🟡 | **Confirmation dialog before publish**. | 1d |
| A13 | 🟡 | **Live monitor drill-down** (failures, fallbacks, guardrail trips). | 2-3d |
| A14 | 🟡 | **Error inspector / failure trace**. | 1-2d |
| A15 | 🟡 | **"Why did the agent say X" link** from an outbound message → this editor's prompt + retrieval trace. | 3-4d |

### Don't touch
Identidad layout, Prompt maestro positioning, WhatsApp preview bubbles, guardrail enforcement modes, KB-collection checkbox UI, status colors, behavior-mode toggle, compare panel, validation pre-publish flow.

---

## Module 3 — Workflow Builder

**Files audited:** `frontend/src/features/workflows/components/{WorkflowEditor.tsx (1504), WorkflowsPage.tsx (1117)}` + `api.ts` + engine.

### What works today
- **List page**: health score (healthy/warning/critical/inactive), 24h metrics, success/failure %, leads affected, suggested_actions, sparklines, draft vs published version numbers.
- **Triggers (14 wired)**: message_received, conversation_created, conversation_closed, webhook_received (auto-generated URL), tag_updated, field_updated, field_extracted, stage_entered, stage_changed, appointment_created, bot_paused, document_accepted, document_rejected, docs_complete_for_plan, human_handoff_requested.
- **Node types with UI forms (9)**: template_message / message, assign_agent, move_stage, delay (s/m/h/d), condition, branch (multi-rule AND/OR with `else` label), http_request (GET/POST/PUT/PATCH/DELETE + timeout + raw-JSON headers/body + save_to), jump_to (capped at 100 steps), end.
- **Branch editor**: unlimited branches, multiple rules per branch (eq/neq/contains/exists/gt/lt/…), top-to-bottom evaluation, named else edge.
- **Variables tab**: extracted variables, where used (node indices), last value, status.
- **Dependencies tab**: workflow → agents/stages/pipeline references with status.
- **Simulator panel**: pre-publish test (incoming message + sample lead) → activated nodes, generated response, variables saved, warnings/errors, compare draft vs published.
- **Execution history**: per-workflow list with lead/phone/start/result; replay log with per-step node_id/label/status/detail; retry from failed node.
- **Node metrics**: entered / completed / dropoff / last_error per node.
- **Safety**: 7 safety_rules toggles (business_hours, max_3_messages_24h, dedupe_template, stop_on_no, stop_on_human, stop_on_frustration, pause_on_critical); 4 pause modes (immediate / new_leads / after_active / handoff_human).
- **Import/export**: JSON ≤400KB, ≤100 nodes, ≤150 edges; strips foreign IDs; auto-renumbers on collision; clipboard copy on export.
- **Validation pre-flight**: critical_count + warning_count gating publish.
- **Idempotent actions**: `WorkflowActionRun(execution_id, action_key)` prevents duplicate sends on retry.
- **24h WhatsApp window check** with `OUTSIDE_24H_WINDOW` error code.

### Gaps for respond.io-grade maturity
| # | Sev | Gap | Cost |
|---|---|---|---|
| W1 | 🔴 | **Visual canvas (DAG with arrows)** — current view is a vertical list. Hard to read graphs >30 nodes. | ~1w |
| W2 | 🔴 | **Visual debugger / step-through** — pause at a node, inspect variables. Replay is logs-only. | ~1.5w |
| W3 | 🟠 | **Per-node retry policy** (max retries, backoff, dead-letter). Today only whole-execution retry. | 2-3d |
| W4 | 🟠 | **Design-time loop detection** (engine caps at 100 steps; nothing warns the operator while editing). | 1.5d |
| W5 | 🟠 | **Reverse dependency view**: "which workflows reference this agent / stage" (paired with P6 + A11). | 1-1.5d |
| W6 | 🟠 | **Sub-workflow step** ("Trigger Another Workflow"). | ~1w |
| W7 | 🟠 | **Update Field / Pause Bot UI forms** — node types exist in engine; no editor form (JSON-edit today). | 1d |
| W8 | 🟡 | **Canvas comments / annotations**. | 1.5d |
| W9 | 🟡 | **Auto-layout for arrows** (depends on W1). | 2-3d |
| W10 | 🟡 | **Test-mode that doesn't fire real HTTP / sends** (simulator hits the same queue today). | 1.5d |
| W11 | 🟡 | **Confirmation before publishing destructive nodes** (delete cascades, mass sends). | 1d |
| W12 | 🟡 | **Rollback to any version** (current `/restore` is hardcoded to v12). | 0.5-1d |
| W13 | 🟡 | **Inline variable picker / autocomplete** in template & http_request forms. | 1.5d |
| W14 | 🟡 | **Node-disabled visual indicator** (toggle exists; node header doesn't reflect it). | 0.5d |
| W15 | 🟡 | **Execution log export** (CSV/JSON). | 1d |
| W16 | 🟡 | **Performance hints** (heavy branch, long HTTP timeout). | 1d |

### Don't touch
Trigger catalog (all 14 wired), validation pre-flight, safety rules, pause modes, import sanitization, idempotent action runs, 24h-window guard, node metrics, health scoring + suggested actions.

---

## Module 4 — Conversation surface (absorbs the unfinished `v1-v2-conversations-gap.md`)

**Files audited:** `frontend/src/features/conversations/components/{ConversationsPage.tsx (1984), ChatWindow.tsx (78), MessageBubble.tsx (121), MediaContent.tsx (62), SystemEventBubble.tsx (203), InterventionComposer.tsx (109), ContactPanel.tsx (1854), EditableDetailRow.tsx (200), AddCustomAttrDialog.tsx (148), FieldSuggestionsPanel.tsx (89), DebugPanel.tsx (112)}` + `features/turn-traces/components/TurnTraceSections.tsx (303)`.

### Status of the 7 original gap items (from `v1-v2-conversations-gap.md`)
| # | Gap | Status today | Evidence |
|---|---|---|---|
| 1 | Conversation list (left rail) | 🟠 **PARTIAL** — `ConversationsPage` is 1984 LOC with FilterRail (unread/mine/unassigned/awaiting_customer/stale), persisted tabs, full-pipeline filter sync, search w/ diacritic strip. Still missing: mailbox sections by AI agent + by pipeline stage, right-click context menu (state defined but action set thin), unread-tracking, lock indicator, tag column, AI-agent column, origin attribution column. | ConversationsPage:104-180 |
| 2 | WhatsApp status badge | 🔴 **OPEN** — header still shows only `Tenant: <uuid>`; no `/whatsapp/status` polling, no circuit breaker indicator. | ConversationDetail:91-111 |
| 3 | Chat window | 🟢 **CLOSED** — `ChatWindow + MessageBubble + MediaContent + SystemEventBubble` together cover media render, internal-notes strip, click-to-debug, 7 system event types. Polish remaining: per-message edit/delete (copy works). | MessageBubble:51-77 |
| 4 | Composer | 🟠 **PARTIAL** — `InterventionComposer` has takeover-toggle + ⌘/Ctrl+Enter; still missing slash-commands, snippet/template browser, dynamic-variable picker, AI suggest. | InterventionComposer:62-107 |
| 5 | ContactPanel (right side) | 🟢 **CLOSED** at 1854 LOC — identity edit, custom fields with dynamic schema, EditableDetailRow, AddCustomAttrDialog, FieldSuggestionsPanel with NLU accept/reject, notes hooks wired. Polish: collapsible 12px↔320px drawer; notes pin/edit-in-place UI confirmation. | ContactPanel:321-486 |
| 6 | DebugPanel (per-message inspector) | 🔴 **OPEN** — only 112 LOC. Wraps `TurnTraceSections` (303 LOC) with 7 sections: Overview, Pipeline (NLU/Composer/Vision bars), NLU, Composer, ToolCalls, State, Errors. **Missing ~9 of v1's blocks** (see below). | DebugPanel.tsx + TurnTraceSections.tsx |
| 7 | WebSocket / real-time | 🟡 **PARTIAL** — `useConversationStream + useTenantStream` work but over-invalidate (Block C+D review note). Not blocking, eats DB. | ConversationsPage:66, ConversationDetail:6 |

### Gaps absorbed from #6 DebugPanel (the biggest hole)
v1's `DebugPanel.jsx` (497 LOC) had these blocks; v2's DebugPanel (112 LOC + 303 LOC of sections) covers only ~40% of them:

| Block | v2 status |
|---|---|
| Mode + trigger rule text | 🔴 missing |
| Intent + confidence % bar | 🔴 missing |
| Recorrido (flow journey): cleaned text, agent name/role/tone, history count, LLM provider, response origin (template/model/fallback), media kind+MIME+classification confidence, fact pack JSON, **LLM raw vs final** (catches post-processing) | 🔴 missing |
| Per-step cards with status (info/warning/error) | 🔴 missing — sections are flat JSON, no per-step drill-down |
| Entities (green = saved, yellow = extracted-but-not-saved pills) | 🔴 missing |
| Knowledge use (source priority list, enabled/consulted/used badges, hits per source, items used with KB article IDs, citas with snippet + similarity score + filename) | 🔴 missing — biggest deficit for AI-agent debugging |
| Actions list (state-changing actions per turn) | 🔴 missing |
| Pipeline latency bars per stage | 🟢 partial — v2 has NLU/Composer/Vision; missing classify/entity_extract/mode_route/action_engine breakdown |
| LLM (model + tokens + template format/sentences/CTA analysis) | 🟢 partial — model + tokens shown; template analysis missing |
| Rules evaluated (pass/fail per rule) | 🔴 missing |
| Errors | 🟢 closed |

### Gaps for the conversation surface (consolidated)
| # | Sev | Gap | Cost |
|---|---|---|---|
| C1 | 🔴 | **WhatsApp status badge** in header (poll `/whatsapp/status` + `/automation-config/status` every 10s; green/amber/red + WA-pausado label). Backend may need both endpoints (verify). | 0.5-1d |
| C2 | 🔴 | **DebugPanel rebuild**: Mode + Intent bar + Recorrido per-step + Entities pills + Knowledge sources w/ scores + Actions + per-step pipeline bars + Rules + LLM raw-vs-final. Will likely need turn_traces schema additions (flow_steps JSONB, fact_pack, kb_evidence). | 1-2 sessions |
| C3 | 🟠 | **Conversation list mailbox sections** — by AI agent + by pipeline stage with live counts (and: unread-tracking, lock indicator, tags column, origin column, AI-agent column). | 2-3 sessions |
| C4 | 🟠 | **Right-click context menu** in conversation list (move-to-stage exists; add assign, close, archive, tag, etc.). | 1-1.5d |
| C5 | 🟠 | **Composer slash-commands + snippet browser** (templates deferred per user; snippet/variable picker still valuable). | 2-3d |
| C6 | 🟡 | **ContactPanel collapsible drawer** (12px ↔ 320px width). | 0.5d |
| C7 | 🟡 | **Notes pin/edit-in-place UI verification** — hooks are imported, confirm UI renders. | 0.5d |
| C8 | 🟡 | **WS targeted patches** (replace bulk invalidation with per-event mutation). | 1.5d |
| C9 | 🟡 | **Per-message edit/delete** actions (copy works). | 1d |

---

## Recommended sequencing (user decides)

Two themes, picked from the audit:

### Theme A — Observability foundation (one cohesive arc)
This is what unblocks evaluation of every other module. Cost: ~1.5 sessions.

1. **C2 — DebugPanel rebuild** (Mode + Intent bar + Recorrido + Entities + Knowledge w/ scores + Actions + per-step pipeline bars + Rules + LLM raw vs final).
   - May require backend additions to `turn_traces` (flow_steps JSONB, fact_pack, kb_evidence).
2. **C1 — WhatsApp status badge** (tied to operations confidence).
3. **A15 — "Why did the agent say X" link** from outbound message → AgentEditor's prompt + retrieval trace. Cheap glue once C2 lands.

### Theme B — Pipeline + Agent governance (parallel arc)
This is the "looks like a SaaS" pass for the two flagship editors. Cost: ~1 week.

1. **P1 — Pipeline version rollback UI**.
2. **A1 — Agent version history + rollback picker**.
3. **A11 — Audit log of agent prompt edits**.
4. **A12 + W11 — Confirmation dialogs before publish** (agents + workflows).
5. **P6 — Stage dependency view inside editor**.
6. **W5 — Workflow reverse-dependency view** (closes the loop with P6 + A6).

### What to defer
- **Test/sandbox features** (P2, A3, A4, W2, W10) — high cost, high value but only after Theme A makes failures observable.
- **A/B testing + multi-tenant template libraries** (A3, A10, P8) — post-PMF.
- **Visual canvas for workflows** (W1) — most expensive item in the audit, deferrable until a workflow exceeds ~25 nodes.
- **Bulk ops / search / templates in editors** — quality-of-life, not blocking.

---

## Verification commands

```powershell
# Re-check line counts when this doc gets stale
Get-ChildItem -Recurse frontend/src/features/{pipeline,agents,workflows,conversations,turn-traces}/components/*.tsx |
  ForEach-Object { "{0,6} {1}" -f (Get-Content $_.FullName | Measure-Object -Line).Lines, $_.FullName }

# Bring v2 up
powershell -ExecutionPolicy Bypass -File scripts/start-demo.ps1

# Demo creds
# admin@demo.com / admin123
# dele.zored@hotmail.com / dinamo123 (superadmin)
```

---

**Next concrete action (when the user picks):** start Theme A → C2 DebugPanel rebuild. Step 1 is a 1-session backend check: does `turn_traces` already record `flow_steps`, `fact_pack`, `kb_evidence`, or does it need migration? No UI code until that's answered.
