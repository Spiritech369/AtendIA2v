from atendia.config import Settings


def test_nlu_provider_default_is_openai_with_haiku_fallback():
    s = Settings(_env_file=None)  # type: ignore[arg-type]
    assert s.nlu_provider == "openai"
    assert s.nlu_model == "gpt-4o-mini"
    assert s.nlu_fallback_provider == "haiku"
    assert s.nlu_fallback_model == "claude-haiku-4-5-20251001"
    assert s.nlu_timeout_s == 8.0
    assert s.nlu_retry_delays_ms == [500, 2000]
    assert s.openai_api_key == ""


def test_composer_provider_default_is_openai():
    s = Settings(_env_file=None)  # type: ignore[arg-type]
    assert s.composer_provider == "openai"
    assert s.composer_model == "gpt-4o-mini"
    assert s.composer_timeout_s == 8.0
    assert s.composer_retry_delays_ms == [500, 2000]
    assert s.composer_max_messages == 2


def test_agent_runtime_model_provider_is_disabled_by_default():
    s = Settings(_env_file=None)  # type: ignore[arg-type]
    assert s.agent_runtime_v2_enabled is False
    assert s.agent_runtime_v2_send_enabled is False
    assert s.agent_runtime_v2_actions_enabled is False
    assert s.agent_runtime_v2_workflow_events_enabled is False
    assert s.agent_runtime_v2_model_provider == "disabled"
    assert s.agent_runtime_v2_model == "gpt-4o-mini"
    assert s.agent_runtime_v2_model_timeout_s == 8.0
    assert s.agent_runtime_v2_model_retry_delays_ms == [500, 2000]
