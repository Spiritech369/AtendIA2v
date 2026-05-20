import pytest

from atendia.config import Settings
from atendia.runner.composer_openai import OpenAIComposer
from atendia.webhooks.meta_routes import build_composer


def test_build_composer_requires_openai_key():
    s = Settings(_env_file=None, openai_api_key="")  # type: ignore[arg-type]
    with pytest.raises(RuntimeError, match="OpenAI API key is required"):
        build_composer(s)


def test_build_composer_returns_openai():
    s = Settings(_env_file=None, openai_api_key="sk-test")  # type: ignore[arg-type]
    composer = build_composer(s)
    assert isinstance(composer, OpenAIComposer)


def test_build_composer_passes_through_settings():
    s = Settings(
        _env_file=None,  # type: ignore[arg-type]
        openai_api_key="sk-test",
        composer_model="gpt-4o",
        composer_timeout_s=4.0,
        composer_retry_delays_ms=[100, 500],
    )
    composer = build_composer(s)
    assert isinstance(composer, OpenAIComposer)
    assert composer._model == "gpt-4o"
    assert composer._delays == (0, 100, 500)
