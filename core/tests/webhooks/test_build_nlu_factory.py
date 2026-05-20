from atendia.config import Settings
from atendia.runner.nlu_fallback import FallbackNLU
from atendia.runner.nlu_openai import OpenAINLU
from atendia.runner.provider_factory import selection_from_config
from atendia.webhooks.meta_routes import build_nlu


def test_build_nlu_returns_openai_by_default():
    s = Settings(
        _env_file=None,  # type: ignore[arg-type]
        openai_api_key="sk-test",
        nlu_fallback_provider="none",
    )
    assert isinstance(build_nlu(s), OpenAINLU)


def test_build_nlu_passes_through_settings_to_openai():
    """OpenAINLU should be constructed with the model + retry timings from Settings."""
    s = Settings(
        _env_file=None,  # type: ignore[arg-type]
        nlu_provider="openai",
        openai_api_key="sk-test",
        nlu_fallback_provider="none",
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


def test_build_nlu_passes_tenant_topics_to_openai():
    s = Settings(
        _env_file=None,  # type: ignore[arg-type]
        nlu_provider="openai",
        openai_api_key="sk-test",
        nlu_fallback_provider="none",
    )
    selection = selection_from_config(
        s,
        {
            "nlu_topics": [
                {
                    "key": "bureau",
                    "label": "Buro",
                    "description": "Preguntas sobre buro",
                }
            ]
        },
    )
    nlu = build_nlu(s, selection)
    assert isinstance(nlu, OpenAINLU)
    assert nlu._topics[0]["key"] == "bureau"


def test_build_nlu_wraps_openai_with_haiku_fallback_when_anthropic_key_exists():
    s = Settings(
        _env_file=None,  # type: ignore[arg-type]
        openai_api_key="sk-test",
        anthropic_api_key="sk-ant-test",
    )
    nlu = build_nlu(s)
    assert isinstance(nlu, FallbackNLU)
    assert isinstance(nlu.primary, OpenAINLU)
