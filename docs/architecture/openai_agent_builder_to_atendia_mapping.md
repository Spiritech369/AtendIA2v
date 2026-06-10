# OpenAI Agent Builder To AtendIA Mapping

Date: 2026-06-06  
Status: Active mapping  
Official source reviewed: https://developers.openai.com/api/docs/guides/agent-builder/migrate-from-agent-builder

## Mapping Table

| OpenAI Concept | AtendIA Equivalent | Current State | Gap | Risk | Recommendation | Priority |
|---|---|---|---|---|---|---|
| Agent Builder | Agent Builder Control Plane | Documented Product-First target | Needs product UI/API implementation later | Runtime patches continue without product contract | Build tenant-scoped agent drafts, versions, publish gates | P1 |
| Workflow export | Workflow-to-agent migration input | No export path adopted | AtendIA workflows are not guaranteed agent-compatible | Blind migration changes behavior | Treat export/migration as review artifact, not truth | P1 |
| Agents SDK | AgentService runtime equivalent | Runtime V2/AgentService exists but needs single-route hardening | Test/live path divergence risk | Smoke passes but live differs | Define AgentService request/result and parity gates | P1 |
| Workspace Agent | Optional team-builder inspiration | Not AtendIA runtime | Workspace agent is not tenant inbox runtime | Loss of tenant control/send policy | Use as UX inspiration only | P3 |
| Tools | Tenant-aware tools | Existing tool layer/docs | Need source/auth/permission readiness | Tool claims without validation | Tool bindings + source-backed validation | P1 |
| Skills | Reusable capability packages | Not productized | Capabilities can sprawl | Hidden behavior and permissions | Map to approved tool/action bundles later | P2 |
| Auth / permissions | Tenant permissions, secrets, action policy | Partially documented | Needs product gate | External side effects unsafe | Block publish without auth/permission readiness | P1 |
| Preview | DB-backed Test Lab | Documented Product-First target | Must be implemented later | Fixture-only readiness | Test Lab uses same AgentService route no-send | P1 |
| Representative inputs | Test Lab scenarios | Acceptance tests documented | Need tenant scenario library | Missed edge cases | Store scenarios per agent version/deployment | P1 |
| Deployment | Publish Control | Documented Product-First target | Must replace scattered flags | Unsafe live activation | Deployment state machine + approval + rollback | P1 |
| Safety practices | Policy + Publish Control + Trace | Documented target | Needs implementation proof later | Unsafe actions or claims | Fail closed on policy/tool/source gaps | P1 |
| Deterministic workflow limitations | Keep strong deterministic flows as workflows | Workflow binding contract exists | Need migration classifier | LLM rewrites deterministic process badly | Classify workflow behavior before migration | P1 |
| Runtime validation | AtendIA AgentService validation | Documented target | Needs future tests | App assumes model/export validated enough | Validate config, tools, auth, permissions, deployment | P1 |

## Separation Of Responsibility

ChatGPT can:

- understand intent
- handle ambiguity
- propose candidate fields
- select allowed tools
- draft natural response
- summarize context
- translate
- interpret transcribed audio or image-derived signals

ChatGPT cannot:

- save state directly
- send WhatsApp
- write outbox
- execute workflows directly
- decide permissions
- approve deployment
- invent prices or requirements
- validate completed expediente
- ignore policy
- access unpublished sources
- publish agents
- roll back deployments

AtendIA must:

- control tenant and versioning
- authorize knowledge
- execute tools/actions
- validate outputs
- persist state
- control lifecycle
- control publish
- control send/no-send
- generate trace
- handle rollback
- block risks

## Recommendation

Adopt OpenAI's migration guidance as a validation checklist, not as a drop-in
implementation model. AtendIA's Product-First contracts remain the authority.
