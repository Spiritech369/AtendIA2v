from atendia.config import Settings
from atendia.runner.nlu_keywords import KeywordNLU
from atendia.runner.nlu_openai import OpenAINLU
from atendia.webhooks.meta_routes import build_nlu


def test_build_nlu_returns_keyword_when_provider_keyword():
    s = Settings(_env_file=None, nlu_provider="keyword")  # type: ignore[arg-type]
    assert isinstance(build_nlu(s), KeywordNLU)


def test_build_nlu_returns_openai_when_provider_openai():
    s = Settings(
        _env_file=None,  # type: ignore[arg-type]
        nlu_provider="openai",
        openai_api_key="sk-test",
    )
    assert isinstance(build_nlu(s), OpenAINLU)


def test_build_nlu_passes_through_settings_to_openai():
    """OpenAINLU should be constructed with the model + retry timings from Settings."""
    s = Settings(
        _env_file=None,  # type: ignore[arg-type]
        nlu_provider="openai",
        openai_api_key="sk-test",
        nlu_model="gpt-4o-mini",
        nlu_timeout_s=4.0,
        nlu_retry_delays_ms=[100, 500],
    )
    nlu = build_nlu(s)
    assert isinstance(nlu, OpenAINLU)
    # Internal-state inspection: the implementer chose to store these as private attrs.
    # If they're not directly inspectable, this test can be relaxed to just isinstance.
    assert nlu._model == "gpt-4o-mini"
    assert nlu._delays == (0, 100, 500)  # 0 prepended for the first attempt
