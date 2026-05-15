"""Smoke test that every KB model is wired into atendia.db.models and
exposes the columns Phase 1 migrations 031-036 created."""

from __future__ import annotations


def test_kb_models_importable() -> None:
    from atendia.db.models import (
        KbAgentPermission,
        KbCollection,
        KbConflict,
        KbHealthSnapshot,
        KbSafeAnswerSetting,
        KbSourcePriorityRule,
        KbTestCase,
        KbTestRun,
        KbUnansweredQuestion,
        KbVersion,
        KnowledgeChunk,
        KnowledgeDocument,
        TenantCatalogItem,
        TenantFAQ,
    )

    # New columns on extended tables (032).
    for attr in (
        "status",
        "visibility",
        "priority",
        "expires_at",
        "agent_permissions",
        "collection_id",
        "language",
        "updated_at",
    ):
        assert hasattr(TenantFAQ, attr), f"TenantFAQ missing {attr}"
        assert hasattr(TenantCatalogItem, attr), f"TenantCatalogItem missing {attr}"

    for attr in (
        "visibility",
        "priority",
        "expires_at",
        "agent_permissions",
        "collection_id",
        "language",
        "progress_percentage",
        "embedded_chunk_count",
        "error_count",
    ):
        assert hasattr(KnowledgeDocument, attr), f"KnowledgeDocument missing {attr}"

    for attr in (
        "chunk_status",
        "marked_critical",
        "error_message",
        "token_count",
        "page",
        "heading",
        "section",
        "last_retrieved_at",
        "retrieval_count",
        "average_score",
    ):
        assert hasattr(KnowledgeChunk, attr), f"KnowledgeChunk missing {attr}"

    # Catalog-specific (032).
    for attr in ("price_cents", "stock_status", "region", "branch", "payment_plans"):
        assert hasattr(TenantCatalogItem, attr), f"TenantCatalogItem missing {attr}"

    # New tables — sanity-check tablename + a couple of columns each.
    assert KbCollection.__tablename__ == "kb_collections"
    assert hasattr(KbCollection, "slug")

    assert KbVersion.__tablename__ == "kb_versions"
    assert hasattr(KbVersion, "diff_json")

    assert KbConflict.__tablename__ == "kb_conflicts"
    assert hasattr(KbConflict, "detection_type")

    assert KbUnansweredQuestion.__tablename__ == "kb_unanswered_questions"
    assert hasattr(KbUnansweredQuestion, "failed_chunks")

    assert KbTestCase.__tablename__ == "kb_test_cases"
    assert hasattr(KbTestCase, "expected_keywords")

    assert KbTestRun.__tablename__ == "kb_test_runs"
    assert hasattr(KbTestRun, "diff_vs_expected")

    assert KbHealthSnapshot.__tablename__ == "kb_health_snapshots"
    assert hasattr(KbHealthSnapshot, "score_components")

    assert KbAgentPermission.__tablename__ == "kb_agent_permissions"
    assert hasattr(KbAgentPermission, "allowed_source_types")

    assert KbSourcePriorityRule.__tablename__ == "kb_source_priority_rules"
    assert hasattr(KbSourcePriorityRule, "allow_synthesis")

    assert KbSafeAnswerSetting.__tablename__ == "kb_safe_answer_settings"
    assert hasattr(KbSafeAnswerSetting, "default_fallback_message")
