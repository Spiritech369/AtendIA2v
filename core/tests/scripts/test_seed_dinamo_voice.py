from atendia.contracts.tone import Tone
from atendia.scripts.seed_dinamo_voice import DINAMO_VOICE


def test_dinamo_voice_parses_to_tone():
    t = Tone.model_validate(DINAMO_VOICE)
    assert t.bot_name == "Dinamo"
    assert t.register == "informal_mexicano"
    assert "estimado cliente" in t.forbidden_phrases
