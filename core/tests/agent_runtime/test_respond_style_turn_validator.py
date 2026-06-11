from __future__ import annotations

from pathlib import Path

from atendia.agent_runtime import (
    AgentContextPackage,
    LLMActionProposal,
    LLMAgentTurnOutput,
    LLMClaim,
    LLMFieldUpdateProposal,
    LLMHandoffProposal,
    LLMWorkflowEventProposal,
    RespondStyleTurnValidator,
    RespondStyleTurnValidatorConfig,
)


def test_validator_allows_valid_turn() -> None:
    decision = RespondStyleTurnValidator().validate(
        output=LLMAgentTurnOutput(
            final_message="Yes, the appointment is available.",
            claims=[
                LLMClaim(
                    text="The appointment is available.",
                    basis="knowledge_source",
                    source_refs=["kb-appointments"],
                )
            ],
            confidence=0.8,
        ),
        context=AgentContextPackage(
            knowledge_bindings=[{"source_id": "kb-appointments"}],
        ),
    )

    assert decision.send_decision == "send"
    assert decision.validation is not None
    assert decision.validation.status == "valid"


def test_validator_blocks_empty_final_message() -> None:
    output = LLMAgentTurnOutput.model_construct(final_message="", confidence=0.5)

    decision = RespondStyleTurnValidator().validate(
        output=output,
        context=AgentContextPackage(),
        attempt_number=2,
    )

    assert decision.send_decision == "no_send"
    assert decision.validation is not None
    assert decision.validation.status == "blocked"
    assert "final_message_empty" in decision.validation.blocked_reason


def test_validator_blocks_internal_leaks() -> None:
    decision = RespondStyleTurnValidator().validate(
        output=LLMAgentTurnOutput(
            final_message="I checked the internal trace and workflow.",
            confidence=0.7,
        ),
        context=AgentContextPackage(),
    )

    assert decision.retry_instruction is not None
    assert decision.validation is not None
    assert decision.validation.blocked_items[0].code == "internal_text_visible"


def test_validator_requires_claim_basis() -> None:
    decision = RespondStyleTurnValidator().validate(
        output=LLMAgentTurnOutput(
            final_message="Your file is approved.",
            claims=[
                LLMClaim(
                    text="Your file is approved.",
                    basis="tool_result",
                    source_refs=["approval.check"],
                )
            ],
            confidence=0.8,
        ),
        context=AgentContextPackage(tool_results=[]),
    )

    assert decision.retry_instruction is not None
    assert _codes(decision) == {"claim_source_ref_not_available"}


def test_validator_requires_quote_tool_for_price() -> None:
    decision = RespondStyleTurnValidator().validate(
        output=LLMAgentTurnOutput(
            final_message="The price is $10,000.",
            confidence=0.8,
        ),
        context=AgentContextPackage(tool_results=[]),
    )

    assert decision.retry_instruction is not None
    assert "missing_quote_tool" in _codes(decision)

    allowed = RespondStyleTurnValidator().validate(
        output=LLMAgentTurnOutput(
            final_message="The price is $10,000.",
            claims=[
                LLMClaim(
                    text="The price is $10,000.",
                    basis="tool_result",
                    source_refs=["quote.resolve"],
                )
            ],
            confidence=0.8,
        ),
        context=AgentContextPackage(
            tool_results=[{"tool_name": "quote.resolve", "status": "succeeded"}],
        ),
    )
    assert allowed.send_decision == "send"


def test_validator_requires_requirements_tool_for_requirements() -> None:
    decision = RespondStyleTurnValidator().validate(
        output=LLMAgentTurnOutput(
            final_message="The requirements are ID and proof of address.",
            confidence=0.8,
        ),
        context=AgentContextPackage(),
    )

    assert decision.retry_instruction is not None
    assert "missing_requirements_tool" in _codes(decision)


