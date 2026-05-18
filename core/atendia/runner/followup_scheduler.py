"""Schedule, cancel and render silence follow-up reminders."""

from datetime import UTC, datetime, timedelta
from string import Formatter
from typing import Any, Final
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from atendia.db.models.tenant import Tenant

FOLLOWUP_KINDS: Final[tuple[str, ...]] = ("3h_silence", "12h_silence")
_DELAYS: Final[dict[str, timedelta]] = {
    "3h_silence": timedelta(hours=3),
    "12h_silence": timedelta(hours=12),
}
_DEFAULT_BODIES: Final[dict[str, str]] = {
    "3h_silence": (
        "En lugar de gastar en el camión, puedes invertirlo mejor en "
        "tu moto. Aquí estoy para ayudarte con eso."
    ),
    "12h_silence": (
        "Hola, ¿sigues en pie con tu {modelo_moto}?{plan_credito_sentence} "
        "El único paso que falta eres tú."
    ),
}


def _kind_for_delay(delay_hours: int) -> str:
    if delay_hours == 3:
        return "3h_silence"
    if delay_hours == 12:
        return "12h_silence"
    return f"silence_{delay_hours}h"


def default_followup_config(*, enabled: bool = True) -> dict[str, Any]:
    return {
        "enabled": enabled,
        "schedule": [
            {"kind": "3h_silence", "delay_hours": 3, "body": _DEFAULT_BODIES["3h_silence"]},
            {"kind": "12h_silence", "delay_hours": 12, "body": _DEFAULT_BODIES["12h_silence"]},
        ],
    }


def normalize_followup_config(config: object, *, enabled: bool = True) -> dict[str, Any]:
    normalized = default_followup_config(enabled=enabled)
    if not isinstance(config, dict):
        return normalized

    if isinstance(config.get("enabled"), bool):
        normalized["enabled"] = bool(config["enabled"])

    schedule = config.get("schedule")
    if isinstance(schedule, list):
        cleaned: list[dict[str, Any]] = []
        seen: set[int] = set()
        for item in schedule:
            if not isinstance(item, dict):
                continue
            try:
                delay_hours = int(item.get("delay_hours"))
            except (TypeError, ValueError):
                continue
            if delay_hours < 1 or delay_hours > 23 or delay_hours in seen:
                continue
            seen.add(delay_hours)
            kind = str(item.get("kind") or _kind_for_delay(delay_hours))[:40]
            body = str(item.get("body") or _DEFAULT_BODIES.get(kind) or "").strip()
            if not body:
                body = "Hola, ¿seguimos con tu trámite? Aquí estoy si necesitas ayuda."
            cleaned.append({"kind": kind, "delay_hours": delay_hours, "body": body[:700]})
        if cleaned:
            normalized["schedule"] = sorted(cleaned, key=lambda row: row["delay_hours"])[:5]

    return normalized


async def load_followup_config(*, session: AsyncSession, tenant_id: UUID) -> dict[str, Any]:
    tenant = (
        await session.execute(select(Tenant).where(Tenant.id == tenant_id))
    ).scalar_one_or_none()
    if tenant is None:
        return default_followup_config(enabled=False)
    return normalize_followup_config(
        (tenant.config or {}).get("followups"),
        enabled=bool(tenant.followups_enabled),
    )


async def schedule_followups_after_outbound(
    *,
    session: AsyncSession,
    conversation_id: UUID,
    tenant_id: UUID,
    extracted_snapshot: dict,
) -> None:
    """Insert configured pending follow-ups after an outbound bot turn."""
    cfg = await load_followup_config(session=session, tenant_id=tenant_id)
    if not cfg["enabled"]:
        return

    now = datetime.now(UTC)
    for item in cfg["schedule"]:
        kind = item["kind"]
        run_at = now + timedelta(hours=int(item["delay_hours"]))
        await session.execute(
            text(
                "INSERT INTO followups_scheduled "
                "(conversation_id, tenant_id, run_at, status, kind, context) "
                "SELECT :cid, :tid, :ra, 'pending', "
                "       CAST(:k AS VARCHAR), CAST(:ctx AS JSONB) "
                "WHERE NOT EXISTS ("
                "  SELECT 1 FROM followups_scheduled "
                "  WHERE conversation_id = :cid "
                "    AND kind = CAST(:k AS VARCHAR) "
                "    AND status = 'pending' "
                "    AND cancelled_at IS NULL"
                ")"
            ),
            {
                "cid": conversation_id,
                "tid": tenant_id,
                "ra": run_at,
                "k": kind,
                "ctx": __import__("json").dumps(extracted_snapshot),
            },
        )


async def cancel_pending_followups(
    *,
    session: AsyncSession,
    conversation_id: UUID,
) -> int:
    """Cancel pending follow-ups for all conversations belonging to the same customer."""
    customer_id = (
        await session.execute(
            text("SELECT customer_id FROM conversations WHERE id = :cid"),
            {"cid": conversation_id},
        )
    ).scalar_one_or_none()
    if customer_id is None:
        return 0

    result = await session.execute(
        text(
            "UPDATE followups_scheduled "
            "SET status = 'cancelled', cancelled_at = :now "
            "WHERE conversation_id IN ("
            "  SELECT id FROM conversations WHERE customer_id = :customer_id"
            ") "
            "  AND status = 'pending' "
            "  AND cancelled_at IS NULL"
        ),
        {"customer_id": customer_id, "now": datetime.now(UTC)},
    )
    return result.rowcount or 0


def render_followup_body(
    *,
    kind: str,
    extracted_data: dict,
    template: str | None = None,
) -> str:
    """Render a configured follow-up with live extracted_data."""

    def _val(name: str, default: str) -> str:
        v = extracted_data.get(name)
        if isinstance(v, dict):
            v = v.get("value")
        return str(v) if v else default

    values = {
        "modelo_moto": _val("modelo_moto", "moto"),
        "plan_credito": _val("plan_credito", ""),
    }
    values["plan_credito_sentence"] = (
        f" Tu plan {values['plan_credito']} sigue activo." if values["plan_credito"] else ""
    )

    if template:
        fields = {name for _, name, _, _ in Formatter().parse(template) if name}
        try:
            return template.format(**{name: values.get(name, "") for name in fields})
        except Exception:
            pass

    if kind == "3h_silence":
        return _DEFAULT_BODIES["3h_silence"]
    if kind == "12h_silence":
        return _DEFAULT_BODIES["12h_silence"].format(**values)
    return "Hola, ¿seguimos con tu trámite? Aquí estoy si necesitas ayuda."
