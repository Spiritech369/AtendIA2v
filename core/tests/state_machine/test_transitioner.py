import pytest

from atendia.contracts.nlu_result import Intent, NLUResult, Sentiment
from atendia.contracts.pipeline_definition import (
    PipelineDefinition,
    StageDefinition,
    Transition,
)
from atendia.state_machine.transitioner import next_stage


@pytest.fixture
def pipeline():
    return PipelineDefinition(
        version=1,
        stages=[
            StageDefinition(
                id="greeting",
                actions_allowed=["greet"],
                transitions=[Transition(to="qualify", when="intent in [ask_info, ask_price]")],
            ),
            StageDefinition(
                id="qualify",
                required_fields=["interes_producto", "ciudad"],
                actions_allowed=["ask_field"],
                transitions=[
                    Transition(
                        to="quote", when="all_required_fields_present AND intent == ask_price"
                    ),
                    Transition(to="escalate", when="sentiment == negative AND turn_count > 3"),
                ],
            ),
            StageDefinition(id="quote", actions_allowed=["quote"], transitions=[]),
            StageDefinition(id="escalate", actions_allowed=[], transitions=[]),
        ],
        tone={},
        fallback="escalate_to_human",
    )


def test_no_transition_when_no_condition_met(pipeline):
    nlu = NLUResult(
        intent=Intent.GREETING,
        entities={},
        sentiment=Sentiment.NEUTRAL,
        confidence=0.9,
        ambiguities=[],
    )
    assert next_stage(pipeline, "greeting", nlu, extracted_data={}, turn_count=0) == "greeting"


def test_transition_greeting_to_qualify(pipeline):
    nlu = NLUResult(
        intent=Intent.ASK_INFO,
        entities={},
        sentiment=Sentiment.NEUTRAL,
        confidence=0.9,
        ambiguities=[],
    )
    assert next_stage(pipeline, "greeting", nlu, extracted_data={}, turn_count=1) == "qualify"


def test_transition_qualify_to_quote_when_fields_complete(pipeline):
    nlu = NLUResult(
        intent=Intent.ASK_PRICE,
        entities={},
        sentiment=Sentiment.NEUTRAL,
        confidence=0.9,
        ambiguities=[],
    )
    extracted = {"interes_producto": "150Z", "ciudad": "CDMX"}
    assert next_stage(pipeline, "qualify", nlu, extracted_data=extracted, turn_count=2) == "quote"


def test_no_transition_qualify_when_fields_incomplete(pipeline):
    nlu = NLUResult(
        intent=Intent.ASK_PRICE,
        entities={},
        sentiment=Sentiment.NEUTRAL,
        confidence=0.9,
        ambiguities=[],
    )
    assert (
        next_stage(pipeline, "qualify", nlu, extracted_data={"ciudad": "CDMX"}, turn_count=2)
        == "qualify"
    )


def test_transition_to_escalate_on_negative_sentiment(pipeline):
    nlu = NLUResult(
        intent=Intent.COMPLAIN,
        entities={},
        sentiment=Sentiment.NEGATIVE,
        confidence=0.8,
        ambiguities=[],
    )
    assert next_stage(pipeline, "qualify", nlu, extracted_data={}, turn_count=4) == "escalate"
