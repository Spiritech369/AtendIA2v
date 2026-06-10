# Model Comparison — gpt-4o-mini vs gpt-4o (same code, same battery)

Date: 2026-06-10
Code: frozen at F17 (exact handoff targets) + provider usage instrumentation;
179 tests passing, ruff clean. ZERO code changes between the two runs.
Battery: the same 10 conversations (71 turns), labels `r5mini_*` / `r5o_*`.

## Headline comparison

| Metric | gpt-4o-mini | gpt-4o |
|---|---|---|
| Human score (avg /5) | **3.9** | **~1.8 — INVALID as quality evidence (see below)** |
| Turns answered | **66/71 (93%)** | 23/71 (32%) |
| Silences (blocked, structured reason) | 5 | 48 |
| LLM calls | 136 | 91 |
| Retries (validator+parse) | 15 | 24 |
| Handoff proposals | 7 (all correct target after F17) | 0 |
| Tool executions | 51 | 33 |
| Dropped tool proposals (F14) | 0 | 0 |
| Tokens (prompt / completion) | 314,306 / 19,163 | 203,100 / 16,094 |
| **Estimated cost (battery)** | **$0.059** | **$0.669** (~11x) |

Pricing assumed: mini $0.15/$0.60 per 1M in/out; 4o $2.50/$10.00.

## Why the gpt-4o run is NOT a model-quality result

**32 of its 48 silences are `RateLimitError` (HTTP 429)** — the API tier's
gpt-4o TPM limit, hit by ~2.8k-token prompts in rapid sequence. Our client
is `AsyncOpenAI(max_retries=0)` with no backoff, so each 429 became an
instant fail-closed turn. The model never got to speak. Mini also caught
exactly one 429 (conv03), proving the same defect exists there at lower
probability.

The other 13 gpt-4o silences are `claim_missing_source_ref`: gpt-4o is
MORE diligent than mini — it declares claims for its statements — but our
prompt never explains WHAT to put in `source_refs` (the tool_name or the
KB source_id), so its claims failed ref validation, retried, and often hit
another 429 on the retry. Mini "passes" this check mostly by under-declaring
claims. The stricter model exposed a real prompt/contract gap.

## gpt-4o-mini battery — scores (avg 3.9)

c01 **4.5** (8/8; exact price/enganche/papeles each at the right moment),
c02 3.5 (1 silence on the compound ask; handoff deflection x3),
c03 3.0 (1 hard-policy silence + the 429), c04 **4.5** (clean; asks for
model naturally on enganche), c05 3.5 (all answered BUT invented "Metro
**2023**" — year not in catalog — and assumed SAT before confirmation),
c06 3.5 (price objection answered with grounded numbers; 1 hard-policy
silence on "más barata?"), c07 4.0 (honest robot answer + handoff), c08
**4.5** (both corrections clean: "Gracias por la corrección"), c09 3.5
(8/8 but mislabeled DNM2.5 as "económica" when the catalog says Metro is
the economy tier), c10 **4.5** (handoff with warm ack, exact target).

## Failure classification — every silent/blocked turn

### gpt-4o-mini (5 failures)

| Turn | Reason | Classification |
|---|---|---|
| c02 "quiero la opcion estandar..." | tool_round_limit_reached — insisted tool-only after the F5 ask-naturally feedback | **MODEL_LIMITATION** |
| c03 "pero dime los papeles primero" | hard_policy: wrote requisitos without the tool | **MODEL_LIMITATION** (validator correct) |
| c03 "me pagan por nómina" | llm_turn_provider_failed: **RateLimitError** | **RUNTIME_DEFECT** (no 429 backoff/retry) |
| c06 "hay una más barata?" | hard_policy: price words without quote support | **MODEL_LIMITATION** |
| c07 "qué ocupo" | hard_policy: requisitos without the tool | **MODEL_LIMITATION** |

Soft failures (answered, but flawed): "Metro 2023" invented year and
"DNM2.5 económica" mislabel (c05/c09) — **MODEL_LIMITATION** (groundedness
slips below the hard-policy radar; not price/requirements, so the gate's
"0 invented prices/requirements" still holds).

### gpt-4o (48 failures)

| Reason | Count | Classification |
|---|---|---|
| RateLimitError (429, no backoff) | 32 | **RUNTIME_DEFECT** — provider must retry transient API errors with backoff; mandatory before any live use regardless of model |
| claim_missing_source_ref | 13 | **RUNTIME_DEFECT** — prompt/contract gap: never instructs that source_refs must contain the tool_name or KB source_id; exposed by the more claim-diligent model |
| hard_policy_unsupported | 3 | **MODEL_LIMITATION** (same class as mini) |

## Conclusions

1. **The model comparison is inconclusive as a quality test** — gpt-4o was
   strangled by rate limits, not outwritten by mini. What IS conclusive:
   two runtime defects that MUST be fixed before live on any model:
   - **F18:** transient-error retry with backoff in the provider (429/5xx).
   - **F19:** prompt must specify source_refs content
     ("source_refs: the tool_name of the supporting tool_result or the
     [source_id] of the knowledge snippet").
2. mini's ceiling is confirmed at ~3.9-4.0 (R4 3.95, R5 3.9 — run variance
   ±0.1): always the same three behaviors (insisting on tools over the
   feedback, fact-words without support, occasional ungrounded garnish).
3. A clean gpt-4o comparison requires F18+F19 first (and benefits from
   pacing between turns). Cost reality: ~11x per conversation.

## Recommendation

Fix F18 + F19 (both small, both required-for-live anyway), then re-run
ONLY the gpt-4o battery for a clean comparison. If gpt-4o then clears 4.2,
the model choice becomes a per-tenant cost/quality dial
(`RespondStyleLLMTurnProviderConfig.model`); if not, the next lever is
hybrid (mini for qualification turns, 4o for fact-composition turns).
Gate unchanged: no AgentService, no smoke below 4.2.
