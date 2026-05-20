from atendia.runner.nlu_prompts import build_prompt


def test_build_prompt_includes_configured_topics_and_sub_intents():
    messages = build_prompt(
        text="Aceptan buro malo?",
        current_stage="nuevo_lead",
        required_fields=[],
        optional_fields=[],
        history=[],
        topics=[
            {
                "key": "bureau",
                "label": "Buro de credito",
                "description": "Preguntas sobre deudas o historial crediticio",
                "examples": ["aceptan buro malo"],
                "sub_intents": [
                    {
                        "key": "ask_bad_credit_allowed",
                        "label": "Pregunta si aceptan buro malo",
                    }
                ],
            }
        ],
    )

    system = messages[0]["content"]
    assert "bureau" in system
    assert "ask_bad_credit_allowed" in system
    assert "sales_signal" in system
    assert "Si ningun" in system
