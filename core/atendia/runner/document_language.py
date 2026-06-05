from __future__ import annotations

import re
import unicodedata
from typing import Any


def _normalize(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    decomposed = unicodedata.normalize("NFKD", text)
    without_accents = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    sanitized = re.sub(r"[_-]+", " ", without_accents.casefold())
    return re.sub(r"\s+", " ", sanitized).strip()


def _doc_label_value(raw_doc: Any) -> str:
    if isinstance(raw_doc, dict):
        label = raw_doc.get("label") or raw_doc.get("key")
    else:
        label = raw_doc
    return str(label or "").strip()


def _doc_concept(value: Any) -> str | None:
    normalized = _normalize(_doc_label_value(value))
    if not normalized:
        return None
    if normalized == "ine frente":
        return "ine_front"
    if normalized == "ine atras":
        return "ine_back"
    if normalized in {"comprobante domicilio", "domicilio", "comprobante de domicilio"}:
        return "proof_of_address"
    if "estado de cuenta" in normalized or "estados de cuenta" in normalized:
        return "bank_statements"
    return None


def humanize_document_label(value: Any) -> str:
    concept = _doc_concept(value)
    if concept == "ine_front":
        return "parte de enfrente de tu INE"
    if concept == "ine_back":
        return "parte de atras de tu INE"
    if concept == "proof_of_address":
        return "comprobante de domicilio reciente"
    if concept == "bank_statements":
        return "estados de cuenta"
    return _doc_label_value(value)


def humanize_document_labels(raw_docs: Any) -> list[str]:
    docs = raw_docs if isinstance(raw_docs, list) else []
    values = [_doc_label_value(item) for item in docs if _doc_label_value(item)]
    concepts = {_doc_concept(item) for item in docs}
    labels: list[str] = []
    if {"ine_front", "ine_back"} <= concepts:
        labels.append("INE por ambos lados")
    else:
        if "ine_front" in concepts:
            labels.append("parte de enfrente de tu INE")
        if "ine_back" in concepts:
            labels.append("parte de atras de tu INE")
    if "proof_of_address" in concepts:
        labels.append("comprobante de domicilio reciente")
    for value in values:
        concept = _doc_concept(value)
        if concept in {"ine_front", "ine_back", "proof_of_address"}:
            continue
        human = humanize_document_label(value)
        if human:
            labels.append(human)
    deduped: list[str] = []
    seen: set[str] = set()
    for label in labels:
        key = _normalize(label)
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(label)
    return deduped


def join_humanized_documents(raw_docs: Any) -> str:
    labels = humanize_document_labels(raw_docs)
    if not labels:
        return ""
    if len(labels) == 1:
        return labels[0]
    if len(labels) == 2:
        return f"{labels[0]} y {labels[1]}"
    return ", ".join(labels[:-1]) + f" y {labels[-1]}"


def extract_document_labels_from_text(text: str) -> list[str]:
    normalized = _normalize(text)
    if not normalized:
        return []
    labels: list[str] = []
    if "ine por ambos lados" in normalized or ("ine" in normalized and "ambos lados" in normalized):
        labels.extend(["INE-FRENTE", "INE-ATRAS"])
    else:
        if "ine frente" in normalized or "parte de enfrente de tu ine" in normalized:
            labels.append("INE-FRENTE")
        if "ine atras" in normalized or "parte de atras de tu ine" in normalized:
            labels.append("INE-ATRAS")
    if (
        "comprobante de domicilio" in normalized
        or "domicilio reciente" in normalized
        or re.search(r"\bdomicilio\b", normalized)
    ):
        labels.append("Domicilio")
    if "estado de cuenta" in normalized or "estados de cuenta" in normalized:
        labels.append("Estados de cuenta")
    deduped: list[str] = []
    seen: set[str] = set()
    for label in labels:
        key = _normalize(label)
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(label)
    return deduped


def infer_requirement_subject(text: str) -> str | None:
    normalized = _normalize(text)
    if not normalized:
        return None
    if "estado de cuenta" in normalized or "estados de cuenta" in normalized:
        return "bank_statements"
    if "ine" in normalized or "identificacion" in normalized:
        return "ine"
    if "comprobante" in normalized or "domicilio" in normalized:
        return "proof_of_address"
    return None


def requirement_subject_answer(*, subject: str, required_docs: Any) -> str | None:
    required = required_docs if isinstance(required_docs, list) else []
    concepts = {_doc_concept(item) for item in required}
    if subject == "bank_statements":
        if "bank_statements" in concepts:
            return "Si, para tu plan actual si te pediriamos estados de cuenta."
        return "Con tu plan actual no te estoy pidiendo estados de cuenta."
    if subject == "ine":
        if {"ine_front", "ine_back"} <= concepts:
            return "Si, para tu plan actual te pediria tu INE por ambos lados."
        if "ine_front" in concepts:
            return "Si, para tu plan actual te pediria la parte de enfrente de tu INE."
        if "ine_back" in concepts:
            return "Si, para tu plan actual te pediria la parte de atras de tu INE."
        return "Por ahora no te estoy pidiendo INE."
    if subject == "proof_of_address":
        if "proof_of_address" in concepts:
            return "Si, para tu plan actual si te pediria un comprobante de domicilio reciente."
        return "Por ahora no te estoy pidiendo comprobante de domicilio."
    return None


__all__ = [
    "extract_document_labels_from_text",
    "humanize_document_label",
    "humanize_document_labels",
    "infer_requirement_subject",
    "join_humanized_documents",
    "requirement_subject_answer",
]
