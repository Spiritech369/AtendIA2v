from atendia.contracts.nlu_result import NLUResult

AMBIGUITY_CONFIDENCE_THRESHOLD = 0.7


def is_ambiguous(nlu: NLUResult) -> bool:
    if nlu.confidence < AMBIGUITY_CONFIDENCE_THRESHOLD:
        return True
    if nlu.ambiguities:
        return True
    for field in nlu.entities.values():
        if field.confidence < AMBIGUITY_CONFIDENCE_THRESHOLD:
            return True
    return False
