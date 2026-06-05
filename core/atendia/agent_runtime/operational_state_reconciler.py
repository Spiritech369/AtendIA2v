from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

from atendia.agent_runtime.schemas import FieldUpdate, LifecycleUpdate, TurnContext, TurnOutput


@dataclass
class OperationalStateInput:
    current_fields: dict[str, Any] = field(default_factory=dict)
    attachments_present: bool = False
    quote_snapshot: dict[str, Any] | None = None


@dataclass(frozen=True)
class PlanSignal:
    plan: str
    down_payment: Any
    strength: str
    reason: str


@dataclass(frozen=True)
class OperationalStateConfig:
    fields: dict[str, str] = field(default_factory=dict)
    field_aliases: dict[str, str] = field(default_factory=dict)
    blocked_auto_fields: set[str] = field(default_factory=set)
    seniority: dict[str, Any] = field(default_factory=dict)
    plans: list[dict[str, Any]] = field(default_factory=list)
    product_aliases: dict[str, str] = field(default_factory=dict)
    quote_snapshot: dict[str, Any] = field(default_factory=dict)
    documents: dict[str, Any] = field(default_factory=dict)
    handoff: dict[str, Any] = field(default_factory=dict)
    stages: dict[str, Any] = field(default_factory=dict)


class OperationalStateReconciler:
    """Reconcile operational state from tenant-scoped rules.

    The runtime owns validation and consistency. Tenant-specific commercial
    concepts such as credit plans, product aliases, document stages, or manual
    stages must come from ``operational_state`` rules in the turn context.
    """

    def reconcile(
        self,
        context: TurnContext,
        output: TurnOutput,
        state: OperationalStateInput | None = None,
    ) -> TurnOutput:
        state = state or OperationalStateInput()
        config = _load_config(context)
        visible = _visible_fields(context)
        current = {
            _canonical_key(key, visible, config): value
            for key, value in state.current_fields.items()
        }
        updates: list[FieldUpdate] = []
        changes: dict[str, Any] = {
            "config_source": _config_source(context),
            "field_normalizations": [],
            "field_derivations": [],
            "removed_field_updates": [],
            "plan_lock_reason": None,
        }

        for update in output.field_updates:
            normalized = self._normalize_update(
                update,
                context=context,
                visible=visible,
                config=config,
            )
            if normalized is None:
                changes["removed_field_updates"].append(update.field_key)
                continue
            updates.append(normalized)
            current[normalized.field_key] = normalized.value

        self._infer_message_fields(context, updates, current, visible, config, changes)
        self._derive_plan_down_payment(context, updates, current, visible, config, changes)
        self._apply_quote_snapshot(
            context,
            updates,
            current,
            visible,
            config,
            state.quote_snapshot,
            changes,
        )
        self._default_documents_complete(context, updates, current, visible, config, changes)
        self._derive_documents_complete_from_checklist(
            context,
            updates,
            current,
            visible,
            config,
            changes,
        )
        self._derive_handoff(context, output, updates, current, visible, config, changes)

        lifecycle, stage_reason, skipped_stage_reason = self._resolve_stage(
            context,
            output,
            current=current,
            attachments_present=state.attachments_present,
            config=config,
        )
        trace = dict(output.trace_metadata)
        trace["operational_reconciler_changes"] = changes
        trace["stage_reason"] = stage_reason
        if skipped_stage_reason:
            trace["skipped_stage_reason"] = skipped_stage_reason
        if state.quote_snapshot:
            trace["quote_resolver"] = {
                "status": state.quote_snapshot.get("status") or "ok",
                "source": state.quote_snapshot.get("source") or "operational_state_reconciler",
            }

        return output.model_copy(
            update={
                "field_updates": updates,
                "lifecycle_update": lifecycle,
                "trace_metadata": trace,
            }
        )

    def _normalize_update(
        self,
        update: FieldUpdate,
        *,
        context: TurnContext,
        visible: set[str],
        config: OperationalStateConfig,
    ) -> FieldUpdate | None:
        key = _canonical_key(update.field_key, visible, config)
        if key in config.blocked_auto_fields:
            return None

        seniority_field = config.fields.get("seniority")
        plan_field = config.fields.get("plan")
        down_payment_field = config.fields.get("down_payment")
        documents_complete_field = config.fields.get("documents_complete")

        if key == seniority_field:
            value = _bool_value(update.value)
            if value is None:
                value = _seniority_from_text(context.inbound_text, config)
        elif key == plan_field:
            value = _canonical_plan(update.value, config) or update.value
        elif key == down_payment_field:
            value = _canonical_down_payment(update.value)
        elif key == documents_complete_field:
            value = _bool_value(update.value)
            if value is None:
                value = False
        else:
            value = update.value

        if key not in visible:
            return None
        if value is None and key in {seniority_field, down_payment_field}:
            return None
        return update.model_copy(
            update={
                "field_key": key,
                "value": value,
                "reason": update.reason or "Operational state normalized field value.",
                "evidence": update.evidence or [context.inbound_text],
                "confidence": update.confidence if update.confidence is not None else 0.9,
                "metadata": {**update.metadata, "operational_reconciler": True},
            }
        )

    def _infer_message_fields(
        self,
        context: TurnContext,
        updates: list[FieldUpdate],
        current: dict[str, Any],
        visible: set[str],
        config: OperationalStateConfig,
        changes: dict[str, Any],
    ) -> None:
        seniority_field = config.fields.get("seniority")
        seniority = _seniority_from_text(context.inbound_text, config)
        if seniority is not None and seniority_field in visible:
            _upsert_update(
                updates,
                current,
                FieldUpdate(
                    field_key=seniority_field,
                    value=seniority,
                    reason="Customer stated tenure relevant to tenant rules.",
                    evidence=[context.inbound_text],
                    confidence=0.95,
                    source="customer_message",
                    metadata={"operational_reconciler": True, "derivation": "tenure_text"},
                ),
            )
            changes["field_derivations"].append(seniority_field)

        plan_field = config.fields.get("plan")
        signal = _plan_signal_from_text(context.inbound_text, current, config)
        if signal and plan_field in visible:
            existing_plan = _canonical_plan(current.get(plan_field), config)
            if existing_plan and existing_plan == signal.plan and signal.strength == "weak":
                changes["plan_lock_reason"] = (
                    f"kept {existing_plan}; weak follow-up evidence did not rewrite plan"
                )
            elif existing_plan and existing_plan != signal.plan and signal.strength == "weak":
                changes["plan_lock_reason"] = (
                    f"kept {existing_plan}; ignored weak evidence for "
                    f"{signal.plan}: {signal.reason}"
                )
            else:
                _upsert_update(
                    updates,
                    current,
                    FieldUpdate(
                        field_key=plan_field,
                        value=signal.plan,
                        reason="Customer stated tenant-configured plan signal.",
                        evidence=[context.inbound_text],
                        confidence=0.95 if signal.strength == "strong" else 0.75,
                        source="customer_message",
                        metadata={
                            "operational_reconciler": True,
                            "derivation": "tenant_plan_text",
                            "plan_evidence_strength": signal.strength,
                        },
                    ),
                )
                changes["field_derivations"].append(plan_field)

        product_field = config.fields.get("product")
        product = _product_from_text(context.inbound_text, config)
        if product and product_field in visible:
            _upsert_update(
                updates,
                current,
                FieldUpdate(
                    field_key=product_field,
                    value=product,
                    reason="Customer stated tenant-configured product alias.",
                    evidence=[context.inbound_text],
                    confidence=0.85,
                    source="customer_message",
                    metadata={"operational_reconciler": True, "derivation": "product_alias"},
                ),
            )
            changes["field_derivations"].append(product_field)

    def _derive_plan_down_payment(
        self,
        context: TurnContext,
        updates: list[FieldUpdate],
        current: dict[str, Any],
        visible: set[str],
        config: OperationalStateConfig,
        changes: dict[str, Any],
    ) -> None:
        plan_field = config.fields.get("plan")
        down_payment_field = config.fields.get("down_payment")
        if not plan_field or down_payment_field not in visible:
            return
        plan = _canonical_plan(current.get(plan_field), config)
        if not plan:
            return
        down_payment = _down_payment_for_plan(plan, config)
        if down_payment in (None, ""):
            return
        _upsert_update(
            updates,
            current,
            FieldUpdate(
                field_key=down_payment_field,
                value=down_payment,
                reason="Derived from tenant-configured plan rule.",
                evidence=[str(current.get(plan_field)), context.inbound_text],
                confidence=1.0,
                source="ai_inference",
                metadata={"operational_reconciler": True, "derivation": "plan_to_down_payment"},
            ),
        )
        changes["field_derivations"].append(down_payment_field)

    def _apply_quote_snapshot(
        self,
        context: TurnContext,
        updates: list[FieldUpdate],
        current: dict[str, Any],
        visible: set[str],
        config: OperationalStateConfig,
        quote_snapshot: dict[str, Any] | None,
        changes: dict[str, Any],
    ) -> None:
        if not quote_snapshot or quote_snapshot.get("status") not in {None, "ok"}:
            return
        last_quote_field = config.fields.get("last_quote")
        quote_sent_field = config.fields.get("quote_sent")
        if last_quote_field in visible:
            _upsert_update(
                updates,
                current,
                FieldUpdate(
                    field_key=last_quote_field,
                    value=quote_snapshot,
                    reason="Quote resolver returned a valid snapshot.",
                    evidence=[context.inbound_text],
                    confidence=1.0,
                    source="action",
                    metadata={"operational_reconciler": True, "quote_resolver": True},
                ),
            )
        quote_sent = quote_snapshot.get(
            "quote_sent",
            config.quote_snapshot.get("quote_sent_default", True),
        ) is not False
        if quote_sent_field in visible and quote_sent:
            _upsert_update(
                updates,
                current,
                FieldUpdate(
                    field_key=quote_sent_field,
                    value=True,
                    reason="Quote resolver returned a valid snapshot.",
                    evidence=[context.inbound_text],
                    confidence=1.0,
                    source="action",
                    metadata={"operational_reconciler": True, "quote_resolver": True},
                ),
            )

        for config_name, snapshot_config_key in {
            "product": "product_keys",
            "plan": "plan_keys",
            "down_payment": "down_payment_keys",
        }.items():
            field_key = config.fields.get(config_name)
            if field_key not in visible:
                continue
            value = _first_snapshot_value(
                quote_snapshot,
                config.quote_snapshot.get(snapshot_config_key) or [],
            )
            if value in (None, ""):
                continue
            if config_name in {"plan", "down_payment"} and _present(current.get(field_key)):
                continue
            _upsert_update(
                updates,
                current,
                FieldUpdate(
                    field_key=field_key,
                    value=value,
                    reason="Quote snapshot aligned tenant field.",
                    evidence=[context.inbound_text],
                    confidence=1.0,
                    source="action",
                    metadata={
                        "operational_reconciler": True,
                        "quote_resolver": True,
                        "derivation": "quote_snapshot_field",
                    },
                ),
            )
        changes["field_derivations"].append("QuoteResolver")

    def _default_documents_complete(
        self,
        context: TurnContext,
        updates: list[FieldUpdate],
        current: dict[str, Any],
        visible: set[str],
        config: OperationalStateConfig,
        changes: dict[str, Any],
    ) -> None:
        field_key = config.fields.get("documents_complete")
        if not field_key or field_key not in visible or field_key in current:
            return
        if not config.documents.get("default_complete_when_missing") is False:
            return
        _upsert_update(
            updates,
            current,
            FieldUpdate(
                field_key=field_key,
                value=False,
                reason="Tenant document policy marks missing checklist as incomplete.",
                evidence=[context.inbound_text],
                confidence=1.0,
                source="ai_inference",
                metadata={"operational_reconciler": True, "default": True},
            ),
        )
        changes["field_derivations"].append(f"{field_key}.default_false")

    def _derive_documents_complete_from_checklist(
        self,
        context: TurnContext,
        updates: list[FieldUpdate],
        current: dict[str, Any],
        visible: set[str],
        config: OperationalStateConfig,
        changes: dict[str, Any],
    ) -> None:
        complete_field = config.fields.get("documents_complete")
        checklist_field = config.fields.get("documents_checklist")
        if complete_field not in visible or not checklist_field:
            return
        checklist = _as_checklist(current.get(checklist_field))
        if not checklist:
            return
        accepted = str(config.documents.get("accepted_status") or "accepted")
        complete = all(str(item.get("status")) == accepted for item in checklist)
        _upsert_update(
            updates,
            current,
            FieldUpdate(
                field_key=complete_field,
                value=complete,
                reason="Derived from tenant document checklist status.",
                evidence=[context.inbound_text],
                confidence=1.0,
                source="ai_inference",
                metadata={"operational_reconciler": True, "derivation": "docs_checklist"},
            ),
        )
        changes["field_derivations"].append(f"{complete_field}.from_checklist")

    def _derive_handoff(
        self,
        context: TurnContext,
        output: TurnOutput,
        updates: list[FieldUpdate],
        current: dict[str, Any],
        visible: set[str],
        config: OperationalStateConfig,
        changes: dict[str, Any],
    ) -> None:
        field_key = config.fields.get("handoff")
        if field_key not in visible:
            return
        has_assign = any(action.name == "assign_conversation" for action in output.actions)
        folded_text = _fold(context.inbound_text)
        positive_phrases = _folded_list(config.handoff.get("positive_phrases"))
        paid_change = all(
            _phrase_in_text(phrase, folded_text)
            for phrase in _folded_list(config.handoff.get("paid_change_all_phrases"))
        )
        risk_phrases = any(
            _phrase_in_text(phrase, folded_text)
            for phrase in _folded_list(config.handoff.get("risk_phrases"))
        )
        docs_complete_field = config.fields.get("documents_complete")
        should_handoff = (
            has_assign
            or any(_phrase_in_text(phrase, folded_text) for phrase in positive_phrases)
            or (paid_change if config.handoff.get("paid_change_all_phrases") else False)
            or risk_phrases
            or current.get(docs_complete_field) is True
        )
        if should_handoff:
            _upsert_update(
                updates,
                current,
                FieldUpdate(
                    field_key=field_key,
                    value=True,
                    reason="Tenant handoff policy matched.",
                    evidence=[context.inbound_text],
                    confidence=1.0,
                    source="ai_inference",
                    metadata={"operational_reconciler": True, "derivation": "handoff_rule"},
                ),
            )
            changes["field_derivations"].append(field_key)
        elif config.handoff.get("default_false_when_missing") and field_key not in current:
            _upsert_update(
                updates,
                current,
                FieldUpdate(
                    field_key=field_key,
                    value=False,
                    reason="No tenant handoff trigger matched.",
                    evidence=[context.inbound_text],
                    confidence=1.0,
                    source="ai_inference",
                    metadata={"operational_reconciler": True, "derivation": "handoff_rule"},
                ),
            )
            changes["field_derivations"].append(f"{field_key}.default_false")

    def _resolve_stage(
        self,
        context: TurnContext,
        output: TurnOutput,
        *,
        current: dict[str, Any],
        attachments_present: bool,
        config: OperationalStateConfig,
    ) -> tuple[LifecycleUpdate | None, str | None, str | None]:
        allowed = _allowed_stages(context)
        existing = output.lifecycle_update
        existing_stage = existing.target_stage if existing else None
        manual = {str(item) for item in _list(config.stages.get("manual"))}
        if existing_stage in manual:
            return None, None, f"manual stage {existing_stage} refused"

        docs_incomplete_stage = _optional_str(config.stages.get("documents_incomplete"))
        if (
            existing_stage == docs_incomplete_stage
            and config.stages.get("documents_incomplete_requires_attachment", True)
            and not attachments_present
        ):
            return None, None, "document progress requires attachment"

        target: str | None = None
        reason: str | None = None
        seniority_field = config.fields.get("seniority")
        docs_complete_field = config.fields.get("documents_complete")
        checklist_field = config.fields.get("documents_checklist")
        plan_field = config.fields.get("plan")
        down_payment_field = config.fields.get("down_payment")
        product_field = config.fields.get("product")
        quote_sent_field = config.fields.get("quote_sent")

        if seniority_field and current.get(seniority_field) is False:
            target = _optional_str(config.stages.get("seniority_failed"))
            reason = f"{seniority_field}=false"
        elif docs_complete_field and current.get(docs_complete_field) is True:
            target = _optional_str(config.stages.get("documents_complete"))
            reason = f"{docs_complete_field}=true"
        elif checklist_field and _has_document_progress(current, checklist_field, config):
            if attachments_present:
                target = docs_incomplete_stage
                reason = "document progress with incomplete checklist"
            else:
                lifecycle = existing if existing_stage != docs_incomplete_stage else None
                return lifecycle, None, "document progress requires attachment"
        elif (
            _present(current.get(plan_field))
            and _present(current.get(down_payment_field))
            and _present(current.get(product_field))
            and _truthy(current.get(quote_sent_field))
        ):
            target = _optional_str(config.stages.get("quote_ready"))
            reason = "plan, down payment, product and quote snapshot present"
        elif _present(current.get(plan_field)) and _present(current.get(down_payment_field)):
            target = _optional_str(config.stages.get("plan_ready"))
            reason = "plan and down payment present"

        if target in manual:
            return None, None, f"manual stage {target} refused"
        if not target or target not in allowed:
            return existing, None, f"stage {target!r} not allowed or no transition"
        return (
            LifecycleUpdate(
                target_stage=target,
                reason=reason or "Operational state transition.",
                evidence=[context.inbound_text],
                confidence=1.0,
                source="agent",
                metadata={"operational_reconciler": True},
            ),
            reason,
            None,
        )


