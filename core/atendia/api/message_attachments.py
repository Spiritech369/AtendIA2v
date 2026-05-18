from __future__ import annotations

import base64
from pathlib import Path
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from atendia.config import get_settings
from atendia.contracts.message import Attachment as CanonicalAttachment


def media_metadata_from_attachment(row) -> dict:
    return {
        "type": row["type"],
        "url": row["storage_url"],
        "mime_type": row["mime_type"],
        "caption": row["caption"],
        "original_filename": row["original_filename"],
        "file_size": row["file_size"],
        "status": row["status"],
    }


async def list_attachments_for_messages(
    session: AsyncSession,
    *,
    message_ids: list[UUID],
) -> dict[UUID, list[dict]]:
    if not message_ids:
        return {}
    rows = (
        await session.execute(
            text(
                """
                SELECT message_id, type, mime_type, storage_url, caption,
                       original_filename, file_size, status
                FROM message_attachments
                WHERE message_id = ANY(CAST(:ids AS uuid[]))
                ORDER BY created_at ASC, id ASC
                """
            ),
            {"ids": message_ids},
        )
    ).mappings()
    grouped: dict[UUID, list[dict]] = {}
    for row in rows:
        grouped.setdefault(row["message_id"], []).append(media_metadata_from_attachment(row))
    return grouped


def _local_upload_path(storage_url: str) -> Path | None:
    if not storage_url.startswith("/uploads/"):
        return None
    rel_path = Path(*storage_url.removeprefix("/uploads/").split("/"))
    return Path(get_settings().upload_dir) / rel_path


async def load_runner_attachments(
    session: AsyncSession,
    *,
    message_id: UUID,
) -> list[CanonicalAttachment]:
    rows = (
        await session.execute(
            text(
                """
                SELECT id, mime_type, storage_url, caption, status
                FROM message_attachments
                WHERE message_id = :message_id
                  AND status = 'ready'
                ORDER BY created_at ASC, id ASC
                """
            ),
            {"message_id": message_id},
        )
    ).mappings()

    attachments: list[CanonicalAttachment] = []
    for row in rows:
        mime_type = str(row["mime_type"] or "")
        if not mime_type.startswith("image/"):
            continue
        storage_url = str(row["storage_url"] or "")
        local_path = _local_upload_path(storage_url)
        if local_path is None or not local_path.exists():
            continue
        data_b64 = base64.b64encode(local_path.read_bytes()).decode("ascii")
        attachments.append(
            CanonicalAttachment(
                media_id=str(row["id"]),
                mime_type=mime_type,
                url=f"data:{mime_type};base64,{data_b64}",
                caption=row["caption"],
            )
        )
    return attachments


async def insert_message_attachment(
    session: AsyncSession,
    *,
    message_id: UUID,
    tenant_id: UUID,
    media: dict,
    sha256: str | None = None,
) -> None:
    await session.execute(
        text(
            """
            INSERT INTO message_attachments (
                message_id, tenant_id, type, mime_type, storage_url, caption,
                original_filename, file_size, sha256, status, metadata_json
            )
            VALUES (
                :message_id, :tenant_id, :type, :mime_type, :storage_url, :caption,
                :original_filename, :file_size, :sha256, 'ready',
                jsonb_build_object('source', 'baileys')
            )
            """
        ),
        {
            "message_id": message_id,
            "tenant_id": tenant_id,
            "type": media.get("type") or "document",
            "mime_type": media.get("mime_type") or "application/octet-stream",
            "storage_url": media.get("url"),
            "caption": media.get("caption"),
            "original_filename": media.get("original_filename"),
            "file_size": media.get("file_size"),
            "sha256": sha256,
        },
    )
