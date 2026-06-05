from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any
from uuid import UUID

from atendia.config import Settings

REPORTS_DIR = Path(__file__).resolve().parents[3] / "docs" / "reports"
APPROVAL_PREFIX = "agent_runtime_model_provider_approval_record"


@dataclass(frozen=True)
class ProviderApprovalRecord:
    approved: bool
    path: Path | None = None
    approver: str | None = None
    tenant_id: str | None = None
    agent_id: str | None = None
    provider: str | None = None
    model: str | None = None
    retention_mode: str | None = None
    region_data_policy: str | None = None
    allowed_data_categories: list[str] = field(default_factory=list)
    forbidden_data_categories: list[str] = field(default_factory=list)
    scope: list[str] = field(default_factory=list)
    send_enabled: bool = False
    actions_enabled: bool = False
    workflow_events_enabled: bool = False
    reasons: list[str] = field(default_factory=list)


def expected_approval_record_path(
    *,
    report_date: date,
    reports_dir: Path = REPORTS_DIR,
) -> Path:
    return reports_dir / f"{APPROVAL_PREFIX}_{report_date:%Y_%m_%d}.md"


def write_pending_approval_record(
    *,
    tenant_id: UUID | str,
    agent_id: UUID | str,
    report_date: date,
    reports_dir: Path = REPORTS_DIR,
) -> Path:
    path = expected_approval_record_path(report_date=report_date, reports_dir=reports_dir)
    if path.exists():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"""# Agent Runtime Model Provider Approval Record - {report_date:%Y-%m-%d}

- approval_status: `not_approved`
- approver: `missing`
- tenant_id: `{tenant_id}`
- agent_id: `{agent_id}`
- provider: `openai`
- model: `missing`
- retention mode: `missing`
- region/data policy: `missing`
- allowed data categories: `none_approved`
- forbidden data categories: `pii_not_needed`, `attachments`, `tokens`, `secrets`, `internal_config`
- scope: `test-turn/preview/simulation/shadow only`
- send_enabled: `false`
- actions_enabled: `false`
- workflow_events_enabled: `false`

No external provider may be executed until this record is updated with explicit approval.
""",
        encoding="utf-8",
    )
    return path


def load_provider_approval_record(
    *,
    tenant_id: UUID | str,
    agent_id: UUID | str,
    provider: str,
    report_date: date,
    reports_dir: Path = REPORTS_DIR,
) -> ProviderApprovalRecord:
    path = expected_approval_record_path(report_date=report_date, reports_dir=reports_dir)
    if not path.exists():
        return ProviderApprovalRecord(
            approved=False,
            path=path,
            provider=provider,
            tenant_id=str(tenant_id),
            agent_id=str(agent_id),
            reasons=["approval record not found"],
        )
    values = _parse_record(path.read_text(encoding="utf-8"))
    record = ProviderApprovalRecord(
        approved=_truthy(values.get("approval_status")) or _truthy(values.get("approved")),
        path=path,
        approver=values.get("approver"),
        tenant_id=values.get("tenant_id"),
        agent_id=values.get("agent_id"),
        provider=values.get("provider"),
        model=values.get("model"),
        retention_mode=values.get("retention mode") or values.get("retention_mode"),
        region_data_policy=values.get("region/data policy") or values.get("region_data_policy"),
        allowed_data_categories=_list_value(values.get("allowed data categories")),
        forbidden_data_categories=_list_value(values.get("forbidden data categories")),
        scope=_list_value(values.get("scope")),
        send_enabled=_truthy(values.get("send_enabled")),
        actions_enabled=_truthy(values.get("actions_enabled")),
        workflow_events_enabled=_truthy(values.get("workflow_events_enabled")),
    )
    reasons = _approval_reasons(
        record,
        tenant_id=str(tenant_id),
        agent_id=str(agent_id),
        provider=provider,
    )
    return ProviderApprovalRecord(
        **{**record.__dict__, "approved": not reasons, "reasons": reasons}
    )


def provider_external_allowed(
    *,
    tenant_id: UUID | str,
    agent_id: UUID | str,
    provider: str,
    settings: Settings,
    report_date: date,
    reports_dir: Path = REPORTS_DIR,
) -> ProviderApprovalRecord:
    record = load_provider_approval_record(
        tenant_id=tenant_id,
        agent_id=agent_id,
        provider=provider,
        report_date=report_date,
        reports_dir=reports_dir,
    )
    reasons = list(record.reasons)
    if not settings.agent_runtime_v2_enabled:
        reasons.append("global runtime v2 flag is disabled")
    if settings.agent_runtime_v2_send_enabled:
        reasons.append("global send flag is enabled")
    if settings.agent_runtime_v2_actions_enabled:
        reasons.append("global actions flag is enabled")
    if settings.agent_runtime_v2_workflow_events_enabled:
        reasons.append("global workflow events flag is enabled")
    if settings.agent_runtime_v2_model_provider != provider:
        reasons.append("global model provider does not match requested provider")
    return ProviderApprovalRecord(
        **{**record.__dict__, "approved": not reasons, "reasons": reasons}
    )


def local_deterministic_readiness_final() -> bool:
    return False


def _approval_reasons(
    record: ProviderApprovalRecord,
    *,
    tenant_id: str,
    agent_id: str,
    provider: str,
) -> list[str]:
    reasons: list[str] = []
    if not record.approver or record.approver in {"missing", "none"}:
        reasons.append("approver missing")
    if record.tenant_id != tenant_id:
        reasons.append("tenant_id mismatch")
    if record.agent_id != agent_id:
        reasons.append("agent_id mismatch")
    if record.provider != provider:
        reasons.append("provider mismatch")
    if not record.model or record.model == "missing":
        reasons.append("model missing")
    if not record.retention_mode or record.retention_mode == "missing":
        reasons.append("retention mode missing")
    if not record.region_data_policy or record.region_data_policy == "missing":
        reasons.append("region/data policy missing")
    if not record.allowed_data_categories or record.allowed_data_categories == ["none_approved"]:
        reasons.append("allowed data categories missing")
    scope_text = " ".join(record.scope).casefold()
    for required in ("test-turn", "preview", "simulation", "shadow"):
        if required not in scope_text:
            reasons.append(f"scope missing {required}")
    if record.send_enabled:
        reasons.append("approval record allows send")
    if record.actions_enabled:
        reasons.append("approval record allows actions")
    if record.workflow_events_enabled:
        reasons.append("approval record allows workflow events")
    return reasons


def _parse_record(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in text.splitlines():
        match = re.match(r"\s*[-*]\s*([^:]+):\s*(.+?)\s*$", line)
        if not match:
            continue
        key = match.group(1).strip().casefold()
        values[key] = _strip_code(match.group(2).strip())
    return values


def _strip_code(value: str) -> str:
    value = value.strip()
    if value.startswith("`") and value.endswith("`"):
        return value[1:-1].strip()
    return value


def _truthy(value: Any) -> bool:
    return str(value or "").strip().casefold() in {"approved", "true", "yes", "si", "sí"}


def _list_value(value: str | None) -> list[str]:
    if not value:
        return []
    return [
        item.strip().strip("`")
        for item in re.split(r",|;", value)
        if item.strip()
    ]
