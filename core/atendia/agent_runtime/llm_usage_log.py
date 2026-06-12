"""Append-only JSONL usage log for OpenAI calls in the Respond-Style path.

One line per request with token counts (input/cached/output/total), model,
call kind (turn/vision/audio) and optional correlation ids. The test run id
comes from the ATENDIA_TEST_RUN_ID env var or a RUN_ID marker file in the
log directory, so a controlled test can be isolated without touching code.
Files land under ``<upload_dir>/llm_usage/usage_<date>.jsonl``.

Best effort by design: usage accounting must never break a customer turn.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _test_run_id(base: Path) -> str | None:
    env_value = os.environ.get("ATENDIA_TEST_RUN_ID")
    if env_value:
        return env_value
    marker = base / "RUN_ID"
    try:
        if marker.exists():
            value = marker.read_text(encoding="utf-8").strip()
            return value or None
    except Exception:
        return None
    return None


def record_llm_usage(
    *,
    kind: str,
    model: str,
    usage: Any,
    context: dict[str, Any] | None = None,
) -> None:
    """Append one usage line. ``usage`` is the OpenAI response.usage object
    (or any object/dict with prompt/completion token attributes)."""
    try:
        from atendia.config import get_settings

        base = Path(get_settings().upload_dir) / "llm_usage"
        base.mkdir(parents=True, exist_ok=True)

        def _get(name: str) -> int:
            if usage is None:
                return 0
            if isinstance(usage, dict):
                return int(usage.get(name) or 0)
            return int(getattr(usage, name, 0) or 0)

        details = getattr(usage, "prompt_tokens_details", None)
        cached = int(getattr(details, "cached_tokens", 0) or 0) if details else 0
        entry: dict[str, Any] = {
            "ts": datetime.now(UTC).isoformat(),
            "test_run_id": _test_run_id(base),
            "kind": kind,
            "model": model,
            "input_tokens": _get("prompt_tokens"),
            "cached_tokens": cached,
            "output_tokens": _get("completion_tokens"),
            "total_tokens": _get("total_tokens"),
        }
        if context:
            entry.update(context)
        path = base / f"usage_{datetime.now(UTC).strftime('%Y_%m_%d')}.jsonl"
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        logger.warning("llm_usage_log_failed", exc_info=True)
