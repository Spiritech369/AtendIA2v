from __future__ import annotations

from collections.abc import Mapping
from difflib import SequenceMatcher
from typing import Any

from atendia.operational_intent.complaint_policy import (
    ComplaintPolicyResult,
    classify_complaint_policy,
)
from atendia.operational_intent.policy_config import OperationalCategoryPolicy, PolicyConfig
from atendia.operational_intent.risk_policy import OperationalEffects, OperationalIntentResult
from atendia.text_normalization import normalize_whatsapp_text


def classify_operational_intent(
    *,
    text: str,
    policy_config: PolicyConfig | None,
    current_stage: str | None = None,
    state: Mapping[str, Any] | None = None,
) -> OperationalIntentResult:
    if policy_config is None:
        return _unknown()

    text_norm = _normalize(text)
    categories_by_id = {category.id: category for category in policy_config.categories}
    complaint_policy = classify_complaint_policy(
        text=text,
        current_stage=current_stage,
        state=dict(state or {}),
    )
    forced_category_id = _forced_category_id(complaint_policy)
    if forced_category_id:
        category = categories_by_id.get(forced_category_id)
        if category is not None and category.enabled:
            return _build_result(
                category=category,
                confidence=max(0.75, complaint_policy.confidence),
                signals=_merge_policy_signals([], complaint_policy),
                policy_config=policy_config,
            )

    candidates: list[tuple[float, OperationalCategoryPolicy, list[str]]] = []
    for category in policy_config.categories:
        if not category.enabled:
            continue
        stage_score = _stage_score(category, current_stage)
        state_score = _state_score(category, state or {})
        signal_score, signals = _signal_score(text_norm, category)
        score = max(signal_score, stage_score, state_score)
        score, signals = _apply_complaint_policy_guards(
            category=category,
            score=score,
            signals=signals,
            complaint_policy=complaint_policy,
        )
        score, signals = _adjust_category_score(text_norm, category, score, signals)
        if score < category.signals.min_confidence:
            continue
        candidates.append((score, category, signals))

    best = _select_candidate(text_norm, candidates)
    if best is None or best[0] <= 0:
        return _unknown(signals=_merge_policy_signals([], complaint_policy))

    confidence, category, signals = best
    return _build_result(
        category=category,
        confidence=confidence,
        signals=_merge_policy_signals(signals, complaint_policy),
        policy_config=policy_config,
    )


def _unknown(*, signals: list[str] | None = None) -> OperationalIntentResult:
    return OperationalIntentResult(
        intent_category="unknown",
        risk_level="none",
        confidence=0.0,
        signals=signals or [],
    )


def _build_result(
    *,
    category: OperationalCategoryPolicy,
    confidence: float,
    signals: list[str],
    policy_config: PolicyConfig,
) -> OperationalIntentResult:
    return OperationalIntentResult(
        intent_category=category.id,
        risk_level=category.risk_level,
        confidence=min(1.0, confidence),
        signals=signals,
        effects=OperationalEffects(
            pause_bot=category.pause_rules.pause_bot,
            handoff_required=category.handoff_rules.required,
            block_pipeline=category.pause_rules.block_pipeline,
        ),
        blocked_actions=list(category.blocked_actions),
        destination_team=(
            category.handoff_rules.destination_team
            or category.destination_team
        ),
        auto_reply_allowed=(
            category.auto_reply_allowed
            if category.auto_reply_allowed is not None
            else category.pause_rules.auto_reply_allowed
        ),
        copilot_only=(
            category.copilot_only
            if category.copilot_only is not None
            else category.pause_rules.copilot_only
        ),
        reason_code=category.handoff_rules.reason_code or category.id,
        response_template_id=category.response_template_id,
        response_template=(
            policy_config.templates.get(category.response_template_id)
            if category.response_template_id
            else None
        ),
    )


