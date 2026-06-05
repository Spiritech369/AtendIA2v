from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from atendia.agent_runtime.schemas import TenantRuntimeConfigContext, TurnContext

CONTRACT_VERSION = "1.0"
SUPPORTED_DOMAINS = {
    "vehicle_credit_sales",
    "appointment_services",
    "generic_lead_qualification",
}


class TenantDomainField(BaseModel):
    model_config = ConfigDict(extra="allow")

    key: str
    label: str | None = None
    type: str | None = None
    domain_role: str | None = None
    aliases: list[str] = Field(default_factory=list)
    write_policy: str | None = None
    owner: str | None = None
    allowed_sources: list[str] = Field(default_factory=list)
    evidence_required: bool = False
    invalidates_roles: list[str] = Field(default_factory=list)
    invalidates_fields: list[str] = Field(default_factory=list)
    value_path: str | None = None
    required_tools: list[str] = Field(default_factory=list)


class TenantDomainTool(BaseModel):
    model_config = ConfigDict(extra="allow")

    tool_id: str
    topic: str
    aliases: list[str] = Field(default_factory=list)


class TenantDomainContract(BaseModel):
    model_config = ConfigDict(extra="allow")

    contract_version: Literal["1.0"]
    tenant_id: str
    agent_id: str | None = None
    domain: Literal[
        "vehicle_credit_sales",
        "appointment_services",
        "generic_lead_qualification",
    ]
    locale: str = "es-MX"
    timezone: str = "America/Mexico_City"
    entities: dict[str, Any] = Field(default_factory=dict)
    fields: list[TenantDomainField] = Field(default_factory=list)
    tools: list[TenantDomainTool] = Field(default_factory=list)
    pipeline: dict[str, Any] = Field(default_factory=dict)
    workflow_events: list[Any] = Field(default_factory=list)
    guards: list[Any] = Field(default_factory=list)
    frontend: dict[str, Any] = Field(default_factory=dict)
    trace: dict[str, Any] = Field(default_factory=dict)
    safety: dict[str, Any] = Field(default_factory=dict)
    safe_mode: bool = False

    @model_validator(mode="after")
    def require_unique_keys(self) -> TenantDomainContract:
        field_keys = [field.key for field in self.fields]
        tool_ids = [tool.tool_id for tool in self.tools]
        if len(field_keys) != len(set(field_keys)):
            raise ValueError("tenant domain fields must have unique keys")
        if len(tool_ids) != len(set(tool_ids)):
            raise ValueError("tenant domain tools must have unique tool_id values")
        return self


@dataclass(frozen=True)
class TenantDomainContractLoadResult:
    contract: TenantDomainContract
    safe_mode: bool
    reason: str | None = None
    errors: list[str] | None = None

    def trace_metadata(self) -> dict[str, Any]:
        if self.safe_mode:
            return {
                "tenant_domain_contract": {
                    "version": self.contract.contract_version,
                    "domain": self.contract.domain,
                    "safe_mode": True,
                    "reason": self.reason or "missing_or_invalid_contract",
                },
                "field_metadata_loaded": False,
                "tool_metadata_loaded": False,
                "pipeline_metadata_loaded": False,
                "guard_metadata_loaded": bool(self.contract.guards),
            }
        return {
            "tenant_domain_contract": {
                "version": self.contract.contract_version,
                "domain": self.contract.domain,
                "safe_mode": False,
            },
            "field_metadata_loaded": bool(self.contract.fields),
            "tool_metadata_loaded": bool(self.contract.tools),
            "pipeline_metadata_loaded": bool(self.contract.pipeline),
            "guard_metadata_loaded": bool(self.contract.guards),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract": self.contract.model_dump(mode="json"),
            "safe_mode": self.safe_mode,
            "reason": self.reason,
            "errors": list(self.errors or []),
        }


def load_tenant_domain_contract(
    raw_contract: Any,
    *,
    tenant_id: str,
    agent_id: str | None = None,
) -> TenantDomainContractLoadResult:
    raw = _extract_raw_contract(raw_contract)
    if raw is None:
        return _safe_result(tenant_id=tenant_id, agent_id=agent_id, reason="missing_contract")
    if not isinstance(raw, dict):
        return _safe_result(
            tenant_id=tenant_id,
            agent_id=agent_id,
            reason="invalid_contract_payload",
            errors=["contract payload must be an object"],
        )

    normalized = dict(raw)
    normalized.setdefault("tenant_id", tenant_id)
    if agent_id is not None:
        normalized.setdefault("agent_id", agent_id)
    if str(normalized.get("tenant_id") or "") != str(tenant_id):
        return _safe_result(
            tenant_id=tenant_id,
            agent_id=agent_id,
            reason="tenant_id_mismatch",
            errors=[
                "contract tenant_id does not match current tenant_id: "
                f"{normalized.get('tenant_id')!r}"
            ],
        )

    try:
        contract = TenantDomainContract.model_validate(normalized)
    except ValidationError as exc:
        return _safe_result(
            tenant_id=tenant_id,
            agent_id=agent_id,
            reason="invalid_contract",
            errors=[error["msg"] for error in exc.errors()],
        )
    except ValueError as exc:
        return _safe_result(
            tenant_id=tenant_id,
            agent_id=agent_id,
            reason="invalid_contract",
            errors=[str(exc)],
        )

    return TenantDomainContractLoadResult(
        contract=contract,
        safe_mode=False,
        reason=None,
        errors=[],
    )


