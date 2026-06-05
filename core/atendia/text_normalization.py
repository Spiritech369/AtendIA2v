from __future__ import annotations

import re
import unicodedata

_TOKEN_REPLACEMENTS: dict[str, str] = {
    "burro": "buro",
    "choper": "chopper",
    "comprobnte": "comprobante",
    "comprobntes": "comprobantes",
    "papels": "papeles",
}


def normalize_whatsapp_text(value: object, *, keep_percent: bool = True) -> str:
    """Normalize short WhatsApp text for deterministic policy matching."""

    decomposed = unicodedata.normalize("NFKD", str(value or "").casefold())
    without_accents = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    allowed = r"[^a-z0-9%]+" if keep_percent else r"[^a-z0-9]+"
    normalized = re.sub(r"\s+", " ", re.sub(allowed, " ", without_accents)).strip()
    if not normalized:
        return ""
    return " ".join(_TOKEN_REPLACEMENTS.get(token, token) for token in normalized.split())


__all__ = ["normalize_whatsapp_text"]
