from pathlib import Path

import pytest

from atendia.contracts.pipeline_definition import FieldSpec
from atendia.runner.nlu_prompts import (
    HISTORY_FORMAT, OUTPUT_INSTRUCTIONS, ROLE_LABELS,
    SYSTEM_PROMPT_TEMPLATE, build_prompt, render_template,
)

_FIXTURES = Path(__file__).parent.parent / "fixtures" / "nlu"


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


def test_build_prompt_basic_structure():
    messages = build_prompt(
        text="me interesa la 150Z",
        current_stage="qualify",
        required_fields=[
            FieldSpec(name="interes_producto", description="Modelo de moto"),
            FieldSpec(name="ciudad", description="Ciudad del cliente"),
        ],
        optional_fields=[FieldSpec(name="nombre", description="Nombre")],
        history=[("inbound", "hola"), ("outbound", "hola, ¿en qué te ayudo?")],
    )

    # System message is first
    assert messages[0]["role"] == "system"
    assert "qualify" in messages[0]["content"]
    assert "interes_producto" in messages[0]["content"]
    assert "Modelo de moto" in messages[0]["content"]
    assert "ciudad" in messages[0]["content"]
    assert "nombre" in messages[0]["content"]

    # Last message is the current user text
    assert messages[-1]["role"] == "user"
    assert messages[-1]["content"] == "me interesa la 150Z"

    # History rendered between system and current message — uses Spanish role labels
    assert any("[cliente] hola" in m.get("content", "") for m in messages)
    assert any("[asistente] hola, ¿en qué te ayudo?" in m.get("content", "") for m in messages)


def test_build_prompt_history_role_mapping():
    messages = build_prompt(
        text="x", current_stage="x",
        required_fields=[], optional_fields=[],
        history=[("inbound", "from-client"), ("outbound", "from-bot")],
    )
    # inbound → role "user", outbound → role "assistant"
    history_msgs = messages[1:-1]  # skip system + final user
    assert len(history_msgs) == 2
    assert history_msgs[0]["role"] == "user"
    assert history_msgs[1]["role"] == "assistant"


def test_build_prompt_empty_required_renders_ninguno():
    messages = build_prompt(
        text="hola", current_stage="greeting",
        required_fields=[], optional_fields=[], history=[],
    )
    assert "(ninguno)" in messages[0]["content"]


def test_build_prompt_empty_history_two_messages_total():
    messages = build_prompt(
        text="hola", current_stage="greeting",
        required_fields=[], optional_fields=[], history=[],
    )
    # Just system + final user
    assert len(messages) == 2
    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "user"


def test_build_prompt_field_with_empty_description_renders_placeholder():
    messages = build_prompt(
        text="x", current_stage="qualify",
        required_fields=[FieldSpec(name="ciudad", description="")],
        optional_fields=[], history=[],
    )
    assert "ciudad: (sin descripción)" in messages[0]["content"]


def test_system_prompt_snapshot_qualify():
    expected = (_FIXTURES / "qualify_system.txt").read_text(encoding="utf-8")
    messages = build_prompt(
        text="dummy",
        current_stage="qualify",
        required_fields=[
            FieldSpec(name="interes_producto", description="Modelo de moto"),
            FieldSpec(name="ciudad", description="Ciudad del cliente"),
        ],
        optional_fields=[FieldSpec(name="nombre", description="Nombre del cliente")],
        history=[],
    )
    assert messages[0]["content"] == expected
