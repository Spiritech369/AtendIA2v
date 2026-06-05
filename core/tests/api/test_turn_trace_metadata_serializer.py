from __future__ import annotations

import json
from types import SimpleNamespace

from atendia.api.turn_traces_routes import _extract_trace_metadata


def _row(
    *,
    composer_output: dict | None = None,
    state_after: dict | None = None,
    raw_llm_response: str | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        composer_output=composer_output,
        state_after=state_after,
        raw_llm_response=raw_llm_response,
    )


def _trace_metadata() -> dict:
    return {
        "trace_id": "turn-test",
        "universal_turn_trace": {
            "trace_version": "1.0",
            "gpt_proposed": {},
            "atendia_validation": {},
            "mandatory_tool_decisions": [],
            "state_changes": {},
            "guards": [],
            "final_output": {"final_message": "mensaje final"},
        },
    }


def test_extract_trace_metadata_from_composer_output() -> None:
    trace_metadata = _trace_metadata()
    row = _row(composer_output={"trace_metadata": trace_metadata})

    assert _extract_trace_metadata(row) == trace_metadata


def test_extract_trace_metadata_from_state_after_fallback() -> None:
    trace_metadata = _trace_metadata()
    row = _row(state_after={"trace_metadata": trace_metadata})

    assert _extract_trace_metadata(row) == trace_metadata


def test_extract_trace_metadata_from_raw_response_fallback() -> None:
    trace_metadata = _trace_metadata()
    row = _row(raw_llm_response=json.dumps({"trace_metadata": trace_metadata}))

    assert _extract_trace_metadata(row) == trace_metadata


def test_extract_trace_metadata_returns_none_for_legacy_trace() -> None:
    row = _row(composer_output={"messages": ["legacy"]}, state_after={"raw": True})

    assert _extract_trace_metadata(row) is None