def _signal_score(text_norm: str, category: OperationalCategoryPolicy) -> tuple[float, list[str]]:
    signals: list[str] = []
    score = 0.0
    text_tokens = _content_tokens(text_norm)
    raw_tokens = set(text_norm.split())
    for keyword in category.signals.keywords:
        keyword_norm = _normalize(keyword)
        if keyword_norm and _keyword_matches(text_norm, raw_tokens, keyword_norm):
            score = max(score, 0.75)
            signals.append(f"keyword:{_signal_label(keyword)}")
    for example in category.signals.semantic_examples:
        example_norm = _normalize(example)
        if not example_norm:
            continue
        if text_norm == example_norm:
            score = max(score, 0.95)
            signals.append(f"semantic_example:{_signal_label(example)}")
            continue
        if example_norm in text_norm or text_norm in example_norm:
            score = max(score, 0.86)
            signals.append(f"semantic_example:{_signal_label(example)}")
            continue
        overlap = _token_overlap(text_norm, example_norm)
        if overlap >= 0.72:
            score = max(score, min(0.85, overlap))
            signals.append(f"semantic_overlap:{_signal_label(example)}")
            continue
        fuzzy_overlap = _fuzzy_token_overlap(text_tokens, _content_tokens(example_norm))
        if fuzzy_overlap >= 0.5:
            score = max(score, 0.82)
            signals.append(f"semantic_fuzzy:{_signal_label(example)}")
            continue
        if fuzzy_overlap > 0 and category.risk_level in {"high", "medium"}:
            score = max(score, 0.74)
            signals.append(f"semantic_signal:{_signal_label(example)}")
            continue
        sequence_similarity = SequenceMatcher(None, text_norm, example_norm).ratio()
        if category.risk_level == "high" and sequence_similarity >= 0.32:
            score = max(score, 0.64)
            signals.append(f"semantic_similarity:{_signal_label(example)}")
    if category.signals.semantic_labels and text_norm:
        for label in category.signals.semantic_labels:
            label_norm = _normalize(label)
            if label_norm and label_norm in text_norm:
                score = max(score, 0.7)
                signals.append(f"semantic_label:{_signal_label(label)}")
    return score, signals


def _adjust_category_score(
    text_norm: str,
    category: OperationalCategoryPolicy,
    score: float,
    signals: list[str],
) -> tuple[float, list[str]]:
    if score <= 0:
        return score, signals
    if category.id == "human_request":
        if _has_strong_human_request_signal(text_norm):
            return max(score, 0.75), signals
        weak_semantic = any(
            signal.startswith("semantic_similarity:") or signal.startswith("semantic_signal:")
            for signal in signals
        )
        if weak_semantic or _has_catalog_or_requirements_signal(text_norm):
            return 0.0, []
    if category.id == "payment_sensitive":
        if _has_strong_payment_signal(text_norm):
            return max(score, 0.75), signals
        weak_semantic = any(
            signal.startswith("semantic_similarity:")
            or signal.startswith("semantic_signal:")
            or signal.startswith("semantic_fuzzy:")
            for signal in signals
        )
        if weak_semantic or _has_catalog_or_requirements_signal(text_norm):
            return 0.0, []
    if category.id == "documents":
        if _has_strong_document_signal(text_norm):
            return score, signals
        weak_semantic = any(
            signal.startswith("semantic_similarity:")
            or signal.startswith("semantic_signal:")
            or signal.startswith("semantic_fuzzy:")
            for signal in signals
        )
        if weak_semantic:
            return 0.0, []
    if category.id == "complaint":
        if _has_strong_complaint_signal(text_norm):
            return max(score, 0.75), signals
        weak_semantic = any(
            signal.startswith("semantic_similarity:")
            or signal.startswith("semantic_signal:")
            or signal.startswith("semantic_fuzzy:")
            for signal in signals
        )
        if weak_semantic:
            return 0.0, []
    return score, signals


