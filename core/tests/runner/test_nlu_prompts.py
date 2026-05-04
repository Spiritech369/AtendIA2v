import pytest

from atendia.runner.nlu_prompts import (
    HISTORY_FORMAT, OUTPUT_INSTRUCTIONS, ROLE_LABELS,
    SYSTEM_PROMPT_TEMPLATE, render_template,
)


def test_render_substitutes_placeholders():
    out = render_template("hello {{name}}, you are in {{stage}}", name="Frank", stage="qualify")
    assert out == "hello Frank, you are in qualify"


def test_render_raises_on_missing_placeholder():
    with pytest.raises(RuntimeError, match="unsubstituted placeholder"):
        render_template("hello {{name}}", other="x")


def test_render_ignores_extra_vars():
    out = render_template("hello {{name}}", name="x", extra="y")
    assert out == "hello x"


def test_render_supports_repeated_placeholders():
    out = render_template("{{a}} and {{a}} again", a="hi")
    assert out == "hi and hi again"


def test_role_labels_complete():
    assert "inbound" in ROLE_LABELS
    assert "outbound" in ROLE_LABELS
    assert ROLE_LABELS["inbound"] == "cliente"
    assert ROLE_LABELS["outbound"] == "asistente"


def test_template_constants_have_placeholders():
    assert "{{stage}}" in SYSTEM_PROMPT_TEMPLATE
    assert "{{required_fields_block}}" in SYSTEM_PROMPT_TEMPLATE
    assert "{{optional_fields_block}}" in SYSTEM_PROMPT_TEMPLATE
    assert "{{output_instructions}}" in SYSTEM_PROMPT_TEMPLATE
    assert "{{role}}" in HISTORY_FORMAT
    assert "{{text}}" in HISTORY_FORMAT
    assert "intent" in OUTPUT_INSTRUCTIONS  # sanity check on content
