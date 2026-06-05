from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal, TypeVar

from atendia.text_normalization import normalize_whatsapp_text


AttachmentIntentKind = Literal[
    "identity_document_front",
    "identity_document_back",
    "proof_of_address",
    "motorcycle_photo",
    "irrelevant_image",
    "blurry_unknown",
    "ad_reference",
    "unknown_attachment",
]
T = TypeVar("T")


@dataclass(frozen=True)
class AttachmentDocumentWrite:
    key: str
    label: str
    source_label: str


@dataclass(frozen=True)
class AttachmentIntentResult:
    labels: tuple[str, ...]
    kinds: tuple[AttachmentIntentKind, ...]
    accepted_documents: tuple[AttachmentDocumentWrite, ...]
    rejected_labels: tuple[str, ...]
    ignored_labels: tuple[str, ...]
    non_document_labels: tuple[str, ...]
    unknown_labels: tuple[str, ...]
    reason_codes: tuple[str, ...]
    suggested_clarification: str | None = None

    @property
    def has_trusted_document(self) -> bool:
        return bool(self.accepted_documents)

    @property
    def has_unresolved_document_like_attachment(self) -> bool:
        return bool(self.rejected_labels)

    @property
    def has_non_document_attachment(self) -> bool:
        return bool(self.ignored_labels or self.non_document_labels or self.unknown_labels)


def classify_attachment_intent(
    *,
    attachments: list[Any] | None,
    metadata: Mapping[str, Any] | None,
    pipeline: Any,
) -> AttachmentIntentResult:
    """Classify attachments before any commercial/document state write."""

    labels = _attachment_semantic_labels(attachments=attachments, metadata=metadata)
    accepted: list[AttachmentDocumentWrite] = []
    rejected: list[str] = []
    ignored: list[str] = []
    non_documents: list[str] = []
    unknowns: list[str] = []
    kinds: list[AttachmentIntentKind] = []
    reasons: list[str] = []
    clarification: str | None = None

    for label in labels:
        kind = attachment_kind_for_label(label)
        kinds.append(kind)
        if kind in {
            "identity_document_front",
            "identity_document_back",
            "proof_of_address",
        }:
            key = document_key_for_attachment_label(pipeline, label)
            if key:
                accepted.append(
                    AttachmentDocumentWrite(
                        key=key,
                        label=_document_label(pipeline, key),
                        source_label=label,
                    )
                )
                reasons.append("trusted_attachment_semantic_label")
            else:
                rejected.append(label)
                reasons.append("document_label_unmapped_no_state_write")
            continue
        if kind == "blurry_unknown":
            rejected.append(label)
            reasons.append("blurry_attachment_no_state_write")
            continue
        if kind == "irrelevant_image":
            ignored.append(label)
            reasons.append("irrelevant_attachment_ignored")
            continue
        if kind in {"motorcycle_photo", "ad_reference"}:
            non_documents.append(label)
            reasons.append("non_document_attachment_no_state_write")
            clarification = (
                "Vi la imagen, pero no puedo confirmar el modelo solo con la foto. "
                "Me compartes el nombre, link o modelo?"
            )
            continue
        unknowns.append(label)
        reasons.append("unknown_attachment_no_state_write")

    if not labels and attachments:
        unknowns.append("unlabeled_attachment")
        kinds.append("unknown_attachment")
        reasons.append("unlabeled_attachment_no_state_write")

    if rejected and clarification is None:
        clarification = (
            "La foto no se alcanza a validar bien. Me la puedes reenviar mas clara?"
        )
    elif unknowns and clarification is None:
        clarification = (
            "Recibi el adjunto, pero no puedo clasificarlo con seguridad. "
            "Me confirmas que documento o modelo es?"
        )

    return AttachmentIntentResult(
        labels=tuple(labels),
        kinds=tuple(_dedupe(kinds)),
        accepted_documents=tuple(_dedupe_documents(accepted)),
        rejected_labels=tuple(_dedupe(rejected)),
        ignored_labels=tuple(_dedupe(ignored)),
        non_document_labels=tuple(_dedupe(non_documents)),
        unknown_labels=tuple(_dedupe(unknowns)),
        reason_codes=tuple(_dedupe(reasons)),
        suggested_clarification=clarification,
    )