def apply_tenant_domain_contract(
    config: TenantRuntimeConfigContext,
    result: TenantDomainContractLoadResult,
) -> TenantRuntimeConfigContext:
    contract = result.contract
    ruleset = dict(config.ruleset)
    tools = dict(config.tools)
    metadata = dict(config.metadata)

    mandatory_tools = dict(ruleset.get("mandatory_tools") or {})
    existing_rules = _list(mandatory_tools.get("rules"))
    contract_rules = mandatory_tool_rules_from_contract(contract)
    existing_rule_ids = {
        str(rule.get("rule_id"))
        for rule in existing_rules
        if isinstance(rule, dict) and rule.get("rule_id")
    }
    mandatory_tools["rules"] = [
        *existing_rules,
        *[
            rule
            for rule in contract_rules
            if str(rule.get("rule_id")) not in existing_rule_ids
        ],
    ]
    mandatory_tools["tool_aliases"] = _merge_tool_aliases(
        mandatory_tools.get("tool_aliases"),
        tool_aliases_from_contract(contract),
    )
    ruleset["mandatory_tools"] = mandatory_tools

    tools["aliases"] = _merge_tool_aliases(
        tools.get("aliases") or tools.get("tool_aliases"),
        tool_aliases_from_contract(contract),
    )

    metadata["tenant_domain_contract"] = {
        "version": contract.contract_version,
        "domain": contract.domain,
        "safe_mode": result.safe_mode,
        "reason": result.reason,
    }
    if result.errors:
        metadata["tenant_domain_contract_errors"] = list(result.errors)

    return config.model_copy(
        update={
            "ruleset": ruleset,
            "tools": tools,
            "metadata": metadata,
            "tenant_domain_contract": contract.model_dump(mode="json"),
            "domain": contract.domain,
            "field_metadata": field_metadata_from_contract(contract),
            "tool_metadata": tool_metadata_from_contract(contract),
            "pipeline_metadata": dict(contract.pipeline),
            "workflow_event_metadata": workflow_event_metadata_from_contract(contract),
            "guard_metadata": guard_metadata_from_contract(contract),
            "frontend_metadata": dict(contract.frontend),
            "safe_mode": result.safe_mode,
        }
    )


def tenant_domain_trace_metadata(context: TurnContext) -> dict[str, Any]:
    contract = context.tenant_config.tenant_domain_contract
    if not contract:
        return {}
    safe_mode = bool(context.tenant_config.safe_mode)
    payload: dict[str, Any] = {
        "tenant_domain_contract": {
            "version": str(contract.get("contract_version") or CONTRACT_VERSION),
            "domain": str(context.tenant_config.domain or contract.get("domain") or ""),
            "safe_mode": safe_mode,
        },
        "field_metadata_loaded": bool(context.tenant_config.field_metadata),
        "tool_metadata_loaded": bool(context.tenant_config.tool_metadata),
        "pipeline_metadata_loaded": bool(context.tenant_config.pipeline_metadata),
        "guard_metadata_loaded": bool(context.tenant_config.guard_metadata),
    }
    reason = context.tenant_config.metadata.get("tenant_domain_contract", {}).get("reason")
    if safe_mode and reason:
        payload["tenant_domain_contract"]["reason"] = reason
    return payload


def field_metadata_from_contract(contract: TenantDomainContract) -> dict[str, dict[str, Any]]:
    return {
        field.key: field.model_dump(mode="json", exclude_none=True)
        for field in contract.fields
    }


def tool_metadata_from_contract(contract: TenantDomainContract) -> dict[str, dict[str, Any]]:
    return {
        tool.tool_id: tool.model_dump(mode="json", exclude_none=True)
        for tool in contract.tools
    }


def workflow_event_metadata_from_contract(
    contract: TenantDomainContract,
) -> dict[str, dict[str, Any]]:
    metadata: dict[str, dict[str, Any]] = {}
    for event in contract.workflow_events:
        if isinstance(event, str):
            metadata[event] = {"key": event}
            continue
        if isinstance(event, dict):
            key = str(
                event.get("key")
                or event.get("event_type")
                or event.get("event")
                or event.get("id")
                or ""
            )
            if key:
                metadata[key] = dict(event)
    return metadata


