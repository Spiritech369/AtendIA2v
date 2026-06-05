from __future__ import annotations

from atendia.knowledge.os.parsers.base import ParsedDocument, ParsedSection, normalize_text


def parse_text(data: bytes, *, filename: str = "") -> ParsedDocument:
    text = data.decode("utf-8-sig", errors="replace")
    normalized = normalize_text(text)
    suffix = filename.rsplit(".", 1)[-1].casefold() if "." in filename else "txt"
    warnings: list[str] = []
    if "\ufffd" in text:
        warnings.append("text_decode_replacement_characters")
    return ParsedDocument(
        extracted_text=normalized,
        sections=[
            ParsedSection(
                text=normalized,
                title=filename or "Text document",
                metadata={"file_type": suffix},
            )
        ]
        if normalized
        else [],
        metadata={"filename": filename, "file_type": suffix, "characters": len(normalized)},
        warnings=warnings,
    )