def _load_config(context: TurnContext) -> OperationalStateConfig:
    raw = _raw_operational_config(context)
    fields = _dict(raw.get("fields"))
    return OperationalStateConfig(
        fields={str(key): str(value) for key, value in fields.items() if str(value)},
        field_aliases={
            _fold(str(key)): str(value)
            for key, value in _dict(raw.get("field_aliases")).items()
            if str(value)
        },
        blocked_auto_fields={str(item) for item in _list(raw.get("blocked_auto_fields"))},
        seniority=_dict(raw.get("seniority")),
        plans=[item for item in _list(raw.get("plans")) if isinstance(item, dict)],
        product_aliases={
            _fold(str(key)): str(value)
            for key, value in _dict(raw.get("product_aliases")).items()
            if str(value)
        },
        quote_snapshot=_dict(raw.get("quote_snapshot")),
        documents=_dict(raw.get("documents")),
        handoff=_dict(raw.get("handoff")),
        stages=_dict(raw.get("stages")),
    )


def _raw_operational_config(context: TurnContext) -> dict[str, Any]:
    tenant_rules = context.tenant_config.ruleset
    for raw in (
        tenant_rules.get("operational_state"),
        context.metadata.get("operational_state_config"),
        _dict(context.metadata.get("tenant_config")).get("operational_state"),
        _dict(_dict(context.metadata.get("tenant_config")).get("ruleset")).get(
            "operational_state"
        ),
        _dict(context.metadata.get("structured_reliability")).get("operational_state"),
    ):
        if isinstance(raw, dict):
            return raw
    return {}


def _config_source(context: TurnContext) -> str:
    return "tenant_ruleset" if _raw_operational_config(context) else "empty"


def _upsert_update(
    updates: list[FieldUpdate],
    current: dict[str, Any],
    update: FieldUpdate,
) -> None:
    updates[:] = [item for item in updates if item.field_key != update.field_key]
    updates.append(update)
    current[update.field_key] = update.value


def _visible_fields(context: TurnContext) -> set[str]:
    if context.active_agent and context.active_agent.visible_contact_field_keys is not None:
        return set(context.active_agent.visible_contact_field_keys)
    return {field.key for field in context.contact_fields}


def _allowed_stages(context: TurnContext) -> set[str]:
    if context.active_agent and context.active_agent.allowed_lifecycle_stage_ids is not None:
        return set(context.active_agent.allowed_lifecycle_stage_ids)
    return set()


def _canonical_key(key: Any, visible: set[str], config: OperationalStateConfig) -> str:
    raw = str(key)
    folded = _fold(raw)
    for candidate in visible:
        if _fold(candidate) == folded:
            return candidate
    return config.field_aliases.get(folded, raw)


def _bool_value(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, dict):
        for key in ("value", "true", "false"):
            if key in value:
                nested = value[key]
                if key == "true" and nested is True:
                    return True
                if key == "false" and nested is True:
                    return False
                parsed = _bool_value(nested)
                if parsed is not None:
                    return parsed
        return None
    raw = _fold(str(value))
    if raw in {"true", "si", "yes"}:
        return True
    if raw in {"false", "no"}:
        return False
    return None


