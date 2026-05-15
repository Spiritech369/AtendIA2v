import pytest
from pydantic import ValidationError

from atendia.contracts.tone import Tone
from atendia.runner.composer_protocol import (
    ComposerInput,
    ComposerOutput,
    ComposerProvider,
)


def test_composer_input_minimal():
    inp = ComposerInput(
        action="greet",
        current_stage="greeting",
        tone=Tone(),
    )
    assert inp.action == "greet"
    assert inp.action_payload == {}
    assert inp.history == []
    assert inp.max_messages == 2


def test_composer_input_max_messages_validates():
    with pytest.raises(ValidationError):
        ComposerInput(action="x", current_stage="x", tone=Tone(), max_messages=4)
    with pytest.raises(ValidationError):
        ComposerInput(action="x", current_stage="x", tone=Tone(), max_messages=0)


def test_composer_output_rejects_empty():
    with pytest.raises(ValidationError):
        ComposerOutput(messages=[])


def test_composer_output_rejects_too_many():
    with pytest.raises(ValidationError):
        ComposerOutput(messages=["a", "b", "c", "d"])


def test_composer_output_accepts_1_to_3():
    assert ComposerOutput(messages=["a"]).messages == ["a"]
    assert len(ComposerOutput(messages=["a", "b"]).messages) == 2
    assert len(ComposerOutput(messages=["a", "b", "c"]).messages) == 3


async def test_protocol_satisfied_by_dummy():
    class Dummy:
        async def compose(self, *, input):
            return ComposerOutput(messages=["x"]), None

    composer: ComposerProvider = Dummy()
    out, usage = await composer.compose(
        input=ComposerInput(
            action="x",
            current_stage="x",
            tone=Tone(),
        )
    )
    assert out.messages == ["x"]
    assert usage is None