def guard_metadata_from_contract(contract: TenantDomainContract) -> dict[str, dict[str, Any]]:
    metadata: dict[str, dict[str, Any]] = {}
    for guard in contract.guards:
        if isinstance(guard, str):
            metadata[guard] = {"guard_id": guard}
            continue
        if isinstance(guard, dict):
            key = str(guard.get("guard_id") or guard.get("key") or guard.get("id") or "")
            if key:
                metadata[key] = dict(guard)
    return metadata


def tool_aliases_from_contract(contract: TenantDomainContract) -> dict[str, list[str]]:
    aliases: dict[str, list[str]] = {}
    for tool in contract.tools:
        values = [str(alias) for alias in tool.aliases if str(alias).strip()]
        if values:
            aliases[tool.tool_id] = list(dict.fromkeys(values))
    raw_aliases = contract.tools and getattr(contract, "tool_aliases", None)
    aliases = _merge_tool_aliases(raw_aliases, aliases)
    return aliases


def mandatory_tool_rules_from_contract(contract: TenantDomainContract) -> list[dict[str, Any]]:
    by_topic = _tools_by_topic(contract)
    rules: list[dict[str, Any]] = []

    if by_topic.get("offer_or_quote"):
        rules.append(
            _rule(
                contract,
                "offer_or_quote",
                by_topic["offer_or_quote"],
                reason="tenant_contract_offer_requires_quote_tool",
                uses_price_signal=True,
                response_plan_pattern=(
                    r"\b(?:precio|cotizacion|cotizar|enganche|mensualidad|pago|"
                    r"descuento|vigencia)\b"
                ),
                blocking_scopes=["final_message", "state_write", "workflow_event"],
            )
        )
    if by_topic.get("requirements"):
        rules.append(
            _rule(
                contract,
                "requirements",
                by_topic["requirements"],
                reason="tenant_contract_requirements_require_tool",
                final_message_pattern=(
                    r"\b(?:requisito|requisitos|documento|documentos|papeleria|"
                    r"papeles|ine|comprobante)\b"
                ),
                response_plan_pattern=(
                    r"\b(?:requisito|requisitos|documento|documentos|papeleria|"
                    r"papeles|ine|comprobante)\b"
                ),
                state_change_key_patterns=["document", "requirement", "doc_"],
                state_change_metadata_keys=["document_status", "requirements_complete"],
                blocking_scopes=["final_message", "workflow_event"],
            )
        )
    policy_tool = by_topic.get("policy_or_faq")
    if policy_tool:
        alternatives = [
            tool.tool_id
            for tool in contract.tools
            if tool.topic == "policy_or_faq" and tool.tool_id != policy_tool.tool_id
        ]
        if "policy.lookup" not in {policy_tool.tool_id, *alternatives}:
            alternatives.append("policy.lookup")
        rules.append(
            _rule(
                contract,
                "policy_or_faq",
                policy_tool,
                reason="tenant_contract_sensitive_policy_requires_tool",
                final_message_pattern=(
                    r"\b(?:politica|restriccion|aprobacion|aprobar|aprueba|"
                    r"aprobado|garantia|cobertura|buro|rechazo|rechazado)\b"
                ),
                response_plan_pattern=(
                    r"\b(?:politica|restriccion|aprobacion|aprobar|aprueba|"
                    r"aprobado|garantia|cobertura|buro|rechazo|rechazado)\b"
                ),
                alternative_tool_ids=alternatives,
            )
        )
    if by_topic.get("document_status"):
        rules.append(
            _rule(
                contract,
                "document_status",
                by_topic["document_status"],
                reason="tenant_contract_document_status_requires_document_tool",
                final_message_pattern=(
                    r"\b(?:documento|documentos).{0,30}"
                    r"(?:recibido|recibidos|validado|completo|completa|rechazado)\b"
                ),
                response_plan_pattern=(
                    r"\b(?:documento|documentos).{0,30}"
                    r"(?:recibido|recibidos|validado|completo|completa|rechazado)\b"
                ),
                state_change_key_patterns=["document", "requirement", "doc_"],
                state_change_metadata_keys=["document_status", "requirements_complete"],
                blocking_scopes=["final_message", "state_write", "workflow_event"],
            )
        )
    if by_topic.get("availability"):
        rules.append(
            _rule(
                contract,
                "availability",
                by_topic["availability"],
                reason="tenant_contract_availability_requires_tool",
                final_message_pattern=(
                    r"\b(?:cita|agenda|agendar|horario|disponibilidad|disponible|turno)\b"
                ),
                response_plan_pattern=(
                    r"\b(?:cita|agenda|agendar|horario|disponibilidad|disponible|turno)\b"
                ),
            )
        )
    if by_topic.get("booking_or_action"):
        rules.append(
            _rule(
                contract,
                "booking_or_action",
                by_topic["booking_or_action"],
                reason="tenant_contract_booking_requires_tool",
                final_message_pattern=(
                    r"\b(?:cita|agenda|agendada|agendar|reservar|reserva|"
                    r"confirmada|confirmar)\b"
                ),
                response_plan_pattern=(
                    r"\b(?:cita|agenda|agendada|agendar|reservar|reserva|"
                    r"confirmada|confirmar)\b"
                ),
                blocking_scopes=["final_message", "workflow_event"],
            )
        )
    return rules


def _safe_result(
    *,
    tenant_id: str,
    agent_id: str | None,
    reason: str,
    errors: list[str] | None = None,
) -> TenantDomainContractLoadResult:
    contract = TenantDomainContract(
        contract_version=CONTRACT_VERSION,
        tenant_id=tenant_id,
        agent_id=agent_id,
        domain="generic_lead_qualification",
        fields=[],
        tools=[],
        pipeline={},
        workflow_events=[],
        guards=["mandatory_tool_guard", "final_copy_guard"],
        frontend={},
        trace={},
        safety={"safe_mode": True, "reason": reason},
        safe_mode=True,
    )
    return TenantDomainContractLoadResult(
        contract=contract,
        safe_mode=True,
        reason=reason,
        errors=errors or [],
    )


def _extract_raw_contract(raw: Any) -> Any:
    if isinstance(raw, dict):
        for key in ("tenant_domain_contract", "domain_contract"):
            nested = raw.get(key)
            if isinstance(nested, dict):
                return nested
        return raw
    return raw


def _tools_by_topic(contract: TenantDomainContract) -> dict[str, TenantDomainTool]:
    by_topic: dict[str, TenantDomainTool] = {}
    for tool in contract.tools:
        by_topic.setdefault(tool.topic, tool)
    return by_topic


def _rule(
    contract: TenantDomainContract,
    topic: str,
    tool: TenantDomainTool,
    *,
    reason: str,
    final_message_pattern: str | None = None,
    response_plan_pattern: str | None = None,
    state_change_key_patterns: list[str] | None = None,
    state_change_metadata_keys: list[str] | None = None,
    lifecycle_stage_pattern: str | None = None,
    blocking_scopes: list[str] | None = None,
    alternative_tool_ids: list[str] | None = None,
    uses_price_signal: bool = False,
) -> dict[str, Any]:
    return {
        "rule_id": f"tenant_domain:{contract.domain}:{topic}",
        "topic": topic,
        "tool_id": tool.tool_id,
        "reason": reason,
        "trigger_source": "tenant_domain_contract",
        "blocking_scopes": blocking_scopes or ["final_message"],
        "fallback": "ask_clarifying_or_handoff",
        "alternative_tool_ids": alternative_tool_ids or [],
        "final_message_pattern": final_message_pattern,
        "response_plan_pattern": response_plan_pattern,
        "state_change_key_patterns": state_change_key_patterns or [],
        "state_change_metadata_keys": state_change_metadata_keys or [],
        "lifecycle_stage_pattern": lifecycle_stage_pattern,
        "uses_price_signal": uses_price_signal,
    }


def _merge_tool_aliases(raw: Any, extra: dict[str, list[str]]) -> dict[str, list[str]]:
    merged: dict[str, list[str]] = {}
    if isinstance(raw, dict):
        for key, value in raw.items():
            if isinstance(value, str):
                canonical = value
                merged.setdefault(canonical, []).append(str(key))
                continue
            values = [str(item) for item in _list(value) if str(item).strip()]
            if values:
                merged.setdefault(str(key), []).extend(values)
    for key, values in extra.items():
        merged.setdefault(str(key), []).extend(str(item) for item in values)
    return {key: list(dict.fromkeys(values)) for key, values in merged.items()}


def _list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


__all__ = [
    "CONTRACT_VERSION",
    "SUPPORTED_DOMAINS",
    "TenantDomainContract",
    "TenantDomainContractLoadResult",
    "TenantDomainField",
    "TenantDomainTool",
    "apply_tenant_domain_contract",
    "field_metadata_from_contract",
    "guard_metadata_from_contract",
    "load_tenant_domain_contract",
    "mandatory_tool_rules_from_contract",
    "tenant_domain_trace_metadata",
    "tool_aliases_from_contract",
    "tool_metadata_from_contract",
    "workflow_event_metadata_from_contract",
]
