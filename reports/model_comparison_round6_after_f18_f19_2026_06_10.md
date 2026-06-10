# Valid Model Comparison — gpt-4o (after F18+F19) vs prior baselines

Date: 2026-06-10
Decision: `GPT4O_COMPARISON_VALID_AFTER_F18_F19_PASSED`
Code: F18 (transient backoff) + F19 (source_refs contract); 191 tests
passing, ruff clean. Same 10 conversations, unchanged. Battery `r6o_*`.

## F18 + F19 — what was implemented

- **F18:** `RespondStyleLLMTurnProvider` retries ONLY transient API errors
  (RateLimitError/timeout/connection/5xx by class name or status code)
  with exponential backoff + jitter, honoring `Retry-After`, capped by
  `max_transient_retries` (default 4) / `backoff_max_seconds`. Exhaustion
  fails closed as `api_rate_limited` / `api_transient_failure`. Schema and
  validation errors are NEVER treated as transient. Counters
  (`transient_retries_total`, `backoff_wait_ms_total`,
  `validator_retries_total`) appear in every decision's trace. No model
  fallback, no synthetic copy, no keys logged.
- **F19:** the platform prompt now defines source_refs exactly
  (`tool:<tool_name>`, `kb:<source_id>`, `contact_field:<field_key>`,
  `transcript:latest_customer_message`, `simulated_field:<field_key>`),
  forbids inventing refs, and instructs: no valid ref → run the tool or
  ask, never state the fact. The validator accepts the prefixed forms
  (plus bare ids for back-compat) sourced from context/tool_results/field
  policies/contact state. Hard policies untouched (test-enforced).
- 12 new tests covering every requirement in the goal spec.

## Headline comparison

| Metric | mini r5 | gpt-4o r5 (invalid) | **gpt-4o r6 (valid)** |
|---|---|---|---|
| Human score (avg /5) | 3.9 | ~1.8 | **4.25** |
| Turns answered | 66/71 | 23/71 | **67/71** |
| Silences | 5 | 48 | **4** |
| RateLimitError silences | 1 | 32 | **0** |
| claim_missing_source_ref | 0* | 13 | **0** |
| Transient retries absorbed (F18) | — | — | 104 (157s total backoff) |
| Validator/parse retries | 15 | 24 | 11 |
| Tool executions | 51 | 33 | (comparable; all grounded) |
| Handoffs (exact target) | 7 | 0 | 6 |
| Tokens (prompt/completion) | 314k/19k | 203k/16k | 297k/21k |
| **Estimated cost / battery** | **$0.059** | $0.669 | **$0.953 (~16x mini)** |

*mini under-declares claims; gpt-4o declares them and, after F19, cites
them correctly — better grounding discipline, not just fewer errors.

## Round-6 scores per conversation

c01 4.5, c02 4.0, c03 **2.5**, c04 **5.0**, c05 4.5, c06 **4.5** (the
price-objection arc finally lands: "está muy caro" → empathy + offer;
"hay una más barata?" → honest grounded "la Metro ES la más económica"),
c07 4.0, c08 4.5, c09 4.5 (red disambiguation with CORRECT price tiers —
mini had mislabeled them), c10 4.5 (instant warm handoff). **Avg 4.25.**

Qualitative: gpt-4o never invented garnish (mini's "Metro 2023" and
"DNM2.5 económica" mislabel did not occur), kept catalog price tiers
straight, and handled the objection arc like a salesperson.

## Failure classification — all 4 remaining silences

| Turn | Reason | Classification |
|---|---|---|
| c03 "pero dime los papeles primero" | hard_policy requirements | **VALIDATION_CORRECT_BLOCK** (claimed papeles without the tool; income_type still unknown) |
| c03 "tengo como 2 años trabajando" | hard_policy requirements | **VALIDATION_CORRECT_BLOCK** |
| c03 "me pagan por nómina" | internal_text_visible | **VALIDATION_CORRECT_BLOCK** (leak tripwire; raw text not persisted for blocked turns — instrumenting blocked-output capture is a nice-to-have) |
| c07 "qué ocupo" | hard_policy requirements | **VALIDATION_CORRECT_BLOCK** |

RATE_LIMIT: 0 (was 32). PROMPT_CONTRACT_GAP: 0 (was 13).
RUNTIME_DEFECT: 0. MODEL_LIMITATION as primary cause: 0 — every remaining
block is the validator doing its job against an early unsupported claim;
the conversational cost is concentrated in c03's stubborn-customer
pattern ("dame los papeles primero" before qualifying data exists).

## Gate status (original human-review gate)

- Average >= 4.2: **PASSED (4.25)** — first battery to clear it.
- "No critical turn < 4": **NOT yet** — c03 still degrades when the
  customer insists on requirements before giving data. The fix direction
  is conversational, not structural: let the model answer the generic
  document list from the KB snippet (it already may via kb: claims) or
  config a KB snippet with the generic requirements so the early ask is
  answerable without income_type.
- Cost reality: ~$0.0134/conversation (gpt-4o) vs ~$0.0008 (mini); model
  per tenant is already a config dial.

## Decision

`GPT4O_COMPARISON_VALID_AFTER_F18_F19_PASSED`

The comparison is now clean: zero rate-limit contamination, zero contract
gaps. gpt-4o clears the score bar (4.25 vs mini's 3.9 ceiling) at ~16x
token cost. Remaining work before declaring the full human-review gate:
resolve the c03 pattern (KB-answerable generic requirements), then one
confirmation battery. Still NO AgentService and NO smoke until the full
gate (score + no critical turns) passes.