def _select_candidate(
    text_norm: str,
    candidates: list[tuple[float, OperationalCategoryPolicy, list[str]]],
) -> tuple[float, OperationalCategoryPolicy, list[str]] | None:
    if not candidates:
        return None
    candidates = [candidate for candidate in candidates if candidate[0] > 0]
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0], reverse=True)
    best = candidates[0]
    if best[1].id != "human_request" or _has_strong_human_request_signal(text_norm):
        return best
    prioritized = {
        "sales",
        "credit",
        "faq",
        "documents",
    }
    for candidate in candidates[1:]:
        if candidate[1].id in prioritized and candidate[0] >= 0.7:
            return candidate
    return best


def _forced_category_id(complaint_policy: ComplaintPolicyResult) -> str | None:
    if complaint_policy.classification == "human_request":
        return "human_request"
    if complaint_policy.classification == "payment_sensitive":
        return "payment_sensitive"
    if complaint_policy.classification in {
        "strong_complaint",
        "legal_threat",
        "advisor_promise_conflict",
    }:
        return "complaint"
    return None


def _merge_policy_signals(
    signals: list[str],
    complaint_policy: ComplaintPolicyResult,
) -> list[str]:
    merged = list(signals)
    if complaint_policy.policy_signal and complaint_policy.policy_signal not in merged:
        merged.append(complaint_policy.policy_signal)
    for signal in complaint_policy.pattern_signals:
        if signal not in merged:
            merged.append(signal)
    return merged


def _apply_complaint_policy_guards(
    *,
    category: OperationalCategoryPolicy,
    score: float,
    signals: list[str],
    complaint_policy: ComplaintPolicyResult,
) -> tuple[float, list[str]]:
    if complaint_policy.classification in {
        "no_complaint",
        "mild_frustration",
        "process_complaint",
    } and category.id in {"complaint", "human_request", "payment_sensitive"}:
        return 0.0, []
    if complaint_policy.classification == "advisor_promise_conflict" and category.id == "human_request":
        return 0.0, []
    return score, signals


def _has_strong_human_request_signal(text_norm: str) -> bool:
    tokens = set(text_norm.split())
    if tokens & {"asesor", "asesora", "francisco", "humano", "humana", "persona"}:
        return True
    if "no bot" in text_norm or "no robot" in text_norm:
        return True
    if "pasame con alguien" in text_norm or "hablar con alguien" in text_norm:
        return True
    if "responder una persona" in text_norm or "atencion humana" in text_norm:
        return True
    return False


def _has_strong_payment_signal(text_norm: str) -> bool:
    tokens = set(text_norm.split())
    if tokens & {"pago", "pagar", "transferencia", "deposito", "cuenta", "clabe"}:
        return True
    strong_phrases = {
        "te pago hoy",
        "como hago el pago",
        "hacer el pago",
        "hacer pago",
    }
    return any(phrase in text_norm for phrase in strong_phrases)


def _has_strong_document_signal(text_norm: str) -> bool:
    tokens = set(text_norm.split())
    return bool(
        tokens
        & {
            "archivo",
            "adjunto",
            "borrosa",
            "comprobante",
            "comprobantes",
            "documento",
            "documentos",
            "domicilio",
            "envio",
            "foto",
            "imagen",
            "ine",
            "identificacion",
            "mando",
            "papeles",
            "papeleria",
        }
    )


def _has_strong_complaint_signal(text_norm: str) -> bool:
    tokens = set(text_norm.split())
    if tokens & {
        "queja",
        "quejas",
        "molesto",
        "molesta",
        "pesimo",
        "terrible",
        "horrible",
        "fraude",
        "engano",
    }:
        return True
    strong_phrases = {
        "mal servicio",
        "quiero poner una queja",
        "me atendieron mal",
        "pesimo servicio",
    }
    return any(phrase in text_norm for phrase in strong_phrases)


def _has_commercial_flow_signal(text_norm: str) -> bool:
    tokens = set(text_norm.split())
    commercial_terms = {
        "credito",
        "credito?",
        "enganche",
        "guardia",
        "modelo",
        "moto",
        "nomina",
        "recibos",
        "tarjeta",
    }
    if tokens & commercial_terms:
        return True
    commercial_phrases = {
        "me pagan",
        "por fuera",
        "sin comprobantes",
        "guardia de seguridad",
        "con comprobantes",
    }
    return any(phrase in text_norm for phrase in commercial_phrases)


