# Contact Memory v2

## Purpose

Contact Memory v2 makes customer/contact fields the safe operational memory for
Agent-First. `AgentRuntime` may propose `TurnOutput.field_updates`, but it still
does not write customer state directly. Updates must pass Contact Memory policy,
carry evidence/reason/confidence, and leave an audit row.

## Data Model

Existing field definitions and values stay in place:

- `customer_field_definitions`
- `customer_field_values`

Field policy is stored in `customer_field_definitions.field_options.contact_memory`
to avoid breaking the current ContactPanel contract:

```json
{
  "contact_memory": {
    "extractable_by_ai": true,
    "write_policy": "ai_auto",
    "confidence_threshold": 0.85,
    "evidence_required": true,
    "prompt_visible": true,
    "lifecycle_relevant": false,
    "pii": false,
    "sensitive": false
  }
}
```

New table:

- `customer_field_update_evidence`

It stores `field_key`, `old_value`, `new_value`, `source`,
`evidence_message_id`, `evidence_attachment_id`, `reason`, `confidence`,
`status`, `trace_id`, `created_by`, metadata and timestamps.

Allowed evidence statuses:

- `auto_applied`
- `suggested`
- `needs_review`
- `rejected`

## Policy

`ContactMemoryPolicy` evaluates each update:

- unknown field or wrong tenant: rejected;
- missing evidence when `evidence_required=true`: rejected;
- `human_only`: rejected for AI writes;
- `ai_suggest`: creates a pending field suggestion and does not overwrite;
- `ai_auto`: writes only if confidence reaches `confidence_threshold`;
- low confidence creates `needs_review` and does not overwrite.

Legacy definitions without `contact_memory` options default to safe behavior:
AI can extract, but writes are suggestions by default and evidence is required.

## Runtime Flow

1. The agent returns a single `TurnOutput`.
2. `PolicyValidator` validates `field_updates` for reason/evidence.
3. `PostTurnActionExecutor` can receive a `ContactMemoryService`.
4. When `dry_run=false`, the executor calls `ContactMemoryService.apply_turn_output`.
5. The service applies policy, writes `customer_field_values` only when allowed,
   creates `field_suggestions` for review paths, and always logs an evidence row
   when the customer is in the tenant.

Dry-run execution, including the test-turn harness, does not write Contact
Memory.

## AgentRuntime Contract

`FieldUpdate` now supports:

- `field_key`
- `value`
- `reason`
- `evidence`
- `confidence`
- `source`
- `evidence_message_id`
- `evidence_attachment_id`
- `trace_id`
- `metadata`

Sources are generic: `customer_message`, `ai_inference`, `knowledge`, `action`,
`human`, `workflow`, `vision`.

## Pending

- ContactPanel can surface evidence history and policy fields explicitly.
- Accept/reject suggestion routes still write legacy `customer.attrs`; a later
  task should route accepted suggestions through Contact Memory as well.
- Add UI controls for per-field write policy and confidence threshold.
