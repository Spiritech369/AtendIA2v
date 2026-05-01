from datetime import datetime, timezone
from decimal import Decimal

from atendia.contracts.conversation_state import ConversationState, ExtractedField


def test_conversation_state_minimal_valid():
    s = ConversationState(
        conversation_id="01J3Z6V8N1Q4WZS5MXY9KQHF7D",
        tenant_id="dinamomotos",
        current_stage="qualify",
        extracted_data={
            "nombre": ExtractedField(value="Juan", confidence=0.95, source_turn=2),
        },
        last_intent="ask_info",
        stage_entered_at=datetime.now(timezone.utc),
        followups_sent_count=0,
        total_cost_usd=Decimal("0.0000"),
    )
    assert s.current_stage == "qualify"
    assert s.extracted_data["nombre"].value == "Juan"


def test_extracted_field_low_confidence():
    f = ExtractedField(value="quizá CDMX", confidence=0.4, source_turn=3)
    assert f.confidence < 0.7