def test_validator_requires_field_policy_and_evidence() -> None:
    output = LLMAgentTurnOutput(
        final_message="I saved the service preference.",
        field_write_proposals=[
            LLMFieldUpdateProposal(
                field_key="preferred_service",
                value="repair",
                evidence=["I need a repair."],
                confidence=0.9,
                reason="Customer stated the service.",
            )
        ],
        confidence=0.8,
    )

    no_policy = RespondStyleTurnValidator().validate(
        output=output,
        context=AgentContextPackage(field_policies=[]),
    )
    # Field-proposal problems never block the visible message: the write is
    # DROPPED and recorded, the message delivers.
    assert no_policy.send_decision == "send"
    assert no_policy.accepted_field_writes == []
    dropped = no_policy.trace_metadata["respond_style_validator"][
        "dropped_field_writes"
    ]
    assert dropped[0]["code"] == "field_policy_missing"

    allowed = RespondStyleTurnValidator().validate(
        output=output,
        context=AgentContextPackage(
            field_policies=[{"field_key": "preferred_service", "writable": True}],
        ),
    )
    assert allowed.send_decision == "send"
    assert len(allowed.accepted_field_writes) == 1


def test_validator_requires_workflow_binding() -> None:
    output = LLMAgentTurnOutput(
        final_message="I will notify the team.",
        workflow_event_proposals=[
            LLMWorkflowEventProposal(
                binding_name="lead_review",
                event_name="lead.ready_for_review",
                reason="Customer requested review.",
            )
        ],
        confidence=0.8,
    )

    blocked = RespondStyleTurnValidator().validate(
        output=output,
        context=AgentContextPackage(workflow_trigger_schemas=[]),
    )
    assert "workflow_binding_missing" in _codes(blocked)

    allowed = RespondStyleTurnValidator().validate(
        output=output,
        context=AgentContextPackage(
            workflow_trigger_schemas=[{"binding_name": "lead_review", "enabled": True}],
        ),
    )
    assert allowed.send_decision == "send"


def test_validator_requires_action_permission() -> None:
    output = LLMAgentTurnOutput(
        final_message="I will create the task.",
        action_proposals=[
            LLMActionProposal(
                action_name="task.create",
                reason="Customer needs follow-up.",
            )
        ],
        confidence=0.8,
    )

    blocked = RespondStyleTurnValidator().validate(
        output=output,
        context=AgentContextPackage(action_schemas=[]),
    )
    assert "action_not_allowed" in _codes(blocked)

    allowed = RespondStyleTurnValidator().validate(
        output=output,
        context=AgentContextPackage(
            action_schemas=[{"name": "task.create", "enabled": True, "permitted": True}],
        ),
    )
    assert allowed.send_decision == "send"


def test_validator_validates_handoff_target() -> None:
    output = LLMAgentTurnOutput(
        final_message="I will pass this to the specialist team.",
        handoff_proposal=LLMHandoffProposal(
            needed=True,
            reason="Specialist review is required.",
            target="specialist",
        ),
        confidence=0.8,
    )

    blocked = RespondStyleTurnValidator().validate(
        output=output,
        context=AgentContextPackage(handoff_policy={"enabled": True, "targets": ["sales"]}),
    )
    assert "handoff_target_not_allowed" in _codes(blocked)

    allowed = RespondStyleTurnValidator().validate(
        output=output,
        context=AgentContextPackage(
            handoff_policy={"enabled": True, "targets": ["specialist"]},
        ),
    )
    assert allowed.send_decision == "send"


def test_validator_returns_no_send_when_retries_exhausted() -> None:
    decision = RespondStyleTurnValidator(
        RespondStyleTurnValidatorConfig(max_retry_attempts=1)
    ).validate(
        output=LLMAgentTurnOutput(
            final_message="The price is $10,000.",
            confidence=0.8,
        ),
        context=AgentContextPackage(),
        attempt_number=1,
    )

    assert decision.retry_instruction is None
    assert decision.send_decision == "no_send"
    assert decision.validation is not None
    assert decision.validation.status == "blocked"


def test_validator_has_no_tenant_or_vertical_hardcode() -> None:
    source = Path(
        "core/atendia/agent_runtime/respond_style_turn_validator.py"
    ).read_text(encoding="utf-8")
    lowered = source.casefold()

    forbidden_terms = [
        "dinamo",
        "motos",
        "credito",
        "credit dealership",
        "sat",
        "metro",
        "barber",
        "dentist",
    ]

    assert not any(term in lowered for term in forbidden_terms)


def _codes(decision) -> set[str]:
    assert decision.validation is not None
    return {item.code for item in decision.validation.blocked_items}



