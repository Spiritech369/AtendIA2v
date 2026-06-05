# Dinamo Single Contact Smoke Post Report Template

Generated: 2026-06-03T23:52:46-06:00

Use this only after a human-approved single-contact smoke actually runs.

## Run Metadata

- start_time:
- end_time:
- tenant_id: 6ad78236-1fc9-467a-858d-90d248d57ee5
- agent_id: c169deec-226d-55b7-bd07-270f339e75a6
- approved_phone: +528212889421
- approved_contact_id:
- real_turns:
- operator_monitor:
- rollback_owner:

## Transcript

Paste anonymized transcript here.

## Final Messages

List each customer-facing `TurnOutput.final_message`.

## Tool Usage

- tools_called:
- tool_results:
- unexpected_tools:

## StateWriter

- accepted:
- blocked:
- notes:

## Business Events

- events_emitted:
- dry_run_events:
- real_events:

## Workflow Results

- workflow_results:
- real_side_effects:

## Provider Metrics

- provider_invoked:
- provider_retry_count:
- provider_retry_exhausted_count:
- provider_fallback_count:
- provider_fallback_response_count:

## Quote Safety

- quote_snapshot_present:
- stale_quote_count:
- price_without_quote_count:
- cash_quote_when_credit_requested:
- requirements_mixed_count:

## Document Handling

- attachments_received:
- document_received_without_attachment:
- document_check_results:

## Human Review

- reviewer:
- human_review_score:
- high_risk_conversations:
- notes:

## Decision

Allowed values:

- `SMOKE_PASS_REPEAT_WITH_2_3_CONTACTS`
- `SMOKE_PASS_READY_FOR_LIMITED_CANARY_PREP`
- `SMOKE_NEEDS_FIXES`
- `SMOKE_ROLLBACK_REQUIRED`

Decision:
