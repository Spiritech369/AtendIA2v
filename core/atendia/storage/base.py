from typing import Protocol


class StorageBackend(Protocol):
    """Tenant-scoped object storage.

    All operations take an explicit ``tenant_id`` so the backend can enforce
    that a caller is never able to read or delete another tenant's bytes,
    even if the caller passes a key that came from somewhere else (an old
    DB row, a stale cache, an attacker-supplied id). Keys returned by
    :meth:`save` always begin with ``{tenant_id}/``.
    """

    async def save(
        self,
        tenant_id: str,
        filename: str,
        data: bytes,
        content_type: str | None = None,
    ) -> str:
        """Save file and return a relative storage key (``{tenant_id}/{name}``)."""

    async def read(self, tenant_id: str, key: str) -> bytes:
        """Read bytes for ``key`` belonging to ``tenant_id`` — caller must own the key."""

    async def delete(self, tenant_id: str, key: str) -> None:
        """Delete ``key`` if it exists and belongs to ``tenant_id``."""