def _seniority_from_text(text: str, config: OperationalStateConfig) -> bool | None:
    if not config.seniority:
        return None
    folded = _fold(text)
    if any(
        _phrase_in_text(phrase, folded)
        for phrase in _folded_list(config.seniority.get("negative_phrases"))
    ):
        return False
    pattern = str(
        config.seniority.get("duration_regex")
        or r"(\d+)\s*(mes|meses|ano|anos|año|años)"
    )
    match = re.search(pattern, folded)
    if not match:
        return None
    amount = int(match.group(1))
    unit = match.group(2)
    year_units = {_fold(str(item)) for item in _list(config.seniority.get("year_units"))}
    if not year_units:
        year_units = {"ano", "anos"}
    months = amount * 12 if _fold(unit) in year_units else amount
    minimum = int(config.seniority.get("minimum_months") or 0)
    return months >= minimum


def _plan_signal_from_text(
    text: str,
    current: dict[str, Any],
    config: OperationalStateConfig,
) -> PlanSignal | None:
    folded = _fold(text)
    plan_field = config.fields.get("plan")
    existing = _canonical_plan(current.get(plan_field), config)
    weak_matches: list[PlanSignal] = []
    for plan in config.plans:
        value = str(plan.get("value") or plan.get("label") or "").strip()
        if not value:
            continue
        for alias in _folded_list(plan.get("aliases")):
            if _phrase_in_text(alias, folded):
                return PlanSignal(value, plan.get("down_payment"), "strong", alias)
    for plan in config.plans:
        value = str(plan.get("value") or plan.get("label") or "").strip()
        if not value:
            continue
        weak_aliases = _folded_list(plan.get("weak_aliases"))
        for alias in weak_aliases:
            if _phrase_in_text(alias, folded):
                weak_matches.append(PlanSignal(value, plan.get("down_payment"), "weak", alias))
    if existing:
        for match in weak_matches:
            if match.plan == existing:
                return match
    return weak_matches[0] if weak_matches else None


