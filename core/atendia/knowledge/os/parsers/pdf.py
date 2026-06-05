from __future__ import annotations

import fitz  # type: ignore[import-untyped]

from atendia.knowledge.os.parsers.base import ParsedDocument, ParsedSection, normalize_text

MAX_PDF_PAGES = 250


def parse_pdf(data: bytes, *, filename: str = "") -> ParsedDocument:
    warnings: list[str] = []
    sections: list[ParsedSection] = []
    with fitz.open(stream=data, filetype="pdf") as document:
        page_count = document.page_count
        if page_count > MAX_PDF_PAGES:
            warnings.append(f"pdf_page_limit:{page_count}>{MAX_PDF_PAGES}")
        for page_index in range(1, min(page_count, MAX_PDF_PAGES) + 1):
            page = document.load_page(page_index - 1)
            text = normalize_text(page.get_text("text"))
            if not text:
                warnings.append(f"empty_pdf_page:{page_index}")
                continue
            sections.append(
                ParsedSection(
                    text=text,
                    title=f"{filename or 'PDF'} page {page_index}",
                    metadata={
                        "file_type": "pdf",
                        "page": page_index,
                        "page_count": page_count,
                    },
                )
            )
    extracted = normalize_text("\n".join(section.text for section in sections))
    return ParsedDocument(
        extracted_text=extracted,
        sections=sections,
        metadata={
            "filename": filename,
            "file_type": "pdf",
            "page_count": page_count,
            "parsed_pages": len(sections),
        },
        warnings=warnings,
    )
