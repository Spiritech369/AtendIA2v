import pytest
from pydantic import ValidationError

from atendia.contracts.tone import Tone


def test_tone_defaults():
    t = Tone()
    assert t.register == "neutral_es"
    assert t.use_emojis == "sparingly"
    assert t.max_words_per_message == 40
    assert t.bot_name == "Asistente"
    assert t.forbidden_phrases == []
    assert t.signature_phrases == []


def test_tone_register_validates():
    with pytest.raises(ValidationError):
        Tone(register="japanese")  # type: ignore[arg-type]


def test_tone_use_emojis_validates():
    with pytest.raises(ValidationError):
        Tone(use_emojis="always")  # type: ignore[arg-type]


def test_tone_max_words_range_low():
    with pytest.raises(ValidationError):
        Tone(max_words_per_message=5)


def test_tone_max_words_range_high():
    with pytest.raises(ValidationError):
        Tone(max_words_per_message=200)


def test_tone_from_dinamo_dict():
    t = Tone.model_validate({
        "register": "informal_mexicano",
        "use_emojis": "sparingly",
        "max_words_per_message": 40,
        "bot_name": "Dinamo",
        "forbidden_phrases": ["estimado cliente"],
        "signature_phrases": ["¡qué onda!"],
    })
    assert t.bot_name == "Dinamo"
    assert "estimado cliente" in t.forbidden_phrases