def _product_from_text(text: str, config: OperationalStateConfig) -> str | None:
    folded = _fold(text)
    for alias, value in config.product_aliases.items():
        if _phrase_in_text(alias, folded):
            return value
    return None


def _canonical_plan(value: Any, config: OperationalStateConfig) -> str | None:
    folded = _fold(str(value or ""))
    if not folded:
        return None
    for plan in config.plans:
        canonical = str(plan.get("value") or plan.get("label") or "").strip()
        if not canonical:
            continue
        aliases = {_fold(canonical), *_folded_list(plan.get("aliases")), *_folded_list(plan.get("weak_aliases"))}
        if folded in aliases:
            return canonical
    return None


def _down_payment_for_plan(value: str, config: OperationalStateConfig) -> Any:
    folded = _fold(value)
    for plan in config.plans:
        canonical = str(plan.get("value") or plan.get("label") or "").strip()
        if _fold(canonical) == folded:
            return plan.get("down_payment")
    return None


def _canonical_down_payment(value: Any) -> Any:
    raw = str(value or "").strip()
    if not raw:
        return None
    match = re.search(r"(\d+(?:\.\d+)?)\s*%?", raw)
    return f"{match.group(1)}%" if match else raw


def _first_snapshot_value(snapshot: dict[str, Any], keys: list[Any]) -> Any:
    for key in keys:
        value = snapshot.get(str(key))
        if value not in (None, ""):
            return value
    return None


def _as_checklist(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return []
        return _as_checklist(parsed)
    return []


def _has_document_progress(
    current: dict[str, Any],
    checklist_field: str,
    config: OperationalStateConfig,
) -> bool:
    checklist = _as_checklist(current.get(checklist_field))
    progress_statuses = {
        str(item) for item in _list(config.documents.get("progress_statuses"))
    }
    if not progress_statuses:
        return False
    return any(str(item.get("status")) in progress_statuses for item in checklist)


def _truthy(value: Any) -> bool:
    parsed = _bool_value(value)
    if parsed is not None:
        return parsed
    return str(value).strip().casefold() in {"1", "ok", "sent", "enviada"}


def _present(value: Any) -> bool:
    return value not in (None, "", False)


def _phrase_in_text(phrase: str, folded_text: str) -> bool:
    return bool(phrase) and phrase in folded_text


def _folded_list(value: Any) -> list[str]:
    return [_fold(str(item)) for item in _list(value) if str(item).strip()]


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _optional_str(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value)


def _fold(text: str) -> str:
    normalized = unicodedata.normalize("NFD", text.casefold())
    folded = "".join(char for char in normalized if unicodedata.category(char) != "Mn")
    return re.sub(r"[^a-z0-9%]+", " ", folded).strip()
