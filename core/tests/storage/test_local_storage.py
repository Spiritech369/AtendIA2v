"""Unit tests for the local storage backend.

Focus: the safety surface that the KB routes rely on.

- Tenant scoping: read/delete reject keys that don't belong to the calling
  tenant, even if the caller hands us a path that resolves under the storage
  root.
- Path traversal: ``..``, absolute paths, and oddly-shaped keys all 400.
- Magic-byte sniffer: the bytes of a file have to agree with its declared
  extension before save() writes anything.
"""
from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import HTTPException

from atendia.storage.local import LocalStorageBackend

PDF_HEADER = b"%PDF-1.7\n%minimal\n"
ZIP_HEADER = b"PK\x03\x04" + b"\x00" * 32


@pytest.fixture
def backend(tmp_path: Path) -> LocalStorageBackend:
    return LocalStorageBackend(
        str(tmp_path),
        max_file_size_bytes=1_000_000,
        tenant_quota_bytes=10_000_000,
    )


@pytest.mark.asyncio
async def test_save_pdf_accepts_correct_magic_bytes(backend: LocalStorageBackend) -> None:
    tid = uuid4().hex
    key = await backend.save(tid, "doc.pdf", PDF_HEADER, "application/pdf")
    assert key.startswith(f"{tid}/")
    assert key.endswith(".pdf")
    assert await backend.read(tid, key) == PDF_HEADER


@pytest.mark.asyncio
async def test_save_rejects_pdf_with_wrong_magic_bytes(backend: LocalStorageBackend) -> None:
    tid = uuid4().hex
    fake = b"this is not really a pdf, just text"
    with pytest.raises(HTTPException) as exc:
        await backend.save(tid, "doc.pdf", fake, "application/pdf")
    assert exc.value.status_code == 400
    assert "do not match" in exc.value.detail.lower()


@pytest.mark.asyncio
async def test_save_rejects_zip_renamed_to_pdf(backend: LocalStorageBackend) -> None:
    tid = uuid4().hex
    with pytest.raises(HTTPException) as exc:
        await backend.save(tid, "trojan.pdf", ZIP_HEADER, "application/pdf")
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_save_accepts_docx_with_zip_header(backend: LocalStorageBackend) -> None:
    tid = uuid4().hex
    key = await backend.save(
        tid,
        "doc.docx",
        ZIP_HEADER,
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
    assert key.endswith(".docx")


@pytest.mark.asyncio
async def test_save_accepts_csv_text(backend: LocalStorageBackend) -> None:
    tid = uuid4().hex
    body = b"a,b,c\n1,2,3\n"
    key = await backend.save(tid, "data.csv", body, "text/csv")
    assert (await backend.read(tid, key)) == body


@pytest.mark.asyncio
async def test_save_rejects_disallowed_extension(backend: LocalStorageBackend) -> None:
    with pytest.raises(HTTPException) as exc:
        await backend.save(uuid4().hex, "evil.exe", b"MZ\x90\x00", None)
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_save_rejects_oversize(backend: LocalStorageBackend) -> None:
    tid = uuid4().hex
    huge = PDF_HEADER + b"\x00" * (backend.max_file_size_bytes + 1)
    with pytest.raises(HTTPException) as exc:
        await backend.save(tid, "big.pdf", huge, "application/pdf")
    assert exc.value.status_code == 413


@pytest.mark.asyncio
async def test_read_rejects_cross_tenant_key(backend: LocalStorageBackend) -> None:
    tid_a = uuid4().hex
    tid_b = uuid4().hex
    key = await backend.save(tid_a, "doc.pdf", PDF_HEADER, "application/pdf")
    # Tenant B asking for tenant A's storage key — even though the file is
    # under the storage root, the resolver must reject this.
    with pytest.raises(HTTPException) as exc:
        await backend.read(tid_b, key)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_delete_rejects_cross_tenant_key(backend: LocalStorageBackend) -> None:
    tid_a = uuid4().hex
    tid_b = uuid4().hex
    key = await backend.save(tid_a, "doc.pdf", PDF_HEADER, "application/pdf")
    with pytest.raises(HTTPException) as exc:
        await backend.delete(tid_b, key)
    assert exc.value.status_code == 403
    # File is still there, untouched.
    assert await backend.read(tid_a, key) == PDF_HEADER


@pytest.mark.asyncio
async def test_path_traversal_rejected(backend: LocalStorageBackend) -> None:
    tid = uuid4().hex
    for bad_key in [
        f"{tid}/../{tid}/anything.pdf",
        "../etc/passwd",
        "/etc/passwd",
        f"{tid}/sub/file.pdf",  # nested deeper than tenant_id/file
    ]:
        with pytest.raises(HTTPException):
            await backend.read(tid, bad_key)


@pytest.mark.asyncio
async def test_delete_missing_key_is_silent(backend: LocalStorageBackend) -> None:
    tid = uuid4().hex
    # Key that's structurally valid but never existed.
    fake_key = f"{tid}/{uuid4().hex}.pdf"
    # Tenant_dir doesn't exist yet either — delete is best-effort.
    Path(backend.root / tid).mkdir(parents=True, exist_ok=True)
    await backend.delete(tid, fake_key)


@pytest.mark.asyncio
async def test_quota_enforced(backend: LocalStorageBackend, tmp_path: Path) -> None:
    tight = LocalStorageBackend(
        str(tmp_path / "tight"),
        max_file_size_bytes=1_000_000,
        tenant_quota_bytes=len(PDF_HEADER) + 4,  # one file fits, the next won't
    )
    tid = uuid4().hex
    await tight.save(tid, "a.pdf", PDF_HEADER, "application/pdf")
    with pytest.raises(HTTPException) as exc:
        await tight.save(tid, "b.pdf", PDF_HEADER, "application/pdf")
    assert exc.value.status_code == 413