def attachment_kind_for_label(label: str) -> AttachmentIntentKind:
    normalized = _normalize_label(label)
    if not normalized:
        return "unknown_attachment"
    if normalized in {
        "identity document front",
        "identity front",
        "ine front",
        "ine frente",
        "identificacion frente",
        "documento identidad frente",
    }:
        return "identity_document_front"
    if normalized in {
        "identity document back",
        "identity back",
        "ine back",
        "ine atras",
        "ine reverso",
        "identificacion reverso",
        "identificacion atras",
        "documento identidad reverso",
    }:
        return "identity_document_back"
    if normalized in {
        "proof of address",
        "address proof",
        "comprobante domicilio",
        "comprobante de domicilio",
        "domicilio",
        "proof address",
    }:
        return "proof_of_address"
    if normalized in {
        "motorcycle photo",
        "moto photo",
        "foto moto",
        "foto de moto",
        "motorcycle",
    }:
        return "motorcycle_photo"
    if normalized in {
        "irrelevant image",
        "imagen irrelevante",
        "random image",
        "irrelevant",
    }:
        return "irrelevant_image"
    if normalized in {
        "blurry unknown",
        "blurry document",
        "foto borrosa",
        "imagen borrosa",
        "borrosa",
    }:
        return "blurry_unknown"
    if normalized in {
        "ad reference",
        "referencia anuncio",
        "anuncio",
        "ad",
        "reference",
    }:
        return "ad_reference"
    return "unknown_attachment"


def document_key_for_attachment_label(pipeline: Any, label: str) -> str | None:
    kind = attachment_kind_for_label(label)
    if kind == "identity_document_front":
        return _find_document_key(pipeline, family="identity", side="front")
    if kind == "identity_document_back":
        return _find_document_key(pipeline, family="identity", side="back")
    if kind == "proof_of_address":
        return _find_document_key(pipeline, family="address", side=None)
    return None


def _attachment_semantic_labels(
    *,
    attachments: list[Any] | None,
    metadata: Mapping[str, Any] | None,
) -> list[str]:
    labels: list[str] = []
    for attachment in attachments or []:
        caption = getattr(attachment, "caption", None)
        if caption:
            labels.append(str(caption))
    if isinstance(metadata, Mapping):
        for item in metadata.get("attachments") or []:
            if isinstance(item, Mapping) and item.get("semantic_label"):
                labels.append(str(item["semantic_label"]))
        media = metadata.get("media")
        if isinstance(media, Mapping) and media.get("semantic_label"):
            labels.append(str(media["semantic_label"]))
    return _dedupe([label for label in labels if str(label).strip()])


def _find_document_key(pipeline: Any, *, family: str, side: str | None) -> str | None:
    docs = list(getattr(pipeline, "documents_catalog", []) or [])
    if not docs:
        return None
    for doc in docs:
        key = str(getattr(doc, "key", "") or "")
        label = str(getattr(doc, "label", "") or "")
        haystack = _normalize_label(f"{key} {label}")
        if family == "identity" and not _has_any(
            haystack,
            ("ine", "identificacion", "identidad", "identity"),
        ):
            continue
        if family == "address" and not _has_any(
            haystack,
            ("comprobante", "domicilio", "address", "proof"),
        ):
            continue
        if side == "front" and not _has_any(haystack, ("frente", "front")):
            continue
        if side == "back" and not _has_any(haystack, ("atras", "reverso", "back")):
            continue
        return key
    expected_keys = {
        ("identity", "front"): "INE_FRENTE",
        ("identity", "back"): "INE_ATRAS",
        ("address", None): "COMPROBANTE_DOMICILIO",
    }
    fallback = expected_keys.get((family, side))
    if fallback and any(str(getattr(doc, "key", "") or "") == fallback for doc in docs):
        return fallback
    return None


def _document_label(pipeline: Any, key: str) -> str:
    for doc in getattr(pipeline, "documents_catalog", []) or []:
        if str(getattr(doc, "key", "")) == key:
            return str(getattr(doc, "label", None) or key)
    return key


def _has_any(value: str, terms: tuple[str, ...]) -> bool:
    return any(term in value for term in terms)


def _normalize_label(value: str) -> str:
    normalized = normalize_whatsapp_text(str(value or ""))
    return normalized.replace("_", " ").replace("-", " ").strip()


def _dedupe(items: list[T]) -> list[T]:
    result: list[T] = []
    seen: set[Any] = set()
    for item in items:
        marker = item
        if isinstance(item, AttachmentDocumentWrite):
            marker = (item.key, item.source_label)
        if marker in seen:
            continue
        seen.add(marker)
        result.append(item)
    return result


def _dedupe_documents(
    items: list[AttachmentDocumentWrite],
) -> list[AttachmentDocumentWrite]:
    result: list[AttachmentDocumentWrite] = []
    seen: set[str] = set()
    for item in items:
        if item.key in seen:
            continue
        seen.add(item.key)
        result.append(item)
    return result


__all__ = [
    "AttachmentDocumentWrite",
    "AttachmentIntentKind",
    "AttachmentIntentResult",
    "attachment_kind_for_label",
    "classify_attachment_intent",
    "document_key_for_attachment_label",
]
