"""Transport-level WhatsApp formatting for validated outbound text.

The LLM is instructed to avoid markdown, but models still slip ``**bold**``
and ``[text](url)`` into otherwise-valid messages. This normalizer converts
those to WhatsApp-native forms right before staging the send. It NEVER
changes wording — only markup — so the validated content stays intact.
"""

from __future__ import annotations

import re

_MD_LINK = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")
_MD_BOLD = re.compile(r"\*\*(.+?)\*\*", re.DOTALL)
_MD_HEADER = re.compile(r"^[ \t]*#{1,6}[ \t]*", re.MULTILINE)


def to_whatsapp_text(text: str | None) -> str | None:
    """Markdown → WhatsApp: ``[t](u)`` → ``t: u``; ``**b**`` → ``*b*``;
    strips header hashes. Idempotent and safe on plain text."""
    if not text:
        return text
    out = _MD_LINK.sub(lambda m: f"{m.group(1)}: {m.group(2)}", text)
    out = _MD_BOLD.sub(r"*\1*", out)
    out = _MD_HEADER.sub("", out)
    return out
