import hashlib
import hmac

import pytest

from atendia.channels.meta_signing import verify_meta_signature


SECRET = "test_app_secret"
BODY = b'{"object":"whatsapp_business_account","entry":[{"id":"123"}]}'
EXPECTED_SIG = "sha256=" + hmac.new(SECRET.encode("utf-8"), BODY, hashlib.sha256).hexdigest()


def test_valid_signature_returns_true():
    assert verify_meta_signature(BODY, EXPECTED_SIG, SECRET) is True


def test_invalid_signature_returns_false():
    assert verify_meta_signature(BODY, "sha256=deadbeef", SECRET) is False


def test_missing_sha256_prefix_returns_false():
    raw = EXPECTED_SIG.removeprefix("sha256=")
    assert verify_meta_signature(BODY, raw, SECRET) is False


def test_empty_secret_returns_false():
    assert verify_meta_signature(BODY, EXPECTED_SIG, "") is False


def test_empty_signature_returns_false():
    assert verify_meta_signature(BODY, "", SECRET) is False


def test_constant_time_comparison_used():
    """Smoke: ensure we use hmac.compare_digest (timing attack protection)."""
    import inspect
    from atendia.channels import meta_signing

    src = inspect.getsource(meta_signing)
    assert "compare_digest" in src