def _has_catalog_or_requirements_signal(text_norm: str) -> bool:
    tokens = set(text_norm.split())
    catalog_terms = {
        "catalogo",
        "catalog",
        "modelo",
        "modelos",
        "moto",
        "motos",
        "opcion",
        "opciones",
        "chopper",
        "deportiva",
        "deportivas",
        "naked",
        "scooter",
        "trabajo",
        "urbana",
        "urbanas",
    }
    requirements_terms = {
        "comprobante",
        "comprobantes",
        "documento",
        "documentos",
        "ine",
        "papeleria",
        "papeles",
        "requisito",
        "requisitos",
    }
    return bool(tokens & catalog_terms) or bool(tokens & requirements_terms)


def _keyword_matches(text_norm: str, raw_tokens: set[str], keyword_norm: str) -> bool:
    if " " in keyword_norm:
        return keyword_norm in text_norm
    return keyword_norm in raw_tokens


def _stage_score(category: OperationalCategoryPolicy, current_stage: str | None) -> float:
    if not category.signals.current_stages or not current_stage:
        return 0.0
    current = _normalize(current_stage)
    configured = {_normalize(stage) for stage in category.signals.current_stages}
    return 0.6 if current in configured else 0.0


def _state_score(category: OperationalCategoryPolicy, state: Mapping[str, Any]) -> float:
    if not category.signals.state_conditions:
        return 0.0
    matches = 0
    for key, expected in category.signals.state_conditions.items():
        actual = _state_value(state, key)
        if actual == expected:
            matches += 1
    if not matches:
        return 0.0
    return min(0.7, matches / len(category.signals.state_conditions))


def _state_value(state: Mapping[str, Any], key: str) -> Any:
    value = state.get(key)
    if isinstance(value, Mapping) and "value" in value:
        return value.get("value")
    return value


def _token_overlap(left: str, right: str) -> float:
    left_tokens = set(left.split())
    right_tokens = set(right.split())
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / min(len(left_tokens), len(right_tokens))


def _fuzzy_token_overlap(left_tokens: list[str], right_tokens: list[str]) -> float:
    if not left_tokens or not right_tokens:
        return 0.0
    matches = 0
    used: set[int] = set()
    for left in left_tokens:
        for index, right in enumerate(right_tokens):
            if index in used:
                continue
            if left == right or SequenceMatcher(None, left, right).ratio() >= 0.72:
                matches += 1
                used.add(index)
                break
    return matches / min(len(left_tokens), len(right_tokens))


def _content_tokens(value: str) -> list[str]:
    stopwords = {
        "a",
        "al",
        "con",
        "de",
        "del",
        "el",
        "en",
        "es",
        "la",
        "las",
        "le",
        "lo",
        "los",
        "me",
        "mi",
        "para",
        "por",
        "que",
        "se",
        "si",
        "te",
        "tu",
        "un",
        "una",
        "y",
    }
    tokens: list[str] = []
    for token in value.split():
        if len(token) <= 2 or token in stopwords:
            continue
        tokens.append(_stem_token(token))
    return tokens


def _stem_token(token: str) -> str:
    for suffix in (
        "mente",
        "ciones",
        "cion",
        "ando",
        "iendo",
        "ado",
        "ada",
        "idos",
        "idas",
        "ido",
        "ida",
        "ar",
        "er",
        "ir",
        "es",
        "s",
    ):
        if len(token) > len(suffix) + 2 and token.endswith(suffix):
            return token[: -len(suffix)]
    return token


def _normalize(value: str) -> str:
    return normalize_whatsapp_text(value)


def _signal_label(value: str) -> str:
    return _normalize(value).replace(" ", "_")[:80]


__all__ = ["classify_operational_intent"]
