from __future__ import annotations

from pathlib import Path

from atendia.knowledge.os.parsers.base import ParsedDocument, ParsedSection, ParsedTable
from atendia.knowledge.os.parsers.csv import parse_csv
from atendia.knowledge.os.parsers.docx import parse_docx
from atendia.knowledge.os.parsers.pdf import parse_pdf
from atendia.knowledge.os.parsers.text import parse_text
from atendia.knowledge.os.parsers.xlsx import parse_xlsx

IMAGE_SUFFIXES = {"jpg", "jpeg", "png", "webp", "gif", "tiff", "bmp"}


def parse_file(data: bytes, *, filename: str) -> ParsedDocument:
    suffix = Path(filename or "").suffix.lower().lstrip(".")
    if suffix == "pdf":
        return parse_pdf(data, filename=filename)
    if suffix == "docx":
        return parse_docx(data, filename=filename)
    if suffix in {"txt", "md"}:
        return parse_text(data, filename=filename)
    if suffix in {"csv", "tsv"}:
        return parse_csv(data, filename=filename)
    if suffix == "xlsx":
        return parse_xlsx(data, filename=filename)
    if suffix in IMAGE_SUFFIXES:
        return ParsedDocument(
            extracted_text="",
            metadata={
                "filename": filename,
                "file_type": suffix,
                "image_ingestion": "metadata_only",
            },
            warnings=["image_ocr_not_enabled"],
        )
    raise NotImplementedError(f"Unsupported Knowledge OS file type: {suffix or 'unknown'}")


__all__ = [
    "ParsedDocument",
    "ParsedSection",
    "ParsedTable",
    "parse_csv",
    "parse_docx",
    "parse_file",
    "parse_pdf",
    "parse_text",
    "parse_xlsx",
]
