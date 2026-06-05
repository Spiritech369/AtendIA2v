# Composer Surface Audit - 2026-06-02

## Classification

`/composer` is classified as `LEGACY_COMPOSER` unless a future backend audit proves AgentRuntime v2 consumes it strictly as stage guidance.

## Backend Consumption Summary

- AgentRuntime v2 final visible copy authority is `TurnOutput.final_message`.
- Legacy runner/composer modules still exist as fallback.
- Pipeline `mode_prompts` exist and can help stage guidance, but must not compete as visible final response text.

## Decision

For Dinamo v2:

- Hide `/composer` from primary navigation or badge it `Legacy`.
- Prefer integrating editable guidance inside Pipeline or Agent Studio.
- If kept active, rename to `Guias por etapa`.
- Required fields per guidance mode: objective, recommended data, max one question per turn, forbidden rules, suggested knowledge sources, allowed actions.

## Guardrail

No `/composer` surface may write, replace, or post-process `TurnOutput.final_message` for AgentRuntime v2 tenants.

