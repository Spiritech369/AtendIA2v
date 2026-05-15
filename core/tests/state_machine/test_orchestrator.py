from datetime import datetime, timezone

import pytest

from atendia.contracts.conversation_state import ConversationState, ExtractedField
from atendia.contracts.nlu_result import Intent, NLUResult, Sentiment
from atendia.contracts.pipeline_definition import (
    PipelineDefinition,
    StageDefinition,
    Transition,
)
from atendia.state_machine.orchestrator import process_turn


@pytest.fixture
def pipeline():
    return PipelineDefinition(
        version=1,
        stages=[
            StageDefinition(
                id="qualify",
                required_fields=["interes_producto", "ciudad"],
                actions_allowed=["ask_field", "lookup_faq", "ask_clarification"],
                transitions=[
                    Transition(
                        to="quote", when="all_required_fields_present AND intent == ask_price"
                    ),
                ],
            ),
            StageDefinition(
                id="quote",
                actions_allowed=["quote", "ask_clarification"],
                transitions=[],
            ),
        ],
        tone={},
        fallback="escalate_to_human",
    )


@pytest.fixture
def state_qualify():
    return ConversationState(
        conversation_id="c1",
        tenant_id="t1",
        current_stage="qualify",
        extracted_data={},
        stage_entered_at=datetime.now(timezone.utc),
    )


def test_ambiguous_nlu_forces_ask_clarification(pipeline, state_qualify):
    nlu = NLUResult(
        intent=Intent.ASK_PRICE,
        entities={},
        sentiment=Sentiment.NEUTRAL,
        confidence=0.5,
        ambiguities=[],
    )
    decision = process_turn(pipeline, state_qualify, nlu, turn_count=2)
    assert decision.action == "ask_clarification"
    assert decision.next_stage == "qualify"


def test_normal_flow_picks_action_and_transitions(pipeline):
    state = ConversationState(
        conversation_id="c2",
        tenant_id="t1",
        current_stage="qualify",
        extracted_data={
            "interes_producto": ExtractedField(value="150Z", confidence=0.95, source_turn=1),
            "ciudad": ExtractedField(value="CDMX", confidence=0.95, source_turn=1),
        },
        stage_entered_at=datetime.now(timezone.utc),
    )
    nlu = NLUResult(
        intent=Intent.ASK_PRICE,
        entities={},
        sentiment=Sentiment.NEUTRAL,
        confidence=0.9,
        ambiguities=[],
    )
    decision = process_turn(pipeline, state, nlu, turn_count=2)
    assert decision.next_stage == "quote"
    # action_resolver should pick from the NEXT stage's allowed actions
    assert decision.action == "quote"
