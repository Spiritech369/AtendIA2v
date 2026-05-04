from atendia.config import Settings


def test_nlu_provider_default_is_keyword():
    s = Settings(_env_file=None)  # type: ignore[arg-type]
    assert s.nlu_provider == "keyword"
    assert s.nlu_model == "gpt-4o-mini"
    assert s.nlu_timeout_s == 8.0
    assert s.nlu_retry_delays_ms == [500, 2000]
    assert s.openai_api_key == ""
