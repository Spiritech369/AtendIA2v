# Dinamo OpenAI Provider Approval Record - 2026-06-02

- approval_status: `approved`
- approver: `tenant operator explicit approval`
- tenant_id: `6ad78236-1fc9-467a-858d-90d248d57ee5`
- agent_id: `c169deec-226d-55b7-bd07-270f339e75a6`
- provider: `openai`
- model: `gpt-4o-mini`
- retention mode: `provider_default_no_secret_logging`
- region/data policy: `safe-preview-no-send`
- scope: `test-turn / preview / simulation / shadow no-send only`
- send_enabled: `false`
- manual_send_enabled: `false`
- auto_send_enabled: `false`
- actions_enabled: `false`
- workflow_events_enabled: `false`
- outbox_enabled: `false`
- allowed data categories: `latest customer message, minimal recent conversation history, limited Knowledge OS snippets/citations, lifecycle stage/status, available contact field schema, agent instructions, allowed action identifiers, citations`
- forbidden data categories: `API keys, tokens, secrets, attachments, full conversation history, full internal config, real write results, unnecessary phone numbers, unnecessary emails, WhatsApp media`
- payload minimization: `redact phone/email-like values when not needed; send only required knowledge snippets; log only payload hash/summary, not full sensitive payload; never log OPENAI_API_KEY`

This approval is restricted to AgentRuntime v2 provider testing for the tenant and agent above. It does not approve WhatsApp sends, outbox writes, real actions, manual-send, auto-send, or workflow event execution.
