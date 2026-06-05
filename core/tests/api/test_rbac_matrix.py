"""RBAC matrix for admin/config/write endpoints.

The matrix verifies the authorization gate only. Allowed roles may still
receive 4xx for route-specific reasons such as missing referenced resources.
"""

from __future__ import annotations

import pytest

# (method, path, payload, allowed_roles)
RBAC_MATRIX: list[tuple[str, str, dict | None, set[str]]] = [
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
    (
        "POST",
        "/api/v1/workflows/00000000-0000-0000-0000-000000000000/publish",
        {},
        {"tenant_admin", "superadmin"},
    ),
    (
        "POST",
        "/api/v1/agents",
        {"name": "rbac matrix probe"},
        {"tenant_admin", "superadmin"},
    ),
    (
        "POST",
        "/api/v1/agents/00000000-0000-0000-0000-000000000000/publish",
        {},
        {"tenant_admin", "superadmin"},
    ),
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
    (
        "PUT",
        "/api/v1/tenants/timezone",
        {"timezone": "America/Mexico_City"},
        {"tenant_admin", "superadmin"},
    ),
    (
        "PUT",
        "/api/v1/tenants/pipeline",
        {"definition": {"stages": []}},
        {"tenant_admin", "superadmin"},
    ),
    (
        "PUT",
        "/api/v1/tenants/runner-rules",
        {"runner_rules": []},
        {"tenant_admin", "superadmin"},
    ),
    (
        "PUT",
        "/api/v1/tenants/qos-config",
        {"enabled": False},
        {"tenant_admin", "superadmin"},
    ),
    (
        "PUT",
        "/api/v1/tenants/inbox-config",
        {"inbox_config": {}},
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
