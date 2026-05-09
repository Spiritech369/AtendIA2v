from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException, status

from atendia.config import get_settings
from atendia.storage.base import StorageBackend

# Allowed extensions and the MIME types we accept for them. Both the
# Content-Type header and the magic-byte sniff (see ``_sniff_kind``) must
# agree with the extension before bytes are written.
ALLOWED_EXTENSIONS: dict[str, set[str]] = {
    ".pdf": {"application/pdf"},
    ".docx": {"application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
    ".xlsx": {"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"},
    ".csv": {"text/csv", "application/csv", "application/vnd.ms-excel", "text/plain"},
    ".txt": {"text/plain"},
}


def _sniff_kind(data: bytes) -> str | None:
    """Return one of {"pdf", "zip", "text"} based on the first bytes of the
    payload, or ``None`` if it doesn't match any of our allowed types.

    PDF: ``%PDF-`` magic.
    DOCX/XLSX: zip header (``PK\\x03\\x04`` or empty-archive ``PK\\x05\\x06``
    or spanned-archive ``PK\\x07\\x08``).
    TXT/CSV: must decode as UTF-8 (best-effort) without obvious binary noise.

    No new dependencies — just stdlib byte inspection.
    """
    if data.startswith(b"%PDF-"):
        return "pdf"
    if data[:4] in (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"):
        return "zip"
    try:
        head = data[:2048].decode("utf-8")
    except UnicodeDecodeError:
        return None
    # Reject if it contains a NUL — UTF-8 text rarely does, but a misnamed
    # binary that happens to decode often will.
    if "\x00" in head:
        return None
    return "text"


def _expected_kind(ext: str) -> str:
    if ext == ".pdf":
        return "pdf"
    if ext in (".docx", ".xlsx"):
        return "zip"
    return "text"


class LocalStorageBackend(StorageBackend):
    def __init__(
        self,
        upload_dir: str,
        *,
        max_file_size_bytes: int,
        tenant_quota_bytes: int,
    ) -> None:
        self.root = Path(upload_dir).resolve()
        self.max_file_size_bytes = max_file_size_bytes
        self.tenant_quota_bytes = tenant_quota_bytes
        self.root.mkdir(parents=True, exist_ok=True)

    async def save(
        self,
        tenant_id: str,
        filename: str,
        data: bytes,
        content_type: str | None = None,
    ) -> str:
        ext = Path(filename or "").suffix.lower()
        if ext not in ALLOWED_EXTENSIONS:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "file type is not allowed")
        if content_type and content_type not in ALLOWED_EXTENSIONS[ext]:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "file mime type is not allowed")
        if not data:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "file is empty")
        if len(data) > self.max_file_size_bytes:
            raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "file is too large")

        # Magic-byte check defends against an attacker who renames a binary
        # to ``.pdf`` and supplies the matching Content-Type — both of which
        # are easy to forge from curl.
        sniffed = _sniff_kind(data)
        expected = _expected_kind(ext)
        if sniffed != expected:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "file contents do not match the declared extension",
            )

        tenant_dir = self._tenant_dir(tenant_id)
        tenant_dir.mkdir(parents=True, exist_ok=True)
        if self._tenant_usage(tenant_dir) + len(data) > self.tenant_quota_bytes:
            raise HTTPException(
                status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                "tenant upload quota exceeded",
            )

        target = tenant_dir / f"{uuid4().hex}{ext}"
        target.write_bytes(data)
        return f"{tenant_id}/{target.name}"

    async def read(self, tenant_id: str, key: str) -> bytes:
        return self._resolve_key(tenant_id, key).read_bytes()

    async def delete(self, tenant_id: str, key: str) -> None:
        try:
            self._resolve_key(tenant_id, key).unlink()
        except FileNotFoundError:
            return

    def _tenant_dir(self, tenant_id: str) -> Path:
        return (self.root / tenant_id).resolve()

    def _resolve_key(self, tenant_id: str, key: str) -> Path:
        path = Path(key)
        # The key shape we hand out from save() is exactly ``{tenant_id}/{file}``.
        # Anything else — absolute paths, traversal, deeper nesting, or a key
        # that names another tenant's directory — gets rejected here.
        if path.is_absolute() or ".." in path.parts or len(path.parts) != 2:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid storage key")
        if path.parts[0] != tenant_id:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "storage key does not belong to this tenant",
            )
        resolved = (self.root / path).resolve()
        if not resolved.is_relative_to(self.root):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid storage key")
        return resolved

    @staticmethod
    def _tenant_usage(tenant_dir: Path) -> int:
        return sum(p.stat().st_size for p in tenant_dir.rglob("*") if p.is_file())


def get_storage_backend() -> StorageBackend:
    settings = get_settings()
    return LocalStorageBackend(
        settings.upload_dir,
        max_file_size_bytes=settings.upload_max_file_size_bytes,
        tenant_quota_bytes=settings.upload_tenant_quota_bytes,
    )
