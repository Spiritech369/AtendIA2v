# Agents Surface Real Data Audit - Dinamo

Date: 2026-06-02

Tenant:

- tenant_id: `6ad78236-1fc9-467a-858d-90d248d57ee5`
- email: `dinamomotosnl@gmail.com`
- agent_id: `c169deec-226d-55b7-bd07-270f339e75a6`

## Verdict

Agent Studio is partially DB-backed and safe for preview review, but the Agents dashboard still mixes real DB-backed panels with heuristic or stale-looking widgets. Anything not proven DB-backed should be hidden or badged before live operator use.

No agent action was executed during this audit.

## API Evidence

| Endpoint | Result | Classification |
| --- | --- | --- |
| `GET /api/v1/agents` | Returned `Francisco de Dinamo NL` for the Dinamo tenant | REAL_DATA |
| `GET /api/v1/agents/studio/knowledge-sources` | Returned 5 Knowledge OS sources | REAL_DATA |
| `GET /api/v1/agents/studio/contact-fields` | Returned 11 contact fields | REAL_DATA |
| `GET /api/v1/agents/studio/lifecycle-stages` | Returned 8 lifecycle stages | REAL_DATA |
| `GET /api/v1/agents/studio/actions` | Returned action definitions/options | REAL_DATA, CONFIG_ONLY |
| `GET /api/v1/agents/{agent_id}/workflows` | Returned `[]` despite 4 tenant workflows | BROKEN |
| `GET /api/v1/agents/{agent_id}/health` | Returned score/status | PARTIAL, needs DB trace badge |
| `GET /api/v1/agents/{agent_id}/knowledge-coverage` | Returned coverage metrics | PARTIAL, needs DB trace badge |

## Real Panels

These panels are acceptable when shown as tenant DB config:

- Agent identity/config
- Knowledge sources
- Contact fields
- Lifecycle stages
- Action catalog/options, as configuration only
- Runtime v2 preview/test-turn controls, as preview only

## Panels Requiring Badge Or Hide

- Health score
- Risk radar
- Knowledge coverage score
- Scenario pass/fail summaries
- Onboarding readiness summaries
- Linked workflows, until endpoint returns the tenant workflows

## Required Fixes

1. Fix `GET /api/v1/agents/{agent_id}/workflows` so it returns the tenant workflows or an explicit explanation of why none are linked.
2. Badge heuristic metrics as `PREVIEW`, `HEURISTIC`, or `NEEDS_EVIDENCE`.
3. Avoid presenting seeded/static dashboard widgets as production evidence.
4. Keep all action controls disabled for send/execution until explicit production readiness gates pass.

