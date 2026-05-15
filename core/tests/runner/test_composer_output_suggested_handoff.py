"""D6 Task 1 — ComposerOutput exposes a nullable suggested_handoff
field that mirrors HandoffReason enum values. The OpenAI composer's
JSON schema accepts it in strict mode."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from atendia.contracts.handoff_summary import HandoffReason
from atendia.runner.composer_protocol import ComposerOutput


def test_composer_output_accepts_null_suggested_handoff():
    """Default — legacy / happy-path turns have no escalation hint."""
    out = ComposerOutput(messages=["hola"])
    assert out.suggested_handoff is None


def test_composer_output_accepts_each_handoff_reason_value():
    """Every HandoffReason enum value is acceptable as
    suggested_handoff. This pins the contract: the composer can
    emit any of the documented reasons and the runner-side parser
    won't reject."""
    for reason in HandoffReason:
        out = ComposerOutput(messages=["x"], suggested_handoff=reason.value)
        assert out.suggested_handoff == reason.value


def test_composer_output_rejects_unknown_handoff_value():
    """If gpt-4o hallucinates a handoff value that isn't in the
    enum, ComposerOutput rejects it (instead of silently passing a
    string the runner can't dispatch). The runner can then surface
    a structured error in turn_traces.errors instead of crashing
    later."""
    with pytest.raises(ValidationError):
        ComposerOutput(messages=["x"], suggested_handoff="just_made_this_up")


def test_openai_schema_includes_suggested_handoff():
    """The strict-mode JSON schema the OpenAI composer sends with
    response_format must declare suggested_handoff in properties +
    required (strict mode rejects partial). Null or one of the enum
    string values are the only acceptable values."""
    from atendia.runner.composer_openai import _composer_schema

    schema = _composer_schema(max_messages=3)
    props = schema["schema"]["properties"]
    required = schema["schema"]["required"]
    assert "suggested_handoff" in props, "suggested_handoff missing from properties"
    assert "suggested_handoff" in required, (
        "OpenAI strict mode requires every property in `required`; "
        "suggested_handoff must be listed even though its value can be null"
    )
    # The field accepts null OR one of the enum string values
    prop = props["suggested_handoff"]
    # Either ["null", "string"] union or oneOf — confirm null is allowed
    type_decl = prop.get("type")
    if isinstance(type_decl, list):
        assert "null" in type_decl
        assert "string" in type_decl
    else:
        # Could be an anyOf / oneOf structure
        any_of = prop.get("anyOf") or prop.get("oneOf") or []
        kinds = {x.get("type") for x in any_of if isinstance(x, dict)}
        assert "null" in kinds and "string" in kinds, (
            f"suggested_handoff must accept null|string, got {prop!r}"
        )
