from atendia.config import Settings
from atendia.runner.composer_canned import CannedComposer
from atendia.runner.composer_openai import OpenAIComposer
from atendia.webhooks.meta_routes import build_composer


def test_build_composer_returns_canned_when_provider_canned():
    s = Settings(_env_file=None, composer_provider="canned")  # type: ignore[arg-type]
    assert isinstance(build_composer(s), CannedComposer)


def test_build_composer_returns_openai_when_provider_openai():
    s = Settings(
        _env_file=None,  # type: ignore[arg-type]
        composer_provider="openai",
        openai_api_key="sk-test",
    )
    composer = build_composer(s)
    assert isinstance(composer, OpenAIComposer)


def test_build_composer_passes_through_settings():
    s = Settings(
        _env_file=None,  # type: ignore[arg-type]
        composer_provider="openai",
        openai_api_key="sk-test",
        composer_model="gpt-4o",
        composer_timeout_s=4.0,
        composer_retry_delays_ms=[100, 500],
    )
    composer = build_composer(s)
    assert isinstance(composer, OpenAIComposer)
    assert composer._model == "gpt-4o"
    assert composer._delays == (0, 100, 500)
