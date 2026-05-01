from atendia.contracts.nlu_result import Intent
from atendia.contracts.pipeline_definition import StageDefinition


class NoActionAvailableError(Exception):
    """No action in `actions_allowed` matches the intent and there is no fallback action."""


_INTENT_TO_PREFERRED_ACTIONS: dict[Intent, list[str]] = {
    Intent.GREETING: ["greet", "ask_field"],
    Intent.ASK_INFO: ["ask_field", "lookup_faq", "search_catalog"],
    Intent.ASK_PRICE: ["quote", "search_catalog", "ask_field"],
    Intent.BUY: ["close", "quote", "book_appointment"],
    Intent.SCHEDULE: ["book_appointment", "ask_field"],
    Intent.COMPLAIN: ["escalate_to_human", "lookup_faq"],
    Intent.OFF_TOPIC: ["lookup_faq", "ask_field"],
    Intent.UNCLEAR: ["ask_clarification", "lookup_faq"],
}


def resolve_action(stage: StageDefinition, intent: Intent) -> str:
    preferred = _INTENT_TO_PREFERRED_ACTIONS.get(intent, [])
    allowed = set(stage.actions_allowed)
    for candidate in preferred:
        if candidate in allowed:
            return candidate
    raise NoActionAvailableError(
        f"no action in {sorted(allowed)} matches intent {intent.value}"
    )
