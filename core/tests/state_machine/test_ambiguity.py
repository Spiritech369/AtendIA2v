from atendia.contracts.conversation_state import ExtractedField
from atendia.contracts.nlu_result import Intent, NLUResult, Sentiment
from atendia.state_machine.ambiguity import is_ambiguous, AMBIGUITY_CONFIDENCE_THRESHOLD


def test_high_confidence_no_ambiguities_is_not_ambiguous():
    nlu = NLUResult(intent=Intent.ASK_PRICE, entities={},
                    sentiment=Sentiment.NEUTRAL, confidence=0.92, ambiguities=[])
    assert is_ambiguous(nlu) is False


def test_low_confidence_is_ambiguous():
    nlu = NLUResult(intent=Intent.ASK_PRICE, entities={},
                    sentiment=Sentiment.NEUTRAL,
                    confidence=AMBIGUITY_CONFIDENCE_THRESHOLD - 0.05,
                    ambiguities=[])
    assert is_ambiguous(nlu) is True


def test_explicit_ambiguity_is_ambiguous():
    nlu = NLUResult(intent=Intent.ASK_PRICE, entities={},
                    sentiment=Sentiment.NEUTRAL, confidence=0.95,
                    ambiguities=["could be 150Z or 250Z"])
    assert is_ambiguous(nlu) is True


def test_low_field_confidence_is_ambiguous():
    nlu = NLUResult(
        intent=Intent.ASK_PRICE,
        entities={"modelo": ExtractedField(value="?", confidence=0.4, source_turn=1)},
        sentiment=Sentiment.NEUTRAL,
        confidence=0.95,
        ambiguities=[],
    )
    assert is_ambiguous(nlu) is True
