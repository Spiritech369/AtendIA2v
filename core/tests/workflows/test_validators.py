"""Workflow definition validators.

Sync structural checks live in ``validate_definition``; dynamic ref checks
(agent_id/stage_id/user_id refs against the tenant) live in
``validate_references`` and run on toggle/save when ``active=true``.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from atendia.workflows.engine import (
    WorkflowValidationError,
    definition_for_steps,
    validate_definition,
    validate_references,
)


def test_empty_definition_is_valid() -> None:
    validate_definition({"nodes": [], "edges": []})


def test_definition_must_be_dict() -> None:
    with pytest.raises(WorkflowValidationError):
        validate_definition([])  # type: ignore[arg-type]


def test_unknown_node_type_rejected() -> None:
    with pytest.raises(WorkflowValidationError, match="unknown node type"):
        validate_definition(
            {
                "nodes": [{"id": "a", "type": "nope"}],
                "edges": [],
            }
        )


def test_duplicate_node_ids_rejected() -> None:
    with pytest.raises(WorkflowValidationError, match="duplicate"):
        validate_definition(
            {
                "nodes": [
                    {"id": "a", "type": "trigger"},
                    {"id": "a", "type": "message"},
                ],
                "edges": [],
            }
        )


def test_delay_over_30_days_rejected() -> None:
    with pytest.raises(WorkflowValidationError, match="30 days"):
        validate_definition(
            {
                "nodes": [{"id": "d", "type": "delay", "config": {"seconds": 60 * 60 * 24 * 31}}],
                "edges": [],
            }
        )


def test_delay_must_be_positive() -> None:
    with pytest.raises(WorkflowValidationError, match="positive"):
        validate_definition(
            {
                "nodes": [{"id": "d", "type": "delay", "config": {"seconds": 0}}],
                "edges": [],
            }
        )


def test_condition_requires_both_branches() -> None:
    bad = {
        "nodes": [
            {"id": "c", "type": "condition", "config": {"field": "extracted.x"}},
            {"id": "a", "type": "pause_bot"},
        ],
        "edges": [{"from": "c", "to": "a", "label": "true"}],
    }
    with pytest.raises(WorkflowValidationError, match="needs both 'true' and 'false'"):
        validate_definition(bad)


def test_condition_namespace_must_be_allowlisted() -> None:
    bad = {
        "nodes": [
            {"id": "c", "type": "condition", "config": {"field": "secrets.api_key"}},
        ],
        "edges": [],
    }
    with pytest.raises(WorkflowValidationError, match="namespace"):
        validate_definition(bad)


def test_condition_conversation_field_must_be_in_allowlist() -> None:
    bad = {
        "nodes": [
            {"id": "c", "type": "condition", "config": {"field": "conversation.deleted_at"}},
        ],
        "edges": [],
    }
    with pytest.raises(WorkflowValidationError, match="not in the allowlist"):
        validate_definition(bad)


def test_cycle_without_delay_rejected() -> None:
    bad = {
        "nodes": [
            {"id": "trigger_1", "type": "trigger"},
            {"id": "a", "type": "pause_bot"},
            {"id": "b", "type": "pause_bot"},
        ],
        "edges": [
            {"from": "trigger_1", "to": "a"},
            {"from": "a", "to": "b"},
            {"from": "b", "to": "a"},
        ],
    }
    with pytest.raises(WorkflowValidationError, match="cycle"):
        validate_definition(bad)


def test_cycle_through_delay_allowed() -> None:
    good = {
        "nodes": [
            {"id": "trigger_1", "type": "trigger"},
            {"id": "m", "type": "message", "config": {"text": "hola"}},
            {"id": "d", "type": "delay", "config": {"seconds": 60}},
        ],
        "edges": [
            {"from": "trigger_1", "to": "m"},
            {"from": "m", "to": "d"},
            {"from": "d", "to": "m"},
        ],
    }
    validate_definition(good)  # MAX_STEPS caps the runtime; structure is fine.


def test_definition_for_steps_helper_round_trips() -> None:
    d = definition_for_steps(
        "message_received",
        [{"type": "pause_bot"}, {"type": "message", "config": {"text": "hi"}}],
    )
    validate_definition(d)
    assert d["nodes"][0]["type"] == "trigger"
    assert d["nodes"][-1]["type"] == "message"


@pytest.mark.asyncio
async def test_validate_references_rejects_unknown_agent(
    db_session,
    seed_tenant_factory,
) -> None:
    seed = await seed_tenant_factory()
    bad_agent = uuid4()
    definition = definition_for_steps(
        "message_received",
        [{"type": "assign_agent", "config": {"agent_id": str(bad_agent)}}],
    )
    with pytest.raises(WorkflowValidationError, match="agent_id refs not found"):
        await validate_references(db_session, definition, UUID(seed["tenant_id"]))


@pytest.mark.asyncio
async def test_validate_references_accepts_in_tenant_agent(
    db_session,
    seed_tenant_factory,
) -> None:
    seed = await seed_tenant_factory(agent_count=1)
    definition = definition_for_steps(
        "message_received",
        [{"type": "assign_agent", "config": {"agent_id": seed["agent_ids"][0]}}],
    )
    await validate_references(db_session, definition, UUID(seed["tenant_id"]))


@pytest.mark.asyncio
async def test_validate_references_rejects_cross_tenant_user(
    db_session,
    seed_tenant_factory,
) -> None:
    a = await seed_tenant_factory(user_role="operator")
    b = await seed_tenant_factory()  # other tenant — no users
    definition = definition_for_steps(
        "message_received",
        [{"type": "notify_agent", "config": {"user_id": a["user_id"]}}],
    )
    # A user_id that exists in tenant A is "not found" from tenant B's view.
    with pytest.raises(WorkflowValidationError, match="user_id refs"):
        await validate_references(db_session, definition, UUID(b["tenant_id"]))


@pytest.mark.asyncio
async def test_validate_references_rejects_unknown_stage(
    db_session,
    seed_tenant_factory,
) -> None:
    seed = await seed_tenant_factory(pipeline_stages=["lead", "won"])
    definition = definition_for_steps(
        "message_received",
        [{"type": "move_stage", "config": {"stage_id": "ghost"}}],
    )
    with pytest.raises(WorkflowValidationError, match="unknown stages"):
        await validate_references(db_session, definition, UUID(seed["tenant_id"]))


@pytest.mark.asyncio
async def test_validate_references_skips_unknown_role(
    db_session,
    seed_tenant_factory,
) -> None:
    seed = await seed_tenant_factory()
    definition = definition_for_steps(
        "message_received",
        [{"type": "notify_agent", "config": {"role": "nope"}}],
    )
    with pytest.raises(WorkflowValidationError, match="unknown notify_agent role"):
        await validate_references(db_session, definition, UUID(seed["tenant_id"]))
