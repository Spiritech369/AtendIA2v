# Sandbox tools

High-fidelity local probes that are useful for validation, but should not live
under `core/scripts/` because the backend dev container watches `core/` and can
reload when files there change.

## Scripts

| Script | Purpose | Side effects |
|---|---|---|
| `sandbox_recon.py` | Read-only tenant inventory to find a good sandbox target | None; rolls back session |
| `sandbox_smoke.py` | Live LLM sandbox conversation smoke with a temporary Dinamo tenant | Deletes seed tenant; harness rolls back runner writes |

## Run

From the repo root:

```powershell
uv --directory core run python ../tools/sandbox/sandbox_recon.py
uv --directory core run python ../tools/sandbox/sandbox_smoke.py
```

Or from `core/`:

```powershell
uv run python ../tools/sandbox/sandbox_recon.py
uv run python ../tools/sandbox/sandbox_smoke.py
```

`sandbox_smoke.py` requires `ATENDIA_V2_OPENAI_API_KEY` in `core/.env`.

