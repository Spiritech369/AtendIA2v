from __future__ import annotations

import json
from pathlib import Path

from atendia.agent_runtime import (
    AdvisorBrainDecision,
    AdvisorBrainStateChange,
    DeterministicStateWriter,
    QuoteSnapshot,
    ToolExecutionResult,
)
from atendia.agent_runtime.canonical import CanonicalProductReference
from atendia.agent_runtime.schemas import (
    ConversationMemoryContext,
    TenantRuntimeConfigContext,
    TurnContext,
)
from atendia.agent_runtime.tenant_domain_contract import (
    apply_tenant_domain_contract,
    load_tenant_domain_contract,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "tenant_domain_contracts"


def _fixture(name: str) -> dict:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def _tenant_config(raw: dict) -> TenantRuntimeConfigContext:
    result = load_tenant_domain_contract(raw, tenant_id=raw["tenant_id"], agent_id=raw["agent_id"])
    return apply_tenant_domain_contract(TenantRuntimeConfigContext(), result)


def _context(
    raw: dict | None = None,
    *,
    inbound_text: str = "Me interesa ese dato",
    memory: ConversationMemoryContext | None = None,
    safe_mode: bool = False,
) -> TurnContext:
    if raw is None:
        config = TenantRuntimeConfigContext(safe_mode=safe_mode)
        tenant_id = "tenant-generic"
    else:
        config = _tenant_config(raw)
        if safe_mode:
            config = config.model_copy(update={"safe_mode": True})
        tenant_id = raw["tenant_id"]
    return TurnContext(
        tenant_id=tenant_id,
        conversation_id="conversation-1",
        inbound_text=inbound_text,
        tenant_config=config,
        memory=memory or ConversationMemoryContext(),
    )


def _decision(*changes: AdvisorBrainStateChange) -> AdvisorBrainDecision:
    return AdvisorBrainDecision(
        understanding="Cliente dio informacion.",
        customer_goal="advance",
        conversation_goals=["advance"],
        known_facts={},
        missing_facts=[],
        next_best_action="save_state",
        proposed_state_changes=list(changes),
        response_plan="Guardar solo datos validados.",
        confidence=0.9,
    )


def _change(
    key: str,
    value: object,
    *,
    evidence: list[str] | None = None,
    metadata: dict | None = None,
    confidence: float = 0.9,
) -> AdvisorBrainStateChange:
    return AdvisorBrainStateChange(
        target="contact_field",
        key=key,
        value=value,
        reason="Cliente lo dijo.",
        evidence=evidence or ["Me interesa ese dato"],
        confidence=confidence,
        metadata=metadata or {},
    )


def _tool(name: str, *, tenant_id: str, data: dict | None = None) -> ToolExecutionResult:
    return ToolExecutionResult(
        tool_name=name,
        status="succeeded",
        data={"tenant_id": tenant_id, **(data or {})},
    )


def _product_ref(product_id: str = "prod-r4") -> CanonicalProductReference:
    return CanonicalProductReference(
        product_id=product_id,
        sku="R4-250",
        display_name="R4 250 CC",
        catalog_id="catalog-1",
        catalog_version_id="v1",
        evidence=["catalog.search matched product"],
    )


def _quote_snapshot(product_id: str = "prod-r4") -> QuoteSnapshot:
    return QuoteSnapshot(
        snapshot_id=f"quote-{product_id}",
        tenant_id="tenant_dinamo_fixture",
        product=_product_ref(product_id),
        plan_code="cash",
        plan_name="Contado",
        pricing={"cash_price": 62000},
        quote_payload={"pricing": {"cash_price": 62000}},
        evidence=["quote.resolve returned quote"],
        source_tool="quote.resolve",
    ).with_integrity_hash()


def test_tool_only_rejects_model_write() -> None:
    context = _context(_fixture("vehicle_credit_sales.json"))

    result = DeterministicStateWriter().build_updates(
        context=context,
        decision=_decision(_change("quote_snapshot_id", "quote-1")),
        tool_results=[],
    )

    assert result.field_updates == []
    assert result.blocked[0]["field"] == "quote_snapshot_id"
    assert result.blocked[0]["reason"] == "field_is_tool_only"


def test_blocked_from_model_rejects_model_write() -> None:
    raw = _fixture("vehicle_credit_sales.json")
    raw["fields"].append(
        {
            "key": "approval_status",
            "domain_role": "eligibility",
            "write_policy": "blocked_from_model",
            "allowed_sources": ["human_review"],
            "evidence_required": True,
        }
    )
    context = _context(raw)

    result = DeterministicStateWriter().build_updates(
        context=context,
        decision=_decision(_change("approval_status", "approved")),
    )

    assert result.blocked[0]["reason"] == "field_is_blocked_from_model"


def test_attachment_required_rejects_without_attachment_or_human_evidence() -> None:
    raw = _fixture("vehicle_credit_sales.json")
    raw["fields"].append(
        {
            "key": "id_document_status",
            "domain_role": "document",
            "write_policy": "attachment_required",
            "allowed_sources": ["user_message", "document.check", "human_review"],
            "evidence_required": True,
        }
    )
    context = _context(raw)

    result = DeterministicStateWriter().build_updates(
        context=context,
        decision=_decision(_change("id_document_status", "received")),
    )

    assert result.blocked[0]["reason"] == "attachment_or_human_evidence_required"


def test_system_derived_rejects_model_write_and_accepts_required_tools() -> None:
    raw = _fixture("vehicle_credit_sales.json")
    context = _context(raw)
    writer = DeterministicStateWriter()

    blocked = writer.build_updates(
        context=context,
        decision=_decision(_change("requirements_complete", True)),
        tool_results=[],
    )
    assert blocked.blocked[0]["reason"] == "field_is_system_derived"

    accepted = writer.build_updates(
        context=context,
        decision=_decision(),
        tool_results=[
            _tool("requirements.lookup", tenant_id=raw["tenant_id"]),
            _tool(
                "document.check",
                tenant_id=raw["tenant_id"],
                data={
                    "field_updates": [
                        {
                            "key": "requirements_complete",
                            "value": True,
                            "reason": "All required documents validated.",
                            "evidence": ["document.check"],
                        }
                    ]
                },
            ),
        ],
    )

    values = {update.field_key: update.value for update in accepted.field_updates}
    assert values["requirements_complete"] is True
    assert accepted.accepted[0]["source"] == "document.check"


def test_auto_apply_when_explicit_accepts_user_evidence_without_bureau_status() -> None:
    raw = _fixture("vehicle_credit_sales.json")
    context = _context(raw, inbound_text="Estoy en buro")

    result = DeterministicStateWriter().build_updates(
        context=context,
        decision=_decision(
            _change(
                "BURO",
                True,
                evidence=["Estoy en buro"],
                metadata={"explicit": True},
            )
        ),
    )

    values = {update.field_key: update.value for update in result.field_updates}
    assert values["bureau_mentioned"] is True
    assert "bureau_status" not in values


def test_auto_apply_when_catalog_match_requires_catalog_evidence() -> None:
    raw = _fixture("vehicle_credit_sales.json")
    context = _context(raw)
    writer = DeterministicStateWriter()

    blocked = writer.build_updates(
        context=context,
        decision=_decision(_change("MOTO", "R4 250 CC")),
        tool_results=[],
    )
    assert blocked.blocked[0]["reason"] == "catalog_match_required"

    accepted = writer.build_updates(
        context=context,
        decision=_decision(_change("MOTO", "R4 250 CC")),
        tool_results=[_tool("catalog.search", tenant_id=raw["tenant_id"])],
    )
    values = {update.field_key: update.value for update in accepted.field_updates}
    assert values["product_selection"] == "R4 250 CC"


def test_auto_apply_when_valid_plan_requires_plan_evidence() -> None:
    raw = _fixture("vehicle_credit_sales.json")
    context = _context(raw)
    writer = DeterministicStateWriter()

    blocked = writer.build_updates(
        context=context,
        decision=_decision(_change("PLAN_CREDITO", "Semanal")),
        tool_results=[],
    )
    assert blocked.blocked[0]["reason"] == "valid_plan_evidence_required"

    accepted = writer.build_updates(
        context=context,
        decision=_decision(_change("PLAN_CREDITO", "Semanal")),
        tool_results=[_tool("credit_plan.resolve", tenant_id=raw["tenant_id"])],
    )
    values = {update.field_key: update.value for update in accepted.field_updates}
    assert values["plan_selection"] == "Semanal"


def test_suggest_review_does_not_write_definitive_value() -> None:
    raw = _fixture("appointment_services.json")
    context = _context(raw, inbound_text="Quiero cita manana a las 5")

    result = DeterministicStateWriter().build_updates(
        context=context,
        decision=_decision(_change("appointment_time", "manana 5pm")),
        tool_results=[],
    )

    assert result.field_updates == []
    assert result.needs_review[0]["field"] == "appointment_time"


def test_quote_fields_invalidate_when_selection_changes() -> None:
    raw = _fixture("vehicle_credit_sales.json")
    context = _context(
        raw,
        memory=ConversationMemoryContext(
            salient_facts={
                "product_selection": "Adventure 150",
                "quote_snapshot_id": "quote-old",
            }
        ),
    )

    result = DeterministicStateWriter().build_updates(
        context=context,
        decision=_decision(_change("product_selection", "R4 250 CC")),
        tool_results=[_tool("catalog.search", tenant_id=raw["tenant_id"])],
    )

    values = {update.field_key: update.value for update in result.field_updates}
    assert values["product_selection"] == "R4 250 CC"
    assert values["quote_snapshot_id"] is None
    assert result.invalidated_fields[0]["field"] == "quote_snapshot_id"


def test_quote_resolve_writes_declarative_quote_field() -> None:
    raw = _fixture("vehicle_credit_sales.json")
    context = _context(raw)

    result = DeterministicStateWriter().build_updates(
        context=context,
        decision=_decision(),
        tool_results=[
            ToolExecutionResult(
                tool_name="quote.resolve",
                status="succeeded",
                data={
                    "tenant_id": raw["tenant_id"],
                    "quote_snapshot": _quote_snapshot().model_dump(mode="json"),
                },
            )
        ],
    )

    values = {update.field_key: update.value for update in result.field_updates}
    assert values["quote_snapshot_id"] == "quote-prod-r4"


def test_appointment_tenant_does_not_use_vehicle_fields() -> None:
    raw = _fixture("appointment_services.json")
    context = _context(raw)

    result = DeterministicStateWriter().build_updates(
        context=context,
        decision=_decision(_change("MOTO", "R4 250 CC")),
        tool_results=[_tool("catalog.search", tenant_id=raw["tenant_id"])],
    )

    assert result.field_updates == []
    assert result.blocked[0]["field"] == "MOTO"


def test_safe_mode_blocks_field_writes() -> None:
    context = _context(safe_mode=True)

    result = DeterministicStateWriter().build_updates(
        context=context,
        decision=_decision(_change("email", "a@example.test")),
    )

    assert result.field_updates == []
    assert result.blocked[0]["reason"] == "safe_mode_blocks_field_write"


def test_tenant_isolation_blocks_cross_tenant_tool_evidence() -> None:
    raw = _fixture("vehicle_credit_sales.json")
    context = _context(raw)

    result = DeterministicStateWriter().build_updates(
        context=context,
        decision=_decision(_change("product_selection", "R4 250 CC")),
        tool_results=[_tool("catalog.search", tenant_id="tenant-a")],
    )

    assert result.field_updates == []
    assert result.blocked[0]["reason"] == "catalog_match_required"
