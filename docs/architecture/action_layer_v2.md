# Action Layer v2

## Purpose

Action Layer v2 executes post-turn side effects from `TurnOutput.actions` after
the agent has produced the final message and after `PolicyValidator` has
approved the output.

The action layer does not compose, return or send customer-visible copy. Any
visible response must stay in `TurnOutput.final_message`.

## Registry Contract

Each registered action has:

- `id`
- `name`
- `description`
- `input_schema`
- `permissions`
- `capabilities`
- `risk_level`
- `requires_evidence`
- `requires_approval`
- `execution_mode`
- optional handler

Unknown or disabled actions are rejected before execution.

## Implemented Actions

`update_contact_field`

- Uses `ContactMemoryService`.
- Requires evidence.
- Applies the field write policy for the tenant and field definition.
- May auto-apply, suggest, need review or reject.

`move_lifecycle`

- Uses `LifecycleService`.
- Requires evidence and reason.
- Validates tenant ownership and stage transitions.
- Writes lifecycle history through `LifecycleService`.

`add_tag`

- Updates `conversations.tags`.
- Validates conversation tenant ownership.
- Deduplicates tags.

`assign_conversation`

- Updates `assigned_user_id` and/or `assigned_agent_id`.
- Validates target user/agent belongs to the same tenant.
- Supports explicit unassign.

`close_conversation`

- Updates `conversations.status` to `closed` or `resolved`.
- Requires evidence.

`trigger_workflow`

- Requires approval and evidence.
- Validates workflow tenant ownership and active status.
- Creates a `workflow_executions` row.
- Worker enqueue remains P2 so this action cannot silently run arbitrary
  workflow side effects in this base layer.

`call_webhook`

- Requires approval and evidence.
- Currently a safe audited stub. There is no generic outbound webhook dispatcher
  in the action layer yet.

## Execution Rules

`PostTurnActionExecutor`:

- validates with `PolicyValidator`;
- respects `dry_run`;
- blocks real side effects while `agent_runtime_v2_enabled=false`, unless a test
  or explicit caller opts out;
- executes actions in order;
- enforces `agent_runtime_v2_max_actions_per_turn`;
- supports `agent_runtime_v2_action_failure_policy` as `continue` or `stop`;
- records action results when a DB session and context are provided.

Dry-run action results are machine-readable and never mutate data.

## Audit Log

New table:

- `action_execution_logs`

Fields:

- `tenant_id`
- `conversation_id`
- `action_id`
- `input`
- `status`
- `result`
- `error`
- `dry_run`
- `trace_id`
- `created_at`

The log records successes, policy blocks, dry-runs, unknown actions and handler
errors.

## Safety Boundaries

Actions cannot:

- include `final_message`, `message`, `reply`, `text` or other visible-copy keys
  in `ActionResult.data`;
- bypass `PolicyValidator`;
- execute unknown registry entries;
- cross tenant boundaries;
- send WhatsApp messages;
- move lifecycle or write contact fields directly from `AgentRuntime`.

## P2 Actions

- `create_appointment`
- `reschedule_appointment`
- `cancel_appointment`
- `create_estimate`
- `send_media`
- `request_document`
- `create_task`
- `notify_team`
- generic outbound `call_webhook` dispatcher with allowlists, retries and
  secrets handling
- workflow enqueue/resume integration for `trigger_workflow`
