"""RBAC matrix — every admin-gated endpoint must reject operator (403) and
allow tenant_admin/superadmin.

We only verify the gating bit. The exact success status (200/201/202/204) and
body shape aren't asserted, because endpoints may return 4xx for other reasons
(missing referenced resource, embedding service offline, …) — those are
verified in route-specific test files.

The matrix covers one endpoint per admin-gated route module so a future
refactor that drops `Depends(require_tenant_admin)` from a whole file gets
caught here. Endpoint-specific RBAC (e.g. users superadmin-only) lives in its
own file (`test_users_rbac.py`).
"""

from __future__ import annotations

import pytest

# (method, path, payload, allowed_roles)
# Bodies are minimal and pass Pydantic validation so we always reach the
# `Depends(require_tenant_admin)` check.
RBAC_MATRIX: list[tuple[str, str, dict | None, set[str]]] = [
    # ── workflows: POST /api/v1/workflows ──
    (
        "POST",
        "/api/v1/workflows",
        {
            "name": "rbac matrix probe",
            "trigger_type": "message_received",
            "definition": {"nodes": [], "edges": []},
            "active": False,
        },
        {"tenant_admin", "superadmin"},
    ),
    # ── agents: POST /api/v1/agents ──
    (
        "POST",
        "/api/v1/agents",
        {"name": "rbac matrix probe"},
        {"tenant_admin", "superadmin"},
    ),
    # ── customer-fields: POST /api/v1/customer-fields/definitions ──
    (
        "POST",
        "/api/v1/customer-fields/definitions",
        {
            "key": "rbac_matrix_probe",
            "label": "RBAC probe",
            "field_type": "text",
            "ordering": 0,
        },
        {"tenant_admin", "superadmin"},
    ),
    # ── tenants: PUT /api/v1/tenants/timezone ──
    (
        "PUT",
        "/api/v1/tenants/timezone",
        {"timezone": "America/Mexico_City"},
        {"tenant_admin", "superadmin"},
    ),
    # ── knowledge: POST /api/v1/knowledge/faqs ──
    (
        "POST",
        "/api/v1/knowledge/faqs",
        {"question": "¿probe?", "answer": "probe response"},
        {"tenant_admin", "superadmin"},
    ),
]

ROLE_ORDER = ["operator", "tenant_admin", "superadmin"]


@pytest.mark.parametrize("method,path,payload,allowed", RBAC_MATRIX)
def test_rbac_matrix(
    method,
    path,
    payload,
    allowed,
    client_operator,
    client_tenant_admin,
    client_superadmin,
):
    clients = {
        "operator": client_operator,
        "tenant_admin": client_tenant_admin,
        "superadmin": client_superadmin,
    }
    for role in ROLE_ORDER:
        client = clients[role]
        resp = client.request(method, path, json=payload)
        if role in allowed:
            assert resp.status_code != 403, (
                f"{role} should NOT be denied {method} {path}; "
                f"got {resp.status_code}: {resp.text[:200]}"
            )
        else:
            assert resp.status_code == 403, (
                f"{role} should be denied {method} {path}; "
                f"got {resp.status_code}: {resp.text[:200]}"
            )
