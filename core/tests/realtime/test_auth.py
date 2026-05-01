import pytest

from atendia.realtime.auth import decode_token, issue_token


def test_round_trip(monkeypatch):
    monkeypatch.setenv("ATENDIA_V2_META_APP_SECRET", "secret_for_t23_jwt")
    from atendia.config import get_settings
    get_settings.cache_clear()

    token = issue_token(tenant_id="dinamomotos", ttl_seconds=600)
    assert isinstance(token, str)
    assert len(token) > 20  # JWT compacted form

    decoded = decode_token(token)
    assert decoded == "dinamomotos"


def test_decode_rejects_tampered_token(monkeypatch):
    monkeypatch.setenv("ATENDIA_V2_META_APP_SECRET", "secret_for_t23_jwt")
    from atendia.config import get_settings
    get_settings.cache_clear()

    token = issue_token(tenant_id="t", ttl_seconds=600)
    tampered = token[:-3] + "AAA"

    with pytest.raises(Exception):
        decode_token(tampered)


def test_decode_rejects_expired_token(monkeypatch):
    monkeypatch.setenv("ATENDIA_V2_META_APP_SECRET", "secret_for_t23_jwt")
    from atendia.config import get_settings
    get_settings.cache_clear()

    # Issue a token that expires immediately
    token = issue_token(tenant_id="t", ttl_seconds=-1)
    with pytest.raises(Exception):
        decode_token(token)
