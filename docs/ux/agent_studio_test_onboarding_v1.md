# Agent Studio, Test Chat, and Onboarding Readiness UI v1

## Flow

Tenant admins can open Agents and use:

- Agent Studio tab: edit instructions, tone, language policy, knowledge sources, actions, visible fields, and lifecycle stages.
- Test Chat v2: run a dry-run turn, keep local history, inspect final message, citations, field updates, lifecycle changes, actions, risk, confidence, and policy/debug payloads.
- Runtime v2 tab: inspect why-this-answer, shadow analytics, pilot report, and readiness from one operational surface.
- Onboarding readiness: validate the onboarding checklist and request publish-readiness from the existing backend endpoint.

## Endpoints

The UI uses the existing backend contract:

- `GET/PATCH /api/v1/agents/{agent_id}/config`
- `GET /api/v1/agents/studio/actions`
- `GET /api/v1/agents/studio/knowledge-sources`
- `GET /api/v1/agents/studio/contact-fields`
- `GET /api/v1/agents/studio/lifecycle-stages`
- `POST /api/v1/agents/{agent_id}/test-turn-v2`
- `GET /api/v1/turn-traces/{trace_id}/why-answer-v2`
- `GET /api/v1/agent-runtime-v2/shadow-report`
- `GET /api/v1/agent-runtime-v2/pilot-report`
- `GET /api/v1/onboarding/state`
- `POST /api/v1/onboarding/validate`
- `POST /api/v1/onboarding/publish-readiness`

## Safety

The Test Chat keeps actions in dry-run mode and does not persist conversation messages. Runtime v2 operations are read-only: shadow report, pilot report, and why-this-answer do not execute actions, publish workflows, send WhatsApp messages, or touch outbox. Readiness evidence can be saved explicitly from the test panel when the tenant admin enables it.

## Runtime v2 Operations

The `Runtime v2` tab is intentionally compact:

- Shadow report shows sample size, average confidence, policy blocks, v2-empty counts, top risk flags, policy issues, knowledge sources, and recent examples.
- Pilot report shows sends, policy failures, confidence, knowledge gaps, actions, field/lifecycle suggestions, and error rate.
- Why-this-answer accepts a trace id and optional conversation id, then shows final message, confidence, citations, actions, field updates, lifecycle, policy, workflow/readiness context, and the human summary.
- Onboarding readiness remains visible below the runtime reports so a tenant admin can connect test/eval outcomes to publish blockers.

## Remaining UX Gaps

- No full onboarding wizard yet.
- No Workflow Canvas integration.
- Readiness eval uses the existing publish-readiness endpoint; there is no separate frontend route for a full eval suite runner yet.
- Shadow/pilot charts are numeric cards only; trend graphs can come after real pilot volume exists.
