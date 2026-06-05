# Frontend Screenshot Review Checklist - Dinamo

Date: 2026-06-02

Tenant:

- tenant_id: `6ad78236-1fc9-467a-858d-90d248d57ee5`
- email: `dinamomotosnl@gmail.com`
- agent_id: `c169deec-226d-55b7-bd07-270f339e75a6`

## Status

Ready for screenshot review with caveats. API and DB validation passed for the main configuration surfaces. Browser UI verification reached the login screen in the in-app browser; authenticated visual verification could not be completed because the browser wrapper did not expose cookie/context mutation cleanly. API-authenticated checks covered the same tenant data.

## Pages To Capture

| Page | Expected Evidence | Status |
| --- | --- | --- |
| `/knowledge` | `Fuentes` tab visible; 5 sources; catalog/FAQ/docs/non-factual labels | API verified, UI test passed |
| `/catalog` | 34 Dinamo products; R4 250 CC and Comando 400 CC present; 136 plans | DB/API verified |
| `/expediente` | `Plan_Credito`; 7 document cases; docs catalog | Frontend parser fixed, unit test passed, visual auth pending |
| `/workflows` | 4 inactive preview/manual workflows; validation visible, no execution | DB/API verified, UI test passed |
| `/customer-fields` | 11 fields; no duplicates; quote/checklist render modes in contract | DB/API verified |
| `/pipeline` | 8 stages; terminal/manual markers; document requirements | DB/API verified |
| `/composer` | Stage guidance shown as guidance, not final copy authority | Decision documented |
| `/agents` | Real Agent Studio panels; badges for heuristic/stale widgets | API audited, gaps documented |
| ContactPanel | Grouped commercial/technical/debug fields; quote/checklist renderers | Backend ready, frontend gap |

## Visual Review Notes

Confirm in screenshots:

- No page presents hardcoded Dinamo/motos/credit copy as global runtime assumptions.
- Preview-only or heuristic data is badged.
- No send/WhatsApp/manual-send control is active.
- Workflows show inactive/draft/preview state.
- Agent Studio sources match the 5 Knowledge OS sources.
- Expediente shows the canonical `document_requirements_field` and `document_requirements` data.
- ContactPanel does not flatten quote/checklist data in a confusing way.

## Known UI Gaps Before Final Live Use

- Authenticated in-app browser visual verification remains pending.
- ContactPanel frontend does not fully consume `group`, `render_mode`, and `render_payload`.
- Agents linked workflows endpoint returns empty.
- Agents heuristic widgets need badges or hiding.

