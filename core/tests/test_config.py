from atendia.config import Settings


def test_nlu_provider_default_is_keyword():
    s = Settings(_env_file=None)  # type: ignore[arg-type]
    assert s.nlu_provider == "keyword"
    assert s.nlu_model == "gpt-4o-mini"
    assert s.nlu_timeout_s == 8.0
    assert s.nlu_retry_delays_ms == [500, 2000]
    assert s.openai_api_key == ""


def test_composer_provider_default_is_canned():
    s = Settings(_env_file=None)  # type: ignore[arg-type]
    assert s.composer_provider == "canned"
    assert s.composer_model == "gpt-4o"
    assert s.composer_timeout_s == 8.0
    assert s.composer_retry_delays_ms == [500, 2000]
    assert s.composer_max_messages == 2
