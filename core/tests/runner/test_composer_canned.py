import pytest

from atendia.contracts.tone import Tone
from atendia.runner.composer_canned import CannedComposer
from atendia.runner.composer_protocol import ComposerInput


@pytest.mark.parametrize("action,expected_substring", [
    ("greet", "hola"),
    ("ask_field", "detalles"),
    ("lookup_faq", "revisar"),
    ("ask_clarification", "no te entendí"),
    ("quote", "precio"),
    ("explain_payment_options", "efectivo"),
    ("close", "siguiente paso"),
])
async def test_canned_composer_returns_text_for_action(action, expected_substring):
    composer = CannedComposer()
    out, usage = await composer.compose(input=ComposerInput(
        action=action, current_stage="x", tone=Tone(),
    ))
    assert len(out.messages) == 1
    assert expected_substring.lower() in out.messages[0].lower()
    assert usage is None


async def test_canned_composer_handles_unknown_action():
    composer = CannedComposer()
    out, usage = await composer.compose(input=ComposerInput(
        action="unknown_action_xyz", current_stage="x", tone=Tone(),
    ))
    assert len(out.messages) == 1
    assert "consultar" in out.messages[0].lower()
    assert usage is None
