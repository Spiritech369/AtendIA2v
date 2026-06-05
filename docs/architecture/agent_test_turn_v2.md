# Agent Test Turn v2

## Purpose

`POST /api/v1/agents/{agent_id}/test-turn-v2` is a backend-only test harness for
the Agent-First runtime. It lets operators validate `agent_runtime_v2` with
Knowledge OS citations before wiring the runtime into real conversations.

The endpoint is intentionally safe:

- no WhatsApp send;
- no outbound message persistence;
- no real conversation row required;
- no customer field writes;
- no lifecycle or pipeline move;
- no workflow trigger;
- actions are evaluated with `PostTurnActionExecutor(dry_run=True)`.

## Access

The route uses the normal authenticated tenant scope and requires
`tenant_admin` or `superadmin`. The `agent_id` must belong to the current
tenant, otherwise the endpoint returns `404`.

## Request

```json
{
  "test_message": "What are support hours?",
  "conversation_history": [
    {"role": "customer", "text": "Hi"}
  ],
  "contact_fields": [
    {"key": "email", "label": "Email", "field_type": "text"}
  ],
  "lifecycle_stage": "qualification",
  "knowledge_source_ids": [],
  "metadata": {"scenario": "smoke"}
}
```

`knowledge_source_ids` is optional. In this MVP it filters legacy FAQ/document
sources adapted into Knowledge OS v2 citation shape for the test run.

## Response

```json
{
  "final_message": "...",
  "knowledge_citations": [],
  "field_updates": [],
  "lifecycle_update": null,
  "actions": [],
  "confidence": 0.72,
  "needs_human": false,
  "risk_flags": [],
  "trace_metadata": {},
  "debug": {
    "context_summary": "tenant=...; messages=1; citations=0; stage=none",
    "retrieval": {"enabled": true, "answerable": false, "citation_count": 0},
    "policy": {"valid": true, "issues": []},
    "actions": {"dry_run": true, "results": []},
    "side_effects": {
      "persisted_messages": false,
      "sent_whatsapp": false,
      "updated_customer_fields": false,
      "moved_lifecycle": false,
      "triggered_workflows": false
    }
  }
}
```

## Example

```bash
curl -X POST "http://localhost:8000/api/v1/agents/$AGENT_ID/test-turn-v2" \
  -H "Content-Type: application/json" \
  -H "X-CSRF-Token: $CSRF" \
  --cookie "atendia_session=$SESSION" \
  -d '{"test_message":"What are support hours Monday?"}'
```

## Implementation Notes

The endpoint builds a synthetic `TurnContext` through `ContextBuilder`, injects
the selected agent as `active_agent`, retrieves Knowledge OS-style evidence from
tenant-scoped legacy KB rows, and runs `AgentRuntime`.

This is not yet Eval Lab persistence. It is a dry-run request/response harness
for backend validation.

## Pending

- Persist named test scenarios and expected assertions.
- Use native `knowledge_sources/items/chunks` once migration 058 is applied in
  all environments.
- Add frontend Test Chat / Eval Lab UI.
- Add LLM provider selection for real agent responses.
