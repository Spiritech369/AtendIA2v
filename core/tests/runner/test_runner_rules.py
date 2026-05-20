from atendia.contracts.nlu_result import Intent, NLUResult, Sentiment
from atendia.runner.runner_rules import RunnerRule, evaluate_runner_rules, normalize_runner_rules


def _nlu() -> NLUResult:
    return NLUResult(
        intent=Intent.ASK_INFO,
        topic="qualification",
        sub_intent=None,
        sales_signal="none",
        entities={},
        sentiment=Sentiment.NEUTRAL,
        confidence=0.8,
        ambiguities=[],
    )


def test_runner_rule_preserves_category_and_priority() -> None:
    rules = normalize_runner_rules(
        [
            {
                "name": "Menos de 6 meses",
                "category": "blocking",
                "priority": 10,
                "enabled": True,
                "when": {"field": "tiempo_empleo_meses", "operator": "less_than", "value": 6},
                "then": {"set_action": "stop_not_qualified"},
            }
        ]
    )

    assert rules[0]["category"] == "blocking"
    assert rules[0]["priority"] == 10


def test_runner_rules_execute_lower_priority_number_first() -> None:
    result = evaluate_runner_rules(
        rules=[
            RunnerRule(
                name="Regla baja",
                priority=90,
                when={"field": "topic", "operator": "equals", "value": "qualification"},
                then={"set_action": "quote"},
            ),
            RunnerRule(
                name="Regla alta",
                priority=10,
                when={"field": "topic", "operator": "equals", "value": "qualification"},
                then={"set_action": "stop_not_qualified"},
            ),
        ],
        nlu=_nlu(),
        extracted_before={},
        extracted_after={},
        current_stage="nuevo",
        inbound_text="hola",
    )

    assert result.matched_rules == ["Regla alta", "Regla baja"]
    assert result.set_action == "quote"
