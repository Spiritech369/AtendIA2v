"""FastAPI dependency layer for the operator dashboard API (Phase 4).

Three building blocks:

* `current_user` — reads the httpOnly session cookie, returns AuthUser.
* `current_tenant_id` — resolves which tenant a request applies to:
    - operator → forced to user.tenant_id (JWT, not query — prevents
      a curious operator from poking at other tenants' rows).
    - superadmin → must pass `?tid=...` explicitly.
* `require_superadmin` — gate for `/api/v1/admin/*` style routes.
* `require_tenant_admin` — gate for tenant config/admin writes.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import Depends, HTTPException, Query, status
from fastapi import status as http_status
from atendia.providers.advisors import AdvisorProvider
from atendia.providers.vehicles import VehicleProvider
from atendia.providers.messaging import MessageActionProvider
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from atendia.api._auth_helpers import AuthUser, get_current_user
from atendia.db.models.tenant import Tenant
from atendia.db.session import get_db_session

# Re-export for convenience: routes can `Depends(current_user)`.
current_user = get_current_user

TENANT_SCOPED_ROLES = {
    "operator",
    "tenant_admin",
    "manager",
    "supervisor",
    "sales_agent",
    "ai_reviewer",
}


async def current_tenant_id(
    user: AuthUser = Depends(current_user),
    tid: UUID | None = Query(default=None, description="Override (superadmin only)"),
) -> UUID:
    """Resolve the tenant the request applies to.

    - operator / tenant_admin: pinned to ``user.tenant_id`` from the JWT —
      the ``?tid=`` query param is ignored so a curious operator can't poke
      at other tenants by editing the URL.
    - superadmin: ``?tid=`` overrides; if absent, falls back to
      ``user.tenant_id`` (their home tenant). The previous behaviour was to
      400 when ``tid`` was missing, which broke the SPA on every
      conversation-list load (sesión 6 fix).
    """
    if user.role in TENANT_SCOPED_ROLES:
        if user.tenant_id is None:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "operator session missing tenant_id")
        return user.tenant_id
    if user.role == "superadmin":
        if tid is not None:
            return tid
        if user.tenant_id is not None:
            return user.tenant_id
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "superadmin has no home tenant — pass ?tid=<uuid> to scope",
        )
    raise HTTPException(status.HTTP_403_FORBIDDEN, "unknown role")


async def require_superadmin(
    user: AuthUser = Depends(current_user),
) -> AuthUser:
    if user.role != "superadmin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "superadmin only")
    return user


async def require_tenant_admin(
    user: AuthUser = Depends(current_user),
) -> AuthUser:
    if user.role not in ("tenant_admin", "superadmin"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "tenant admin only")
    return user


async def demo_tenant(
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> bool:
    """Return True when the current request's tenant is a demo/sandbox tenant.

    Routes use this to gate mock data and simulated actions.
    Non-demo tenants that hit an unimplemented provider receive 501.
    """
    result = await session.execute(select(Tenant).where(Tenant.id == tenant_id))
    tenant = result.scalar_one_or_none()
    return bool(tenant and tenant.is_demo)


# ── Provider factories ────────────────────────────────────────────────────────
# Each factory returns:
# * is_demo=True  → the hardcoded demo provider (constants).
# * is_demo=False → for advisors/vehicles, the DB-backed provider so the
#   operator's own data shows up. The factory still returns Empty when no
#   session is available (used by legacy tests and code paths that don't
#   have a request scope); route-facing FastAPI deps pass the session
#   through so the DB-backed provider gets used end-to-end.


def _get_advisor_provider_for(is_demo: bool) -> AdvisorProvider:
    """Sessionless factory — used by tests and code paths without DB access.

    Non-demo still returns Empty here; the route-facing
    ``get_advisor_provider`` dep is what wires the DB-backed provider.
    """
    if is_demo:
        from atendia._demo.providers import DemoAdvisorProvider

        return DemoAdvisorProvider()
    from atendia.providers.empty import EmptyAdvisorProvider

    return EmptyAdvisorProvider()


def _get_vehicle_provider_for(is_demo: bool) -> VehicleProvider:
    if is_demo:
        from atendia._demo.providers import DemoVehicleProvider

        return DemoVehicleProvider()
    from atendia.providers.empty import EmptyVehicleProvider

    return EmptyVehicleProvider()


def _get_messaging_provider_for(is_demo: bool) -> MessageActionProvider:
    if is_demo:
        from atendia._demo.providers import DemoMessageActionProvider

        return DemoMessageActionProvider()
    # No-op messaging — the appointment side-effect (send reminder etc.)
    # acks as "noop" so the UI doesn't error. When real Meta-backed
    # messaging lands we swap this for the real adapter.
    from atendia.providers.empty import EmptyMessageActionProvider

    return EmptyMessageActionProvider()


async def get_advisor_provider(
    is_demo: bool = Depends(demo_tenant),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> AdvisorProvider:
    if is_demo:
        from atendia._demo.providers import DemoAdvisorProvider

        return DemoAdvisorProvider()
    from atendia.providers.db_advisors import DBAdvisorProvider

    return DBAdvisorProvider(session=session, tenant_id=tenant_id)


async def get_vehicle_provider(
    is_demo: bool = Depends(demo_tenant),
    tenant_id: UUID = Depends(current_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> VehicleProvider:
    if is_demo:
        from atendia._demo.providers import DemoVehicleProvider

        return DemoVehicleProvider()
    from atendia.providers.db_vehicles import DBVehicleProvider

    return DBVehicleProvider(session=session, tenant_id=tenant_id)


async def get_messaging_provider(
    is_demo: bool = Depends(demo_tenant),
) -> MessageActionProvider:
    return _get_messaging_provider_for(is_demo)
