"""Verify the KB command center returns empty shapes (not hardcoded
demo lists) for non-demo tenants.

Prior to this fix, /health, /risks, /items, /unanswered-questions,
/funnel-coverage, /dashboard-cards, /conflicts, /audit-logs and
/simulate all returned a hardcoded demo payload regardless of tenant.
Plus /simulate raised 501 for non-demo.
"""
from __future__ import annotations


def test_health_non_demo_returns_empty_state(client_operator):
    resp = client_operator.get("/api/v1/knowledge/health")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["overall_score"] == 0
    assert body["label"] == "Sin contenido"
    assert body["metrics"] == []


def test_health_history_non_demo_empty(client_operator):
    resp = client_operator.get("/api/v1/knowledge/health/history")
    assert resp.status_code == 200
    assert resp.json() == []


def test_risks_non_demo_empty(client_operator):
    resp = client_operator.get("/api/v1/knowledge/risks")
    assert resp.status_code == 200
    assert resp.json()["items"] == []


def test_items_non_demo_returns_summary_from_db(client_operator):
    """Empty tenant: 0 FAQs/catalog/docs → 0 summary items."""
    resp = client_operator.get("/api/v1/knowledge/items")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["items"] == []
    assert body["total"] == 0


def test_unanswered_non_demo_empty(client_operator):
    resp = client_operator.get("/api/v1/knowledge/unanswered-questions")
    assert resp.status_code == 200
    assert resp.json()["items"] == []


def test_funnel_coverage_non_demo_empty(client_operator):
    resp = client_operator.get("/api/v1/knowledge/funnel-coverage")
    assert resp.status_code == 200
    assert resp.json()["stages"] == []


def test_dashboard_cards_non_demo_empty(client_operator):
    resp = client_operator.get("/api/v1/knowledge/dashboard-cards")
    assert resp.status_code == 200
    assert resp.json()["items"] == []


def test_conflicts_non_demo_empty(client_operator):
    resp = client_operator.get("/api/v1/knowledge/conflicts")
    assert resp.status_code == 200
    assert resp.json()["items"] == []


def test_audit_logs_non_demo_empty(client_operator):
    resp = client_operator.get("/api/v1/knowledge/audit-logs")
    assert resp.status_code == 200
    assert resp.json()["items"] == []


def test_simulate_non_demo_returns_stub_not_501(client_operator):
    """Critical: this used to raise 501 for non-demo, blocking the
    UI entirely. Now returns a no-answer shape so the cockpit works."""
    resp = client_operator.post(
        "/api/v1/knowledge/simulate",
        json={"message": "¿cuánto cuesta?", "agent": "sales", "model": "gpt-4o-mini"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["mode"] == "sources_only"
    assert body["retrieved_chunks"] == []
    assert "Carga FAQs" in body["answer"]
