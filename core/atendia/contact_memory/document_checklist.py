from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

DocumentStatus = str
MISSING: DocumentStatus = "missing"
RECEIVED: DocumentStatus = "received"
ACCEPTED: DocumentStatus = "accepted"
REJECTED: DocumentStatus = "rejected"


class DocumentChecklistService:
    """Build and reconcile per-plan document checklists.

    The service is domain-neutral: requirements and labels come from tenant
    pipeline/config JSON, not from runtime code. It can be used with explicit
    dictionaries in tests or with a DB session to load the active tenant
    pipeline.
    """

    def __init__(
        self,
        session: AsyncSession | None = None,
        *,
        document_requirements: dict[str, list[str]] | None = None,
        documents_catalog: list[dict[str, Any]] | None = None,
        selection_catalog: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        self._session = session
        self._document_requirements = deepcopy(document_requirements or {})
        self._documents_catalog = deepcopy(documents_catalog or [])
        self._selection_catalog = deepcopy(selection_catalog or {})

    async def get_required_documents_for_plan(
        self,
        tenant_id: UUID | str,
        plan_id: str,
    ) -> list[str]:
        requirements, _, selection_catalog = await self._load_config(tenant_id)
        canonical_plan = _canonical_plan(plan_id, selection_catalog)
        return list(requirements.get(canonical_plan) or [])

    async def build_document_checklist_for_tenant(
        self,
        tenant_id: UUID | str,
        plan_id: str,
        *,
        current_documents: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        requirements, catalog, selection_catalog = await self._load_config(tenant_id)
        return self.build_document_checklist(
            _canonical_plan(plan_id, selection_catalog),
            current_documents=current_documents,
            document_requirements=requirements,
            documents_catalog=catalog,
        )

    def build_document_checklist(
        self,
        plan_id: str,
        *,
        current_documents: dict[str, Any] | None = None,
        document_requirements: dict[str, list[str]] | None = None,
        documents_catalog: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        requirements = document_requirements or self._document_requirements
        catalog = documents_catalog or self._documents_catalog
        labels = {str(item.get("key")): item for item in catalog}
        existing = current_documents or {}
        checklist: list[dict[str, Any]] = []
        for key in requirements.get(plan_id, []):
            raw_state = _doc_state(existing.get(key))
            spec = labels.get(key, {})
            checklist.append(
                {
                    "key": key,
                    "label": spec.get("label") or key,
                    "hint": spec.get("hint") or "",
                    "status": raw_state.get("status") or MISSING,
                    "received_at": raw_state.get("received_at"),
                    "accepted_at": raw_state.get("accepted_at"),
                    "rejected_reason": raw_state.get("rejected_reason"),
                    "evidence": list(raw_state.get("evidence") or []),
                }
            )
        return checklist

    def mark_document_received(
        self,
        checklist: list[dict[str, Any]],
        document_key: str,
        *,
        evidence: list[str] | None = None,
        received_at: datetime | None = None,
    ) -> list[dict[str, Any]]:
        return _mark(
            checklist,
            document_key,
            {
                "status": RECEIVED,
                "received_at": (received_at or datetime.now(UTC)).isoformat(),
                "accepted_at": None,
                "rejected_reason": None,
                "evidence": list(evidence or []),
            },
        )

    def mark_document_accepted(
        self,
        checklist: list[dict[str, Any]],
        document_key: str,
        *,
        accepted_at: datetime | None = None,
    ) -> list[dict[str, Any]]:
        return _mark(
            checklist,
            document_key,
            {
                "status": ACCEPTED,
                "accepted_at": (accepted_at or datetime.now(UTC)).isoformat(),
                "rejected_reason": None,
            },
        )

    def mark_document_rejected(
        self,
        checklist: list[dict[str, Any]],
        document_key: str,
        *,
        reason: str,
    ) -> list[dict[str, Any]]:
        return _mark(
            checklist,
            document_key,
            {"status": REJECTED, "accepted_at": None, "rejected_reason": reason},
        )

    def compute_missing_documents(self, checklist: list[dict[str, Any]]) -> list[str]:
        return [
            str(item["key"])
            for item in checklist
            if str(item.get("status") or MISSING) != ACCEPTED
        ]

    def compute_documentos_completos(self, checklist: list[dict[str, Any]]) -> bool:
        return bool(checklist) and not self.compute_missing_documents(checklist)

    def rebuild_checklist_on_plan_change(
        self,
        *,
        previous_checklist: list[dict[str, Any]],
        new_plan_id: str,
        document_requirements: dict[str, list[str]] | None = None,
        documents_catalog: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        previous_by_key = {str(item.get("key")): item for item in previous_checklist}
        return self.build_document_checklist(
            new_plan_id,
            current_documents=previous_by_key,
            document_requirements=document_requirements,
            documents_catalog=documents_catalog,
        )

    async def _load_config(
        self,
        tenant_id: UUID | str,
    ) -> tuple[dict[str, list[str]], list[dict[str, Any]], dict[str, dict[str, Any]]]:
        if self._session is None:
            return (
                deepcopy(self._document_requirements),
                deepcopy(self._documents_catalog),
                deepcopy(self._selection_catalog),
            )
        row = (
            await self._session.execute(
                text(
                    "SELECT definition FROM tenant_pipelines "
                    "WHERE tenant_id = :tenant_id AND active = true "
                    "ORDER BY version DESC LIMIT 1"
                ),
                {"tenant_id": str(tenant_id)},
            )
        ).mappings().first()
        definition = dict(row["definition"] or {}) if row else {}
        return (
            deepcopy(definition.get("document_requirements") or {}),
            deepcopy(definition.get("documents_catalog") or []),
            deepcopy(definition.get("selection_catalog") or {}),
        )


def _canonical_plan(plan_id: str, selection_catalog: dict[str, dict[str, Any]]) -> str:
    normalized = _fold(plan_id)
    for key, spec in selection_catalog.items():
        if normalized == _fold(key):
            return key
        aliases = list(spec.get("aliases") or [])
        label = spec.get("label")
        for value in [label, *aliases]:
            if value is not None and normalized == _fold(str(value)):
                return key
    return plan_id


def _doc_state(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if value is True:
        return {"status": ACCEPTED}
    if value:
        return {"status": str(value)}
    return {"status": MISSING}


def _mark(
    checklist: list[dict[str, Any]],
    document_key: str,
    patch: dict[str, Any],
) -> list[dict[str, Any]]:
    updated = deepcopy(checklist)
    for item in updated:
        if item.get("key") == document_key:
            item.update(patch)
            return updated
    updated.append({"key": document_key, "label": document_key, "hint": "", **patch})
    return updated


def _fold(value: str) -> str:
    return " ".join(value.casefold().strip().split())
