"""Tenant configuration validation.

The goal is not to make one vertical stricter in Python. The goal is to catch
tenant-authored contradictions before they become runtime bugs: mismatched
DOCS_* keys, docs_per_plan values that cannot be selected by the configured
customer field, Vision mappings pointing at removed docs, or prompts that refer
to missing customer fields / KB documents.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from atendia.contracts.flow_mode import FlowMode
from atendia.db.models.customer_fields import CustomerFieldDefinition
from atendia.db.models.knowledge_document import KnowledgeDocument

DOC_KEY_RE = re.compile(r"^DOCS_[A-Z][A-Z0-9_]*$")
CONTACT_TOKEN_RE = re.compile(r"\{\{\s*contact\.([A-Za-z][A-Za-z0-9_]*)\s*\}\}")
DOCUMENT_REF_RE = re.compile(r"(?:#|@)(?:documento?|document)\.([\w.-]+)", re.I)

DOC_STATUS_CHOICES = {"missing", "ok", "rejected"}
KNOWN_RUNTIME_FIELDS = {
    "antiguedad",
    "antiguedad_laboral_meses",
    "tipo_credito",
    "credito_plan",
    "plan_credito",
    "modelo_moto",
    "modelo_interes",
    "city",
    "ciudad",
}
VALID_VISION_CATEGORIES = {
    "ine",
    "comprobante",
    "recibo_nomina",
    "estado_cuenta",
    "constancia_sat",
    "factura",
    "imss",
}


@dataclass(slots=True)
class ConfigIssue:
    code: str
    severity: str
    message: str
    path: str | None = None

    def as_dict(self) -> dict[str, str]:
        out = {"code": self.code, "severity": self.severity, "message": self.message}
        if self.path:
            out["path"] = self.path
        return out


class ConfigValidationResult:
    def __init__(self, issues: list[ConfigIssue] | None = None) -> None:
        self.issues = issues or []

    @property
    def critical_count(self) -> int:
        return sum(1 for issue in self.issues if issue.severity == "critical")

    @property
    def warning_count(self) -> int:
        return sum(1 for issue in self.issues if issue.severity == "warning")

    @property
    def status(self) -> str:
        if self.critical_count:
            return "blocked"
        if self.warning_count:
            return "warning"
        return "ready"

    @property
    def summary(self) -> str:
        if self.critical_count:
            return f"No se puede guardar: {self.critical_count} error(es) critico(s)."
        if self.warning_count:
            return f"Se puede guardar, pero hay {self.warning_count} advertencia(s)."
        return "Configuracion lista."

    def add(self, code: str, severity: str, message: str, path: str | None = None) -> None:
        self.issues.append(ConfigIssue(code=code, severity=severity, message=message, path=path))

    def merge(self, other: "ConfigValidationResult") -> None:
        self.issues.extend(other.issues)

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "summary": self.summary,
            "critical_count": self.critical_count,
            "warning_count": self.warning_count,
            "issues": [issue.as_dict() for issue in self.issues],
        }

    def error_message(self) -> str:
        if not self.issues:
            return self.summary
        top = self.issues[:6]
        joined = "; ".join(
            f"{issue.path + ': ' if issue.path else ''}{issue.message}" for issue in top
        )
        extra = len(self.issues) - len(top)
        if extra > 0:
            joined = f"{joined}; +{extra} mas"
        return joined


async def _customer_field_defs(
    session: AsyncSession, tenant_id: UUID
) -> dict[str, CustomerFieldDefinition]:
    rows = (
        (
            await session.execute(
                select(CustomerFieldDefinition).where(
                    CustomerFieldDefinition.tenant_id == tenant_id
                )
            )
        )
        .scalars()
        .all()
    )
    return {row.key: row for row in rows}


async def _knowledge_filenames(session: AsyncSession, tenant_id: UUID) -> list[str]:
    return list(
        (
            await session.execute(
                select(KnowledgeDocument.filename).where(KnowledgeDocument.tenant_id == tenant_id)
            )
        )
        .scalars()
        .all()
    )


def choices_from_field(defn: CustomerFieldDefinition | None) -> set[str]:
    if defn is None:
        return set()
    opts = defn.field_options or {}
    raw = opts.get("choices") or opts.get("options")
    if not isinstance(raw, list):
        return set()
    return {str(item).strip() for item in raw if str(item).strip()}


def _is_known_field(field: str, fields: dict[str, CustomerFieldDefinition]) -> bool:
    root = field.split(".", 1)[0]
    return root in fields or root in KNOWN_RUNTIME_FIELDS or DOC_KEY_RE.fullmatch(root) is not None


def _doc_refs(definition: dict[str, Any]) -> list[tuple[str, str]]:
    refs: list[tuple[str, str]] = []
    docs_per_plan = definition.get("docs_per_plan")
    if isinstance(docs_per_plan, dict):
        for plan, docs in docs_per_plan.items():
            if isinstance(docs, list):
                for index, doc_key in enumerate(docs):
                    if isinstance(doc_key, str):
                        refs.append((doc_key, f"docs_per_plan.{plan}.{index}"))
    vision = definition.get("vision_doc_mapping")
    if isinstance(vision, dict):
        for category, docs in vision.items():
            if isinstance(docs, list):
                for index, doc_key in enumerate(docs):
                    if isinstance(doc_key, str):
                        refs.append((doc_key, f"vision_doc_mapping.{category}.{index}"))
    return refs


def _validate_prompt_references(
    *,
    result: ConfigValidationResult,
    text: str,
    path: str,
    fields: dict[str, CustomerFieldDefinition],
    filenames: list[str],
) -> None:
    for token in CONTACT_TOKEN_RE.findall(text or ""):
        if not _is_known_field(token, fields):
            result.add(
                "PROMPT_UNKNOWN_CONTACT_FIELD",
                "critical",
                f"El prompt referencia contact.{token}, pero ese campo no existe.",
                path,
            )
    normalized_files = [name.casefold() for name in filenames]
    for ref in DOCUMENT_REF_RE.findall(text or ""):
        needle = ref.replace("_", " ").replace("-", " ").casefold()
        if filenames and not any(needle in item.replace("_", " ").replace("-", " ") for item in normalized_files):
            result.add(
                "PROMPT_UNKNOWN_DOCUMENT",
                "warning",
                f"El prompt referencia #document.{ref}, pero no encontre un documento KB con ese nombre.",
                path,
            )


async def validate_pipeline_config(
    session: AsyncSession,
    tenant_id: UUID,
    definition: dict[str, Any],
) -> ConfigValidationResult:
    result = ConfigValidationResult()
    fields = await _customer_field_defs(session, tenant_id)
    filenames = await _knowledge_filenames(session, tenant_id)

    stages = definition.get("stages")
    if not isinstance(stages, list) or not stages:
        result.add("PIPELINE_STAGES_EMPTY", "critical", "El pipeline necesita al menos una etapa.", "stages")
        return result

    stage_ids: set[str] = set()
    for index, stage in enumerate(stages):
        if not isinstance(stage, dict):
            result.add("PIPELINE_STAGE_INVALID", "critical", "Cada etapa debe ser un objeto.", f"stages.{index}")
            continue
        stage_id = stage.get("id")
        if not isinstance(stage_id, str) or not re.fullmatch(r"^[a-z][a-z0-9_]*$", stage_id):
            result.add("PIPELINE_STAGE_ID_INVALID", "critical", "ID de etapa invalido.", f"stages.{index}.id")
        elif stage_id in stage_ids:
            result.add("PIPELINE_STAGE_ID_DUPLICATE", "critical", f"Etapa duplicada: {stage_id}.", f"stages.{index}.id")
        else:
            stage_ids.add(stage_id)

    for index, stage in enumerate(stages):
        if not isinstance(stage, dict):
            continue
        for transition in stage.get("transitions") or []:
            if isinstance(transition, dict) and transition.get("to") not in stage_ids:
                result.add(
                    "PIPELINE_TRANSITION_UNKNOWN_STAGE",
                    "critical",
                    f"Transicion apunta a una etapa inexistente: {transition.get('to')}.",
                    f"stages.{index}.transitions",
                )

    catalog = definition.get("documents_catalog") or []
    if not isinstance(catalog, list):
        result.add("DOC_CATALOG_INVALID", "critical", "documents_catalog debe ser una lista.", "documents_catalog")
        catalog = []
    catalog_keys: set[str] = set()
    normalized_seen: dict[str, str] = {}
    for index, item in enumerate(catalog):
        if not isinstance(item, dict):
            result.add("DOC_CATALOG_ITEM_INVALID", "critical", "Cada documento debe ser objeto.", f"documents_catalog.{index}")
            continue
        key = item.get("key")
        label = item.get("label")
        if not isinstance(key, str) or not DOC_KEY_RE.fullmatch(key):
            result.add(
                "DOC_KEY_INVALID",
                "critical",
                "La llave del documento debe iniciar con DOCS_ y usar mayusculas, numeros y guion bajo.",
                f"documents_catalog.{index}.key",
            )
            continue
        if key in catalog_keys:
            result.add("DOC_KEY_DUPLICATE", "critical", f"Documento duplicado: {key}.", f"documents_catalog.{index}.key")
        catalog_keys.add(key)
        normalized = key.casefold()
        if normalized in normalized_seen and normalized_seen[normalized] != key:
            result.add(
                "DOC_KEY_CASE_COLLISION",
                "critical",
                f"{key} choca con {normalized_seen[normalized]} por mayusculas/minusculas.",
                f"documents_catalog.{index}.key",
            )
        normalized_seen[normalized] = key
        if not isinstance(label, str) or not label.strip():
            result.add("DOC_LABEL_EMPTY", "critical", f"{key} no tiene nombre visible.", f"documents_catalog.{index}.label")
        if key not in fields:
            result.add(
                "DOC_FIELD_NOT_VISIBLE",
                "warning",
                f"{key} existe en expediente, pero no esta en Datos de cliente.",
                f"documents_catalog.{index}.key",
            )
        else:
            choices = choices_from_field(fields[key])
            if choices and not DOC_STATUS_CHOICES.issubset(choices):
                result.add(
                    "DOC_FIELD_STATUS_CHOICES",
                    "warning",
                    f"{key} deberia usar opciones missing, ok, rejected para evitar Si/No vs OK.",
                    f"customer_field_definitions.{key}",
                )

    docs_per_plan = definition.get("docs_per_plan") or {}
    if not isinstance(docs_per_plan, dict):
        result.add("DOCS_PER_PLAN_INVALID", "critical", "docs_per_plan debe ser un objeto.", "docs_per_plan")
        docs_per_plan = {}

    docs_plan_field = str(definition.get("docs_plan_field") or "plan_credito")
    plan_def = fields.get(docs_plan_field)
    if docs_per_plan and plan_def is None and docs_plan_field not in KNOWN_RUNTIME_FIELDS:
        result.add(
            "DOCS_PLAN_FIELD_MISSING",
            "critical",
            f"docs_plan_field={docs_plan_field} no existe en Datos de cliente.",
            "docs_plan_field",
        )
    plan_choices = choices_from_field(plan_def)
    for plan, docs in docs_per_plan.items():
        path = f"docs_per_plan.{plan}"
        if not isinstance(plan, str) or not plan.strip():
            result.add("DOCS_PLAN_EMPTY_KEY", "critical", "Hay un plan/caso sin nombre.", path)
        elif plan_choices and plan not in plan_choices:
            result.add(
                "DOCS_PLAN_KEY_NOT_SELECTABLE",
                "critical",
                f"{plan!r} no es una opcion exacta de {docs_plan_field}.",
                path,
            )
        if not isinstance(docs, list) or not docs:
            result.add("DOCS_PLAN_EMPTY_DOCS", "warning", f"{plan!r} no tiene documentos requeridos.", path)
            continue
        for index, doc_key in enumerate(docs):
            item_path = f"{path}.{index}"
            if not isinstance(doc_key, str) or not DOC_KEY_RE.fullmatch(doc_key):
                result.add("DOC_REF_INVALID", "critical", f"Documento invalido: {doc_key}.", item_path)
            elif doc_key not in catalog_keys:
                result.add("DOC_REF_NOT_IN_CATALOG", "critical", f"{doc_key} no existe en documents_catalog.", item_path)

    for doc_key, path in _doc_refs(definition):
        if isinstance(doc_key, str) and doc_key.startswith("docs_"):
            result.add(
                "DOC_KEY_LOWERCASE_LEGACY",
                "critical",
                f"Usa la llave canonica en mayusculas, por ejemplo {doc_key.upper()}.",
                path,
            )

    vision = definition.get("vision_doc_mapping") or {}
    if not isinstance(vision, dict):
        result.add("VISION_MAPPING_INVALID", "critical", "vision_doc_mapping debe ser un objeto.", "vision_doc_mapping")
    else:
        for category, docs in vision.items():
            path = f"vision_doc_mapping.{category}"
            if category not in VALID_VISION_CATEGORIES:
                result.add("VISION_CATEGORY_UNKNOWN", "warning", f"Categoria Vision desconocida: {category}.", path)
            if not isinstance(docs, list):
                result.add("VISION_MAPPING_DOCS_INVALID", "critical", "El mapeo debe ser una lista de DOCS_*.", path)
                continue
            for index, doc_key in enumerate(docs):
                if doc_key not in catalog_keys:
                    result.add("VISION_DOC_NOT_IN_CATALOG", "critical", f"{doc_key} no existe en documents_catalog.", f"{path}.{index}")

    for stage_index, stage in enumerate(stages):
        if not isinstance(stage, dict):
            continue
        rules = stage.get("auto_enter_rules")
        if not isinstance(rules, dict) or not rules.get("enabled"):
            continue
        conditions = rules.get("conditions")
        if not isinstance(conditions, list) or not conditions:
            result.add("AUTO_RULES_EMPTY", "critical", "Auto-entrada activa requiere condiciones.", f"stages.{stage_index}.auto_enter_rules")
            continue
        for condition_index, condition in enumerate(conditions):
            if not isinstance(condition, dict):
                result.add("AUTO_RULE_INVALID", "critical", "Cada condicion debe ser objeto.", f"stages.{stage_index}.auto_enter_rules.conditions.{condition_index}")
                continue
            field = condition.get("field")
            operator = condition.get("operator")
            cpath = f"stages.{stage_index}.auto_enter_rules.conditions.{condition_index}"
            if not isinstance(field, str) or not _is_known_field(field, fields):
                result.add("AUTO_RULE_FIELD_UNKNOWN", "critical", f"Campo desconocido en regla: {field}.", f"{cpath}.field")
            elif field.split(".", 1)[0].startswith("DOCS_") and field.split(".", 1)[0] not in catalog_keys:
                result.add(
                    "AUTO_RULE_DOC_NOT_IN_CATALOG",
                    "critical",
                    f"{field.split('.', 1)[0]} no existe en documents_catalog.",
                    f"{cpath}.field",
                )
            if operator == "docs_complete_for_plan":
                if not docs_per_plan:
                    result.add("DOCS_COMPLETE_WITHOUT_MAP", "critical", "docs_complete_for_plan necesita docs_per_plan.", cpath)
                if field != docs_plan_field:
                    result.add(
                        "DOCS_COMPLETE_FIELD_MISMATCH",
                        "critical",
                        f"docs_complete_for_plan usa {field}, pero docs_plan_field es {docs_plan_field}.",
                        f"{cpath}.field",
                    )

    for mode, prompt in (definition.get("mode_prompts") or {}).items():
        if mode not in {flow_mode.value for flow_mode in FlowMode}:
            result.add("MODE_PROMPT_UNKNOWN_MODE", "critical", f"Modo desconocido: {mode}.", f"mode_prompts.{mode}")
        if isinstance(prompt, str):
            _validate_prompt_references(
                result=result,
                text=prompt,
                path=f"mode_prompts.{mode}",
                fields=fields,
                filenames=filenames,
            )

    return result


async def validate_agent_config(
    session: AsyncSession,
    tenant_id: UUID,
    data: dict[str, Any],
) -> ConfigValidationResult:
    result = ConfigValidationResult()
    fields = await _customer_field_defs(session, tenant_id)
    filenames = await _knowledge_filenames(session, tenant_id)

    extraction = data.get("extraction_config") or {}
    if isinstance(extraction, dict):
        raw_fields = extraction.get("fields") or []
        if isinstance(raw_fields, list):
            for index, item in enumerate(raw_fields):
                key = item.get("key") if isinstance(item, dict) else item
                if isinstance(key, str) and key and not _is_known_field(key, fields):
                    result.add(
                        "AGENT_EXTRACTION_FIELD_UNKNOWN",
                        "critical",
                        f"El agente intenta extraer {key}, pero no existe en Datos de cliente.",
                        f"extraction_config.fields.{index}",
                    )

    prompt = data.get("system_prompt")
    if isinstance(prompt, str):
        _validate_prompt_references(
            result=result,
            text=prompt,
            path="system_prompt",
            fields=fields,
            filenames=filenames,
        )

    return result
