import pytest

from atendia.config import get_settings


def test_settings_includes_meta_credentials(monkeypatch):
    monkeypatch.setenv("ATENDIA_V2_META_APP_SECRET", "test_secret")
    monkeypatch.setenv("ATENDIA_V2_META_ACCESS_TOKEN", "test_token")
    monkeypatch.setenv("ATENDIA_V2_META_API_VERSION", "v21.0")
    monkeypatch.setenv("ATENDIA_V2_META_BASE_URL", "https://graph.facebook.com")

    # bypass lru_cache
    get_settings.cache_clear()
    s = get_settings()
    assert s.meta_app_secret == "test_secret"
    assert s.meta_access_token == "test_token"
    assert s.meta_api_version == "v21.0"
    assert s.meta_base_url == "https://graph.facebook.com"


def test_settings_defaults_for_meta(monkeypatch):
    monkeypatch.delenv("ATENDIA_V2_META_APP_SECRET", raising=False)
    monkeypatch.delenv("ATENDIA_V2_META_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("ATENDIA_V2_META_API_VERSION", raising=False)
    monkeypatch.delenv("ATENDIA_V2_META_BASE_URL", raising=False)
    get_settings.cache_clear()
    s = get_settings()
    assert s.meta_app_secret == ""  # empty default
    assert s.meta_access_token == ""
    assert s.meta_api_version == "v21.0"  # version default
    assert s.meta_base_url == "https://graph.facebook.com"
