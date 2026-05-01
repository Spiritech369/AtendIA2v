import hashlib
import hmac


def verify_meta_signature(body: bytes, signature_header: str, app_secret: str) -> bool:
    """Verify the X-Hub-Signature-256 header on a Meta webhook.

    The header has the format `sha256=<hex>`. We compute HMAC-SHA256 over
    the raw body using `app_secret` and compare in constant time.
    Returns False on any malformed input — never raises.
    """
    if not app_secret or not signature_header:
        return False
    if not signature_header.startswith("sha256="):
        return False
    received = signature_header.removeprefix("sha256=")
    expected = hmac.new(
        app_secret.encode("utf-8"), body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(received, expected)
