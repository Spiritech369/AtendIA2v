from __future__ import annotations

import csv
from io import StringIO

from atendia.knowledge.os.parsers.base import (
    ParsedDocument,
    ParsedSection,
    ParsedTable,
    normalize_text,
    stringify_cell,
)

MAX_CSV_ROWS = 10000


def parse_csv(data: bytes, *, filename: str = "") -> ParsedDocument:
    raw = data.decode("utf-8-sig", errors="replace")
    warnings: list[str] = []
    if "\ufffd" in raw:
        warnings.append("csv_decode_replacement_characters")
    sample = raw[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample)
    except csv.Error:
        dialect = csv.excel_tab if filename.casefold().endswith(".tsv") else csv.excel
        warnings.append("csv_dialect_fallback")
    rows = list(csv.reader(StringIO(raw), dialect=dialect))
    if not rows:
        return ParsedDocument(
            extracted_text="",
            metadata={"filename": filename, "file_type": "csv", "rows": 0},
            warnings=warnings,
        )
    if len(rows) > MAX_CSV_ROWS + 1:
        warnings.append(f"csv_row_limit:{len(rows)}>{MAX_CSV_ROWS}")
        rows = rows[: MAX_CSV_ROWS + 1]

    headers, data_rows, has_headers = _headers_and_rows(rows)
    structured_rows: list[dict[str, str]] = []
    lines: list[str] = []
    for index, row in enumerate(data_rows, start=1):
        record = {
            headers[col_index]: stringify_cell(row[col_index]) if col_index < len(row) else ""
            for col_index in range(len(headers))
        }
        structured_rows.append(record)
        lines.append(_row_to_text(record, row_index=index))

    text = normalize_text("\n".join(lines))
    return ParsedDocument(
        extracted_text=text,
        sections=[
            ParsedSection(
                text=text,
                title=filename or "CSV table",
                metadata={
                    "file_type": "csv",
                    "row_count": len(structured_rows),
                    "headers": headers,
                },
            )
        ]
        if text
        else [],
        tables=[
            ParsedTable(
                headers=headers,
                rows=structured_rows,
                reference={"table": 1},
                metadata={"has_headers": has_headers, "file_type": "csv"},
            )
        ],
        metadata={
            "filename": filename,
            "file_type": "csv",
            "headers": headers,
            "row_count": len(structured_rows),
        },
        warnings=warnings,
    )


def _headers_and_rows(rows: list[list[str]]) -> tuple[list[str], list[list[str]], bool]:
    first = [stringify_cell(cell) for cell in rows[0]]
    try:
        has_headers = csv.Sniffer().has_header("\n".join(",".join(row) for row in rows[:10]))
    except csv.Error:
        has_headers = any(cell and not _looks_numeric(cell) for cell in first)
    if has_headers:
        headers = [_normalize_header(cell, index) for index, cell in enumerate(first)]
        return headers, rows[1:], True
    width = max((len(row) for row in rows), default=0)
    return [f"column_{index + 1}" for index in range(width)], rows, False


def _normalize_header(value: str, index: int) -> str:
    normalized = value.strip() or f"column_{index + 1}"
    return normalized


def _looks_numeric(value: str) -> bool:
    try:
        float(value.replace(",", "").replace("$", ""))
        return True
    except ValueError:
        return False


def _row_to_text(row: dict[str, str], *, row_index: int) -> str:
    parts = [f"{key}: {value}" for key, value in row.items() if value]
    return f"row {row_index}: " + "; ".join(parts)
