"""Test the ToolNoDataResult model.

Phase 3b adds this Pydantic model so the runner can pass a
'no catalog connected yet' hint to the Composer for actions like
quote/lookup_faq/search_catalog. Real tool data lands in Phase 3c.
"""
import pytest
from pydantic import ValidationError

from atendia.tools.base import ToolNoDataResult


def test_tool_no_data_result_default_status():
    r = ToolNoDataResult(hint="catalog not connected")
    assert r.status == "no_data"
    assert r.hint == "catalog not connected"


def test_tool_no_data_result_status_is_literal():
    """status must be exactly 'no_data' — Literal type prevents other values."""
    with pytest.raises(ValidationError):
        ToolNoDataResult.model_validate({"status": "ok", "hint": "x"})


def test_tool_no_data_result_serializes_correctly():
    r = ToolNoDataResult(hint="faqs not connected")
    dumped = r.model_dump()
    assert dumped == {"status": "no_data", "hint": "faqs not connected"}


def test_tool_no_data_result_requires_hint():
    with pytest.raises(ValidationError):
        ToolNoDataResult()  # type: ignore[call-arg]