def test_validator_does_not_fact_gate_tool_request_turns() -> None:
    from atendia.agent_runtime import LLMToolCallProposal

    decision = RespondStyleTurnValidator().validate(
        output=LLMAgentTurnOutput(
            turn_kind="tool_request",
            final_message=None,
            tool_requests=[
                LLMToolCallProposal(
                    tool_name="requirements.lookup",
                    reason="Customer asked which documents are required.",
                )
            ],
            confidence=0.8,
        ),
        context=AgentContextPackage(
            tool_schemas=[{"tool_name": "requirements.lookup", "enabled": True}],
        ),
    )

    assert decision.validation is not None
    assert decision.validation.status == "valid"
    assert decision.send_decision == "no_send"
    assert len(decision.validation.accepted_tool_requests) == 1


def test_validator_blocks_unbound_tool_in_tool_request_turn() -> None:
    from atendia.agent_runtime import LLMToolCallProposal

    decision = RespondStyleTurnValidator().validate(
        output=LLMAgentTurnOutput(
            turn_kind="tool_request",
            final_message=None,
            tool_requests=[
                LLMToolCallProposal(
                    tool_name="requirements.lookup",
                    reason="Customer asked which documents are required.",
                )
            ],
            confidence=0.8,
        ),
        context=AgentContextPackage(
            tool_schemas=[{"tool_name": "quote.resolve", "enabled": True}],
        ),
    )

    assert "tool_not_bound" in _codes(decision)


def test_validator_catches_spanish_price_phrasing() -> None:
    decision = RespondStyleTurnValidator().validate(
        output=LLMAgentTurnOutput(
            final_message="Te sale en 85 mil pesos a la semana.",
            confidence=0.8,
        ),
        context=AgentContextPackage(),
    )

    assert "missing_quote_tool" in _codes(decision)


def test_validator_catches_spanish_requirements_word() -> None:
    decision = RespondStyleTurnValidator().validate(
        output=LLMAgentTurnOutput(
            final_message="Los requisitos son identificacion y comprobante de domicilio.",
            confidence=0.8,
        ),
        context=AgentContextPackage(),
    )

    assert "missing_requirements_tool" in _codes(decision)


def test_validator_allows_price_supported_by_knowledge_source_claim() -> None:
    decision = RespondStyleTurnValidator().validate(
        output=LLMAgentTurnOutput(
            final_message="La limpieza dental cuesta 800 pesos.",
            claims=[
                LLMClaim(
                    text="La limpieza dental cuesta 800 pesos.",
                    basis="knowledge_source",
                    source_refs=["kb-price-list"],
                )
            ],
            confidence=0.8,
        ),
        context=AgentContextPackage(
            knowledge_bindings=[{"source_id": "kb-price-list"}],
        ),
    )

    assert decision.send_decision == "send"


def test_validator_allows_benign_document_mention() -> None:
    decision = RespondStyleTurnValidator().validate(
        output=LLMAgentTurnOutput(
            final_message="Recibi tus documentos, gracias. En cuanto los revisemos te confirmo.",
            confidence=0.8,
        ),
        context=AgentContextPackage(),
    )

    assert decision.send_decision == "send"


def test_tenant_hard_policies_replace_defaults() -> None:
    context = AgentContextPackage(
        hard_policies=[
            {
                "policy_id": "warranty_support",
                "description": "warranty claims require the warranty tool",
                "trigger_patterns": [r"\bgarant[ií]a\b"],
                "requires_any": ["tool:warranty.lookup"],
            }
        ],
    )

    blocked = RespondStyleTurnValidator().validate(
        output=LLMAgentTurnOutput(
            final_message="La garantia cubre un anio completo.",
            confidence=0.8,
        ),
        context=context,
    )
    assert "hard_policy_unsupported:warranty_support" in _codes(blocked)

    # Defaults no longer apply when tenant policies are present:
    price_ok = RespondStyleTurnValidator().validate(
        output=LLMAgentTurnOutput(
            final_message="El costo es de 500 pesos.",
            confidence=0.8,
        ),
        context=context,
    )
    assert price_ok.send_decision == "send"


def test_malformed_tenant_hard_policy_fails_closed() -> None:
    decision = RespondStyleTurnValidator().validate(
        output=LLMAgentTurnOutput(
            final_message="Hola, claro que te ayudo.",
            confidence=0.8,
        ),
        context=AgentContextPackage(
            hard_policies=[{"policy_id": "broken", "trigger_patterns": "not-a-list"}],
        ),
    )

    assert decision.send_decision == "no_send"
    assert decision.validation is not None
    assert decision.validation.status == "blocked"
    assert "hard_policy_malformed" in _codes(decision)
