from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from atendia.agent_runtime.canonical import (
    QuoteSnapshot,
    coerce_canonical_product_ref,
    coerce_quote_snapshot,
)
from atendia.agent_runtime.schemas import (
    AdvisorBrainDecision,
    AdvisorBrainStateChange,
    FieldUpdate,
    LifecycleUpdate,
    TurnContext,
)


@dataclass(frozen=True)
class StateWriteResult:
    field_updates: list[FieldUpdate] = field(default_factory=list)
    lifecycle_update: LifecycleUpdate | None = None
    accepted: list[dict[str, Any]] = field(default_factory=list)
    blocked: list[dict[str, Any]] = field(default_factory=list)
    needs_review: list[dict[str, Any]] = field(default_factory=list)
    decisions: list[dict[str, Any]] = field(default_factory=list)
    invalidated_fields: list[dict[str, Any]] = field(default_factory=list)

    @property
    def summary(self) -> dict[str, Any]:
        return {
            "accepted_count": len(self.accepted),
            "blocked_count": len(self.blocked),
            "needs_review_count": len(self.needs_review),
            "invalidated_count": len(self.invalidated_fields),
        }


class DeterministicStateWriter:
    """Validate Advisor Brain state proposals before persistence.

    This class does not touch the database. It converts validated proposals into
    runtime updates that downstream persistence can apply. Product and quote
    writes are intentionally stricter than generic fields so free-text product
    names cannot become canonical state.
    """

    def build_updates(
        self,
        *,
        context: TurnContext,
        decision: AdvisorBrainDecision,
        tool_results: list[Any] | None = None,
    ) -> StateWriteResult:
        tool_results = list(tool_results or [])
        allowed_fields = _visible_fields(context)
        field_metadata = _field_metadata(context)
        alias_map = _field_aliases(field_metadata)
        declarative_field_keys = set(field_metadata)
        product_fields = _configured_field_names(context, "product_fields")
        quote_fields = _configured_field_names(context, "quote_snapshot_fields")
        plan_fields = _configured_field_names(context, "plan_fields")
        income_fields = _configured_field_names(context, "income_fields")
        document_fields = _configured_field_names(context, "document_fields")
        product_fields.update(_fields_by_role(field_metadata, "selection"))
        quote_fields.update(_fields_by_role(field_metadata, "quote"))
        plan_fields.update(_fields_by_role(field_metadata, "plan"))
        document_fields.update(_fields_by_role(field_metadata, "document"))
        if not product_fields:
            product_field = _configured_single_field(context, "product")
            if product_field:
                product_fields.add(product_field)
        if not quote_fields:
            quote_field = _configured_single_field(context, "last_quote")
            if quote_field:
                quote_fields.add(quote_field)
        if not plan_fields:
            plan_field = _configured_single_field(context, "plan")
            if plan_field:
                plan_fields.add(plan_field)
            credit_plan_field = _configured_single_field(context, "credit_plan")
            if credit_plan_field:
                plan_fields.add(credit_plan_field)
        if not income_fields:
            income_field = _configured_single_field(context, "income")
            if income_field:
                income_fields.add(income_field)
        if not document_fields:
            document_fields.update(_configured_document_fields(context))
        quote_sent_field = _configured_single_field(context, "quote_sent")

        field_updates: list[FieldUpdate] = []
        lifecycle_update: LifecycleUpdate | None = None
        accepted: list[dict[str, Any]] = []
        blocked: list[dict[str, Any]] = []
        needs_review: list[dict[str, Any]] = []
        decisions: list[dict[str, Any]] = []
        invalidated_fields: list[dict[str, Any]] = []

        for change in decision.proposed_state_changes:
            if change.target == "none":
                continue
            if change.target == "contact_field":
                canonical_key = _canonical_field_key(change.key, field_metadata, alias_map)
                canonical_change = change.model_copy(update={"key": canonical_key})
                if context.tenant_config.safe_mode:
                    decision_payload = _decision_payload(
                        canonical_change,
                        decision="blocked",
                        reason="safe_mode_blocks_field_write",
                        source="model_proposed",
                    )
                    blocked.append(decision_payload)
                    decisions.append(decision_payload)
                    continue
                if field_metadata and canonical_key not in declarative_field_keys:
                    decision_payload = _decision_payload(
                        canonical_change,
                        decision="blocked",
                        reason="field_not_declared_in_tenant_contract",
                        source="model_proposed",
                    )
                    blocked.append(decision_payload)
                    decisions.append(decision_payload)
                    continue
                if canonical_key in declarative_field_keys:
                    outcome = self._field_update_from_policy(
                        context=context,
                        change=canonical_change,
                        metadata=field_metadata[canonical_key],
                        allowed_fields=allowed_fields,
                        tool_results=tool_results,
                    )
                    decisions.append(outcome["decision"])
                    if outcome["status"] == "accepted" and outcome["update"] is not None:
                        update = outcome["update"]
                        field_updates.append(update)
                        accepted.append(outcome["decision"])
                        derived_updates = _derived_updates_for_declarative_change(
                            context=context,
                            update=update,
                            field_metadata=field_metadata,
                            allowed_fields=allowed_fields,
                        )
                        field_updates.extend(
                            derived_update for derived_update, _ in derived_updates
                        )
                        accepted.extend(
                            derived_decision for _, derived_decision in derived_updates
                        )
                        decisions.extend(
                            derived_decision for _, derived_decision in derived_updates
                        )
                        invalidations = _quote_invalidations_for_declarative_change(
                            context=context,
                            changed_field=update.field_key,
                            new_value=update.value,
                            field_metadata=field_metadata,
                            quote_fields=quote_fields,
                            allowed_fields=allowed_fields,
                        )
                        field_updates.extend(invalidations)
                        invalidated_fields.extend(
                            [
                                _invalidation_decision(
                                    invalidation,
                                    changed_field=update.field_key,
                                )
                                for invalidation in invalidations
                            ]
                        )
                        continue
                    if outcome["status"] == "needs_review":
                        needs_review.append(outcome["decision"])
                        continue
                    blocked.append(outcome["decision"])
                    continue
                if canonical_key in quote_fields:
                    payload = _blocked(canonical_change, "quote_snapshot_requires_quote_resolver")
                    blocked.append(payload)
                    decisions.append(payload)
                    continue
                if canonical_key == quote_sent_field and change.value is True:
                    payload = _blocked(
                        canonical_change,
                        "quote_sent_requires_quote_safety_guard",
                    )
                    blocked.append(payload)
                    decisions.append(payload)
                    continue
                blocked_before = len(blocked)
                update = self._field_update_from_change(
                    context=context,
                    change=canonical_change,
                    allowed_fields=allowed_fields,
                    product_fields=product_fields,
                    quote_fields=quote_fields,
                    document_fields=document_fields,
                    blocked=blocked,
                )
                if update is None:
                    if len(blocked) == blocked_before:
                        payload = _blocked(
                            canonical_change,
                            "invalid_or_unsafe_field_update",
                        )
                        blocked.append(payload)
                        decisions.append(payload)
                    continue
                field_updates.append(update)
                payload = _accepted(canonical_change)
                accepted.append(payload)
                decisions.append(payload)
                if update.field_key in product_fields:
                    invalidations = _quote_invalidations_for_product_change(
                        context=context,
                        product_value=update.value,
                        quote_field=next(iter(sorted(quote_fields)), None),
                        quote_sent_field=quote_sent_field,
                        allowed_fields=allowed_fields,
                    )
                    field_updates.extend(invalidations)
                    invalidated_fields.extend(
                        [
                            _invalidation_decision(invalidation, changed_field=update.field_key)
                            for invalidation in invalidations
                        ]
                    )
                if update.field_key in plan_fields or update.field_key in income_fields:
                    invalidations = _quote_invalidations_for_plan_change(
                        context=context,
                        changed_field=update.field_key,
                        new_value=update.value,
                        quote_field=next(iter(sorted(quote_fields)), None),
                        quote_sent_field=quote_sent_field,
                        allowed_fields=allowed_fields,
                    )
                    field_updates.extend(invalidations)
                    invalidated_fields.extend(
                        [
                            _invalidation_decision(invalidation, changed_field=update.field_key)
                            for invalidation in invalidations
                        ]
                    )
                continue
            if change.target == "lifecycle":
                if _is_blocked_document_lifecycle_change(context, change):
                    payload = _blocked(
                        change,
                        "document_stage_requires_attachment_or_checklist",
                    )
                    blocked.append(payload)
                    decisions.append(payload)
                    continue
                lifecycle = self._lifecycle_update_from_change(context=context, change=change)
                if lifecycle is None:
                    payload = _blocked(change, "invalid_lifecycle_update")
                    blocked.append(payload)
                    decisions.append(payload)
                    continue
                lifecycle_update = lifecycle
                payload = _accepted(change)
                accepted.append(payload)
                decisions.append(payload)
                continue
            if change.target == "memory":
                payload = _blocked(change, "memory_writes_require_memory_service")
                blocked.append(payload)
                decisions.append(payload)

        tool_result_updates = _field_updates_from_tool_results(
            context=context,
            tool_results=tool_results,
            field_metadata=field_metadata,
            allowed_fields=allowed_fields,
        )
        for update, decision_payload in tool_result_updates:
            field_updates.append(update)
            accepted.append(decision_payload)
            decisions.append(decision_payload)

        for result in tool_results:
            if not _trusted_quote_resolver_result(result, context=context):
                continue
            snapshot = _validated_quote_snapshot(_tool_result_value(result, "quote_snapshot"))
            if snapshot is None:
                payload = {
                    "target": "contact_field",
                    "key": next(iter(sorted(quote_fields)), None),
                    "field": next(iter(sorted(quote_fields)), None),
                    "decision": "blocked",
                    "source": "tool_result",
                    "writer": "StateWriter",
                    "reason": "invalid_quote_snapshot",
                    "evidence_refs": [],
                }
                blocked.append(payload)
                decisions.append(payload)
                continue
            product_field = next(iter(sorted(product_fields)), None)
            if (
                product_field
                and product_field not in declarative_field_keys
                and (not allowed_fields or product_field in allowed_fields)
            ):
                field_updates.append(
                    FieldUpdate(
                        field_key=product_field,
                        value=snapshot.product.model_dump(mode="json"),
                        reason="QuoteResolver returned canonical product inside QuoteSnapshot.",
                        evidence=list(snapshot.evidence) or [context.inbound_text],
                        confidence=1.0,
                        source="action",
                        metadata={
                            "state_writer": "deterministic",
                            "tool_result": True,
                            "canonical_product_ref": True,
                            "quote_snapshot_product": True,
                        },
                    )
                )
                accepted.append(
                    {
                        "target": "contact_field",
                        "key": product_field,
                        "field": product_field,
                        "decision": "accepted",
                        "source": "tool_result",
                        "writer": "StateWriter",
                        "reason": "quote_resolver_returned_canonical_product",
                        "evidence_refs": _tool_evidence_refs([result]),
                        "confidence": 1.0,
                    }
                )
                decisions.append(accepted[-1])
            quote_field = next(iter(sorted(quote_fields)), None)
            if (
                quote_field
                and quote_field not in declarative_field_keys
                and (not allowed_fields or quote_field in allowed_fields)
            ):
                field_updates.append(
                    FieldUpdate(
                        field_key=quote_field,
                        value=snapshot.with_integrity_hash().model_dump(mode="json"),
                        reason="QuoteResolver returned a valid immutable QuoteSnapshot.",
                        evidence=list(snapshot.evidence) or [context.inbound_text],
                        confidence=1.0,
                        source="action",
                        metadata={
                            "state_writer": "deterministic",
                            "tool_result": True,
                            "quote_snapshot": True,
                            "quote_snapshot_id": snapshot.snapshot_id,
                            "quote_snapshot_hash": snapshot.with_integrity_hash().integrity_hash,
                            "source_tool": snapshot.source_tool,
                        },
                    )
                )
                accepted.append(
                    {
                        "target": "contact_field",
                        "key": quote_field,
                        "field": quote_field,
                        "decision": "accepted",
                        "source": "tool_result",
                        "writer": "StateWriter",
                        "reason": "quote_resolver_returned_valid_quote_snapshot",
                        "evidence_refs": _tool_evidence_refs([result]),
                        "confidence": 1.0,
                    }
                )
                decisions.append(accepted[-1])
            elif quote_field:
                payload = {
                    "target": "contact_field",
                    "key": quote_field,
                    "field": quote_field,
                    "decision": "blocked",
                    "source": "tool_result",
                    "writer": "StateWriter",
                    "reason": "field_not_visible",
                    "evidence_refs": _tool_evidence_refs([result]),
                }
                blocked.append(payload)
                decisions.append(payload)
        return StateWriteResult(
            field_updates=field_updates,
            lifecycle_update=lifecycle_update,
            accepted=accepted,
            blocked=blocked,
            needs_review=needs_review,
            decisions=decisions,
            invalidated_fields=invalidated_fields,
        )

    def _field_update_from_policy(
        self,
        *,
        context: TurnContext,
        change: AdvisorBrainStateChange,
        metadata: dict[str, Any],
        allowed_fields: set[str],
        tool_results: list[Any],
    ) -> dict[str, Any]:
        key = change.key or ""
        policy = str(metadata.get("write_policy") or "auto_apply")
        source = _proposal_source(change)
        confidence = change.confidence if change.confidence is not None else 0.8
        evidence_refs = _evidence_refs(context, change, tool_results=tool_results)
        if not key or (allowed_fields and key not in allowed_fields):
            decision = _decision_payload(
                change,
                decision="blocked",
                reason="field_not_visible",
                source=source,
                evidence_refs=evidence_refs,
                confidence=confidence,
            )
            return {"status": "blocked", "update": None, "decision": decision}

        if policy in {"tool_only", "blocked_from_model", "system_derived"}:
            reason = {
                "tool_only": "field_is_tool_only",
                "blocked_from_model": "field_is_blocked_from_model",
                "system_derived": "field_is_system_derived",
            }[policy]
            decision = _decision_payload(
                change,
                decision="blocked",
                reason=reason,
                source="model_proposed",
                evidence_refs=evidence_refs,
                confidence=confidence,
            )
            return {"status": "blocked", "update": None, "decision": decision}

        if policy == "suggest_review":
            decision = _decision_payload(
                change,
                decision="needs_review",
                reason="field_policy_requires_review",
                source=source,
                evidence_refs=evidence_refs,
                confidence=confidence,
            )
            return {"status": "needs_review", "update": None, "decision": decision}

        reason = _policy_block_reason(
            context=context,
            change=change,
            metadata=metadata,
            policy=policy,
            source=source,
            tool_results=tool_results,
        )
        if reason is not None:
            decision = _decision_payload(
                change,
                decision="blocked",
                reason=reason,
                source=source,
                evidence_refs=evidence_refs,
                confidence=confidence,
            )
            return {"status": "blocked", "update": None, "decision": decision}

        if (
            policy == "auto_apply_when_catalog_match"
            and str(metadata.get("domain_role") or "") == "selection"
            and coerce_canonical_product_ref(change.value) is None
            and not _catalog_tool_validates_selection(context, tool_results, change.value)
        ):
            decision = _decision_payload(
                change,
                decision="blocked",
                reason="catalog_tool_result_must_write_canonical_selection",
                source=source,
                evidence_refs=evidence_refs,
                confidence=confidence,
            )
            return {"status": "blocked", "update": None, "decision": decision}

        value, update_metadata = _value_for_declarative_update(change.value, metadata)
        update = FieldUpdate(
            field_key=key,
            value=value,
            reason=change.reason or f"Accepted by field policy {policy}.",
            evidence=list(change.evidence) or [context.inbound_text],
            confidence=confidence,
            source=_field_update_source(source),
            metadata={
                **dict(change.metadata),
                **update_metadata,
                "state_writer": "declarative",
                "advisor_proposed": True,
                "write_policy": policy,
                "source": source,
                "writer": "StateWriter",
            },
        )
        decision = _decision_payload(
            change,
            decision="accepted",
            reason=f"field_policy_{policy}_accepted",
            source=source,
            evidence_refs=evidence_refs,
            confidence=confidence,
        )
        return {"status": "accepted", "update": update, "decision": decision}

    def _field_update_from_change(
        self,
        *,
        context: TurnContext,
        change: AdvisorBrainStateChange,
        allowed_fields: set[str],
        product_fields: set[str],
        quote_fields: set[str],
        document_fields: set[str],
        blocked: list[dict[str, Any]],
    ) -> FieldUpdate | None:
        key = change.key or ""
        if not key or (allowed_fields and key not in allowed_fields):
            return None
        if key in product_fields:
            ref = coerce_canonical_product_ref(change.value)
            if ref is None or not ref.display_name:
                return None
            value: Any = ref.model_dump(mode="json")
            metadata = {"canonical_product_ref": True, **change.metadata}
        elif key in quote_fields:
            snapshot = coerce_quote_snapshot(change.value)
            if snapshot is None:
                return None
            value = snapshot.with_integrity_hash().model_dump(mode="json")
            metadata = {"quote_snapshot": True, **change.metadata}
        else:
            if key in document_fields and not _document_update_has_evidence(context, change):
                blocked.append(_blocked(change, "document_update_requires_attachment_or_checklist"))
                return None
            value = change.value
            metadata = dict(change.metadata)
        if not (change.reason or change.evidence):
            return None
        return FieldUpdate(
            field_key=key,
            value=value,
            reason=change.reason,
            evidence=list(change.evidence) or [context.inbound_text],
            confidence=change.confidence if change.confidence is not None else 0.8,
            source="ai_inference",
            metadata={
                **metadata,
                "state_writer": "deterministic",
                "advisor_proposed": True,
            },
        )

    def _lifecycle_update_from_change(
        self,
        *,
        context: TurnContext,
        change: AdvisorBrainStateChange,
    ) -> LifecycleUpdate | None:
        del context
        target_stage = change.key or _stage_from_value(change.value)
        if not target_stage:
            return None
        if not (change.reason or change.evidence):
            return None
        return LifecycleUpdate(
            target_stage=target_stage,
            reason=change.reason,
            evidence=list(change.evidence),
            confidence=change.confidence if change.confidence is not None else 0.8,
            source="agent",
            metadata={
                **change.metadata,
                "state_writer": "deterministic",
                "advisor_proposed": True,
            },
        )


def _field_metadata(context: TurnContext) -> dict[str, dict[str, Any]]:
    return {
        str(key): dict(value)
        for key, value in context.tenant_config.field_metadata.items()
        if isinstance(value, dict)
    }


def _field_aliases(field_metadata: dict[str, dict[str, Any]]) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for key, metadata in field_metadata.items():
        aliases[_field_token(key)] = key
        for alias in _list(metadata.get("aliases")):
            aliases[_field_token(alias)] = key
    return aliases


def _canonical_field_key(
    key: str | None,
    field_metadata: dict[str, dict[str, Any]],
    alias_map: dict[str, str],
) -> str | None:
    if key is None:
        return None
    raw = str(key)
    if raw in field_metadata:
        return raw
    return alias_map.get(_field_token(raw), raw)


def _fields_by_role(field_metadata: dict[str, dict[str, Any]], role: str) -> set[str]:
    return {
        key
        for key, metadata in field_metadata.items()
        if str(metadata.get("domain_role") or "").casefold() == role
    }


def _proposal_source(change: AdvisorBrainStateChange) -> str:
    source = str(change.metadata.get("source") or change.metadata.get("source_tool") or "")
    if source:
        return source
    if change.evidence:
        return "user_message"
    return "model_proposed"


def _field_update_source(source: str) -> str:
    if source in {"user_message", "customer_message"}:
        return "customer_message"
    if source in {"human", "human_review"}:
        return "human"
    if source in {"workflow"}:
        return "workflow"
    if source in {"vision"}:
        return "vision"
    if source not in {"model_proposed", "ai_inference"}:
        return "action"
    return "ai_inference"


def _policy_block_reason(
    *,
    context: TurnContext,
    change: AdvisorBrainStateChange,
    metadata: dict[str, Any],
    policy: str,
    source: str,
    tool_results: list[Any],
) -> str | None:
    allowed_sources = [str(item) for item in _list(metadata.get("allowed_sources"))]
    if allowed_sources and not _source_allowed(source, allowed_sources):
        return "source_not_allowed_by_field_policy"
    evidence_required = bool(metadata.get("evidence_required"))
    if evidence_required and not _has_required_evidence(
        context,
        change,
        source=source,
        allowed_sources=allowed_sources,
        tool_results=tool_results,
    ):
        return "field_policy_requires_evidence"
    if policy == "auto_apply_when_explicit" and not _is_explicit_user_evidence(context, change):
        return "field_policy_requires_explicit_user_evidence"
    if policy == "auto_apply_when_catalog_match" and not _has_trusted_tool(
        context,
        tool_results,
        "catalog.search",
    ):
        return "catalog_match_required"
    if policy == "auto_apply_when_valid_plan" and not _has_valid_plan_evidence(
        context,
        change,
        metadata,
        tool_results,
    ):
        return "valid_plan_evidence_required"
    if policy == "attachment_required" and not _has_attachment_or_human_evidence(
        context,
        tool_results,
    ):
        return "attachment_or_human_evidence_required"
    return None


def _source_allowed(source: str, allowed_sources: list[str]) -> bool:
    if source in allowed_sources:
        return True
    if source == "customer_message" and "user_message" in allowed_sources:
        return True
    if source == "user_message" and "customer_message" in allowed_sources:
        return True
    return False


def _has_required_evidence(
    context: TurnContext,
    change: AdvisorBrainStateChange,
    *,
    source: str,
    allowed_sources: list[str],
    tool_results: list[Any],
) -> bool:
    if change.evidence or change.reason:
        return True
    if source in {"human", "human_review", "system"}:
        return True
    if _has_document_attachment(context):
        return True
    return any(_has_trusted_tool(context, tool_results, item) for item in allowed_sources)


def _is_explicit_user_evidence(context: TurnContext, change: AdvisorBrainStateChange) -> bool:
    if change.metadata.get("explicit") is True:
        return True
    evidence_text = " ".join(str(item) for item in change.evidence)
    inbound = str(context.inbound_text or "")
    if evidence_text and (evidence_text in inbound or inbound in evidence_text):
        return True
    value = str(change.value or "").strip()
    return bool(value and value.casefold() in inbound.casefold())


def _has_valid_plan_evidence(
    context: TurnContext,
    change: AdvisorBrainStateChange,
    metadata: dict[str, Any],
    tool_results: list[Any],
) -> bool:
    if _has_trusted_tool(context, tool_results, "credit_plan.resolve"):
        return True
    if _has_trusted_tool(context, tool_results, "plan.resolve"):
        return True
    if _has_trusted_tool(context, tool_results, "requirements.lookup"):
        return True
    allowed_values = {
        str(item).casefold()
        for item in (
            _list(metadata.get("allowed_values"))
            or _list(metadata.get("options"))
            or _list(metadata.get("enum"))
        )
        if str(item).strip()
    }
    value = str(change.value or "").casefold()
    return bool(
        allowed_values
        and value in allowed_values
        and _is_explicit_user_evidence(context, change)
    )


def _catalog_tool_validates_selection(
    context: TurnContext,
    tool_results: list[Any],
    value: Any,
) -> bool:
    expected = _field_token(value)
    if not expected:
        return False
    for result in tool_results:
        if not _trusted_tool_result(context, result, "catalog.search"):
            continue
        data = getattr(result, "data", None)
        if isinstance(result, dict):
            data = result.get("data")
        if not isinstance(data, dict):
            continue
        ref = coerce_canonical_product_ref(data.get("canonical_product_ref"))
        if ref is not None and _field_token(ref.display_name) == expected:
            return True
        for collection_key in ("items", "matches", "category_matches"):
            for item in _list(data.get(collection_key)):
                if not isinstance(item, dict):
                    continue
                names = [
                    item.get("display_name"),
                    item.get("name"),
                    item.get("modelo"),
                    item.get("modelo_moto"),
                    item.get("sku"),
                ]
                if any(_field_token(name) == expected for name in names):
                    return True
    return False


def _has_attachment_or_human_evidence(
    context: TurnContext,
    tool_results: list[Any],
) -> bool:
    return (
        _has_document_attachment(context)
        or bool(context.metadata.get("human_review"))
        or _has_trusted_tool(context, tool_results, "document.check")
        or _has_trusted_tool(context, tool_results, "vision.document_check")
    )


def _has_trusted_tool(
    context: TurnContext,
    tool_results: list[Any],
    tool_name: str,
) -> bool:
    return any(_trusted_tool_result(context, result, tool_name) for result in tool_results)


def _trusted_tool_result(context: TurnContext, result: Any, tool_name: str | None = None) -> bool:
    result_tool = getattr(result, "tool_name", None)
    status = getattr(result, "status", None)
    data = getattr(result, "data", None)
    trace_metadata = getattr(result, "trace_metadata", None)
    if isinstance(result, dict):
        result_tool = result.get("tool_name") or result.get("name")
        status = result.get("status")
        data = result.get("data")
        trace_metadata = result.get("trace_metadata")
    if tool_name is not None and str(result_tool or "") != tool_name:
        return False
    if str(status or "") != "succeeded":
        return False
    return not _tool_result_has_cross_tenant_data(
        context,
        data if isinstance(data, dict) else {},
        trace_metadata if isinstance(trace_metadata, dict) else {},
    )


def _tool_result_has_cross_tenant_data(
    context: TurnContext,
    data: dict[str, Any],
    trace_metadata: dict[str, Any],
) -> bool:
    tenant_id = str(context.tenant_id)
    ids = _tenant_ids_in_value(data)
    if trace_metadata.get("tenant_id") is not None:
        ids.append(str(trace_metadata["tenant_id"]))
    return any(item and item != tenant_id for item in ids)


def _tenant_ids_in_value(value: Any) -> list[str]:
    ids: list[str] = []
    if isinstance(value, dict):
        for key, nested in value.items():
            if str(key) in {"tenant_id", "tenantId"} and nested is not None:
                ids.append(str(nested))
            ids.extend(_tenant_ids_in_value(nested))
    elif isinstance(value, list):
        for nested in value:
            ids.extend(_tenant_ids_in_value(nested))
    return ids


def _evidence_refs(
    context: TurnContext,
    change: AdvisorBrainStateChange,
    *,
    tool_results: list[Any],
) -> list[str]:
    refs = [f"user_message:{item}" for item in change.evidence if str(item).strip()]
    refs.extend(_tool_evidence_refs(tool_results))
    if _has_document_attachment(context):
        refs.append("attachment:present")
    if context.metadata.get("human_review"):
        refs.append("human_review:present")
    return list(dict.fromkeys(refs))


def _tool_evidence_refs(tool_results: list[Any]) -> list[str]:
    refs: list[str] = []
    for result in tool_results:
        tool_name = getattr(result, "tool_name", None)
        status = getattr(result, "status", None)
        if isinstance(result, dict):
            tool_name = result.get("tool_name") or result.get("name")
            status = result.get("status")
        if tool_name and str(status or "") == "succeeded":
            refs.append(f"tool_result:{tool_name}")
    return refs


def _value_for_declarative_update(
    value: Any,
    metadata: dict[str, Any],
) -> tuple[Any, dict[str, Any]]:
    if metadata.get("requires_canonical_product_ref"):
        ref = coerce_canonical_product_ref(value)
        if ref is not None:
            return ref.model_dump(mode="json"), {"canonical_product_ref": True}
    return value, {}


def _field_updates_from_tool_results(
    *,
    context: TurnContext,
    tool_results: list[Any],
    field_metadata: dict[str, dict[str, Any]],
    allowed_fields: set[str],
) -> list[tuple[FieldUpdate, dict[str, Any]]]:
    updates: list[tuple[FieldUpdate, dict[str, Any]]] = []
    alias_map = _field_aliases(field_metadata)
    for result in tool_results:
        if not _trusted_tool_result(context, result):
            continue
        tool_name = str(getattr(result, "tool_name", ""))
        data = getattr(result, "data", {})
        if not isinstance(data, dict):
            continue
        updates.extend(
            _quote_field_updates_from_tool(
                context=context,
                result=result,
                field_metadata=field_metadata,
                allowed_fields=allowed_fields,
            )
        )
        for raw_update in _raw_field_updates_from_tool_data(data):
            key = _canonical_field_key(raw_update.get("key"), field_metadata, alias_map)
            if key is None or key not in field_metadata:
                continue
            if allowed_fields and key not in allowed_fields:
                continue
            metadata = field_metadata[key]
            if not _tool_source_can_write_field(tool_name, metadata):
                continue
            required_tools = [str(item) for item in _list(metadata.get("required_tools"))]
            if required_tools and not all(
                _has_trusted_tool(context, tool_results, required_tool)
                for required_tool in required_tools
            ):
                continue
            value = raw_update.get("value")
            evidence = _list(raw_update.get("evidence")) or [tool_name]
            update = FieldUpdate(
                field_key=key,
                value=value,
                reason=str(raw_update.get("reason") or f"{tool_name} returned field value."),
                evidence=[str(item) for item in evidence],
                confidence=float(raw_update.get("confidence") or 1.0),
                source="action",
                metadata={
                    "state_writer": "declarative",
                    "tool_result": True,
                    "source_tool": tool_name,
                    "write_policy": metadata.get("write_policy"),
                    "writer": "StateWriter",
                },
            )
            decision = {
                "target": "contact_field",
                "key": key,
                "field": key,
                "proposed_value": value,
                "decision": "accepted",
                "reason": "tool_result_satisfied_field_policy",
                "source": tool_name,
                "writer": "StateWriter",
                "evidence_refs": [f"tool_result:{tool_name}"],
                "confidence": update.confidence,
            }
            updates.append((update, decision))
    return updates


def _derived_updates_for_declarative_change(
    *,
    context: TurnContext,
    update: FieldUpdate,
    field_metadata: dict[str, dict[str, Any]],
    allowed_fields: set[str],
) -> list[tuple[FieldUpdate, dict[str, Any]]]:
    source_metadata = field_metadata.get(update.field_key, {})
    if not _is_employment_seniority_field(update.field_key, source_metadata):
        return []
    months = _int(update.value)
    if months is None:
        return []
    out: list[tuple[FieldUpdate, dict[str, Any]]] = []
    for key, metadata in field_metadata.items():
        if allowed_fields and key not in allowed_fields:
            continue
        if not _is_employment_seniority_eligibility_field(key, metadata):
            continue
        minimum = _minimum_months(context, metadata, source_metadata)
        value = months >= minimum
        derived = FieldUpdate(
            field_key=key,
            value=value,
            reason=(
                f"{update.field_key} validated against minimum {minimum} months."
            ),
            evidence=list(update.evidence) or [context.inbound_text],
            confidence=update.confidence,
            source="action",
            metadata={
                "state_writer": "declarative",
                "system_derived": True,
                "derived_from_field": update.field_key,
                "minimum_months": minimum,
                "writer": "StateWriter",
            },
        )
        out.append(
            (
                derived,
                {
                    "target": "contact_field",
                    "key": key,
                    "field": key,
                    "decision": "accepted",
                    "source": "system",
                    "writer": "StateWriter",
                    "reason": "employment_seniority_eligibility_derived",
                    "evidence_refs": list(derived.evidence),
                    "confidence": derived.confidence,
                },
            )
        )
    return out


def _quote_field_updates_from_tool(
    *,
    context: TurnContext,
    result: Any,
    field_metadata: dict[str, dict[str, Any]],
    allowed_fields: set[str],
) -> list[tuple[FieldUpdate, dict[str, Any]]]:
    if not _trusted_tool_result(context, result, "quote.resolve"):
        return []
    snapshot = _validated_quote_snapshot(_tool_result_value(result, "quote_snapshot"))
    if snapshot is None:
        return []
    updates: list[tuple[FieldUpdate, dict[str, Any]]] = []
    for key, metadata in field_metadata.items():
        if str(metadata.get("domain_role") or "") != "quote":
            continue
        if allowed_fields and key not in allowed_fields:
            continue
        if not _tool_source_can_write_field("quote.resolve", metadata):
            continue
        value = _quote_value_for_field(key, metadata, snapshot)
        if value is None:
            continue
        update = FieldUpdate(
            field_key=key,
            value=value,
            reason="quote.resolve returned validated quote data.",
            evidence=list(snapshot.evidence) or ["quote.resolve"],
            confidence=1.0,
            source="action",
            metadata={
                "state_writer": "declarative",
                "tool_result": True,
                "quote_snapshot": True,
                "quote_snapshot_id": snapshot.snapshot_id,
                "quote_snapshot_hash": snapshot.with_integrity_hash().integrity_hash,
                "source_tool": "quote.resolve",
                "write_policy": metadata.get("write_policy"),
                "writer": "StateWriter",
            },
        )
        decision = {
            "target": "contact_field",
            "key": key,
            "field": key,
            "proposed_value": value,
            "decision": "accepted",
            "reason": "quote_resolver_satisfied_field_policy",
            "source": "quote.resolve",
            "writer": "StateWriter",
            "evidence_refs": ["tool_result:quote.resolve"],
            "confidence": 1.0,
        }
        updates.append((update, decision))
    return updates


def _raw_field_updates_from_tool_data(data: dict[str, Any]) -> list[dict[str, Any]]:
    raw = data.get("field_updates")
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, dict)]
    fields = data.get("fields")
    if isinstance(fields, dict):
        return [{"key": key, "value": value} for key, value in fields.items()]
    return []


def _tool_source_can_write_field(tool_name: str, metadata: dict[str, Any]) -> bool:
    policy = str(metadata.get("write_policy") or "auto_apply")
    allowed_sources = [str(item) for item in _list(metadata.get("allowed_sources"))]
    if policy in {"blocked_from_model"}:
        return True
    if allowed_sources and tool_name not in allowed_sources:
        return False
    return policy in {
        "auto_apply",
        "auto_apply_when_catalog_match",
        "auto_apply_when_valid_plan",
        "tool_only",
        "attachment_required",
        "system_derived",
    }


def _quote_value_for_field(
    key: str,
    metadata: dict[str, Any],
    snapshot: QuoteSnapshot,
) -> Any:
    value_path = metadata.get("value_path")
    if value_path:
        return _value_at_path(snapshot.model_dump(mode="json"), str(value_path))
    folded_key = key.casefold()
    if "snapshot_id" in folded_key or folded_key.endswith("_id"):
        return snapshot.snapshot_id
    if "valid_until" in folded_key:
        return snapshot.quote_payload.get("valid_until")
    if "payment" in folded_key or "amount" in folded_key:
        return _first_pricing_amount(snapshot.pricing)
    return snapshot.with_integrity_hash().model_dump(mode="json")


def _value_at_path(value: Any, path: str) -> Any:
    current = value
    for part in path.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def _first_pricing_amount(pricing: dict[str, Any]) -> Any:
    for key in ("payment_amount", "installment", "monthly_payment", "cash_price", "price"):
        if key in pricing:
            return pricing[key]
    for value in pricing.values():
        if isinstance(value, int | float | str):
            return value
    return None


def _quote_invalidations_for_declarative_change(
    *,
    context: TurnContext,
    changed_field: str,
    new_value: Any,
    field_metadata: dict[str, dict[str, Any]],
    quote_fields: set[str],
    allowed_fields: set[str],
) -> list[FieldUpdate]:
    metadata = field_metadata.get(changed_field, {})
    role = str(metadata.get("domain_role") or "")
    invalidates_roles = {str(item) for item in _list(metadata.get("invalidates_roles"))}
    invalidates_fields = {str(item) for item in _list(metadata.get("invalidates_fields"))}
    should_invalidate = (
        "quote" in invalidates_roles
        or bool(invalidates_fields)
        or role in {"selection", "plan"}
    )
    if not should_invalidate or not _field_value_changed(context, changed_field, new_value):
        return []
    targets = {
        key
        for key, item in field_metadata.items()
        if str(item.get("domain_role") or "") == "quote"
    }
    targets.update(quote_fields)
    targets.update(invalidates_fields)
    updates: list[FieldUpdate] = []
    for key in sorted(targets):
        if key == changed_field:
            continue
        if allowed_fields and key not in allowed_fields:
            continue
        if _current_field_value(context, key) is None:
            continue
        updates.append(
            FieldUpdate(
                field_key=key,
                value=None,
                reason=f"{changed_field} changed; dependent quote field is stale.",
                evidence=[context.inbound_text],
                confidence=1.0,
                source="action",
                metadata={
                    "state_writer": "declarative",
                    "quote_snapshot_invalidated": True,
                    "invalidated_by_field_change": True,
                    "changed_field": changed_field,
                    "invalidated_field": key,
                    "writer": "StateWriter",
                },
            )
        )
    return updates


def _field_value_changed(context: TurnContext, key: str, new_value: Any) -> bool:
    current = _current_field_value(context, key)
    if current is None:
        return False
    return current != new_value


def _current_field_value(context: TurnContext, key: str) -> Any:
    if key in context.memory.salient_facts:
        return context.memory.salient_facts.get(key)
    return context.customer.attrs.get(key)


def _is_employment_seniority_field(key: str, metadata: dict[str, Any]) -> bool:
    role = _field_token(metadata.get("domain_role"))
    token = _field_token(key)
    aliases = {_field_token(alias) for alias in _list(metadata.get("aliases"))}
    return (
        role in {"employmentseniority", "workseniority"}
        or token in {"employmentseniority", "employmentsenioritymonths", "workseniority"}
        or bool(aliases & {"employmentseniority", "employmentsenioritymonths", "workseniority"})
    )


def _is_employment_seniority_eligibility_field(
    key: str,
    metadata: dict[str, Any],
) -> bool:
    role = _field_token(metadata.get("domain_role"))
    token = _field_token(key)
    aliases = {_field_token(alias) for alias in _list(metadata.get("aliases"))}
    return (
        role == "employmentseniorityeligibility"
        or token in {"employmentseniorityeligibility", "seniorityeligibility"}
        or bool(aliases & {"employmentseniorityeligibility", "seniorityeligibility"})
    )


def _minimum_months(
    context: TurnContext,
    target_metadata: dict[str, Any],
    source_metadata: dict[str, Any],
) -> int:
    for source in (
        _dict(target_metadata.get("validation")),
        _dict(source_metadata.get("validation")),
        _dict(_dict(context.tenant_config.tenant_domain_contract).get("flow_policy")),
    ):
        value = source.get("minimum_months") or source.get("seniority_minimum_months")
        months = _int(value)
        if months is not None:
            return months
    return 1


def _invalidation_decision(update: FieldUpdate, *, changed_field: str) -> dict[str, Any]:
    return {
        "field": update.field_key,
        "decision": "invalidated",
        "reason": update.reason,
        "source": "system",
        "writer": "StateWriter",
        "evidence_refs": list(update.evidence),
        "changed_field": changed_field,
    }


def _decision_payload(
    change: AdvisorBrainStateChange,
    *,
    decision: str,
    reason: str,
    source: str,
    evidence_refs: list[str] | None = None,
    confidence: float | None = None,
) -> dict[str, Any]:
    return {
        "target": change.target,
        "key": change.key,
        "field": change.key,
        "proposed_value": change.value,
        "decision": decision,
        "reason": reason,
        "source": source,
        "writer": "StateWriter",
        "evidence_refs": list(evidence_refs or []),
        "confidence": confidence if confidence is not None else change.confidence,
    }


def _visible_fields(context: TurnContext) -> set[str]:
    contract_fields = set(_field_metadata(context))
    if context.active_agent and context.active_agent.visible_contact_field_keys is not None:
        return set(context.active_agent.visible_contact_field_keys) | contract_fields
    return {field.key for field in context.contact_fields} | contract_fields


def _configured_single_field(context: TurnContext, name: str) -> str | None:
    rules = context.tenant_config.ruleset
    fields = _dict(_dict(rules.get("operational_state")).get("fields"))
    value = fields.get(name)
    return str(value) if value else None


def _configured_field_names(context: TurnContext, name: str) -> set[str]:
    rules = context.tenant_config.ruleset
    state_writer = _dict(rules.get("state_writer"))
    values = state_writer.get(name)
    if not isinstance(values, list):
        return set()
    return {str(item) for item in values if str(item).strip()}


def _stage_from_value(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    if isinstance(value, dict):
        for key in ("target_stage", "stage"):
            if value.get(key):
                return str(value[key])
    return None


def _accepted(change: AdvisorBrainStateChange) -> dict[str, Any]:
    return {"target": change.target, "key": change.key}


def _blocked(change: AdvisorBrainStateChange, reason: str) -> dict[str, Any]:
    return {"target": change.target, "key": change.key, "reason": reason}


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def _field_token(value: Any) -> str:
    return str(value or "").casefold().replace("_", "").replace("-", "").replace(" ", "")


def _tool_result_value(result: Any, key: str) -> Any:
    data = getattr(result, "data", None)
    if isinstance(data, dict):
        return data.get(key)
    if isinstance(result, dict):
        nested = result.get("data")
        if isinstance(nested, dict):
            return nested.get(key)
        return result.get(key)
    return None


def _trusted_quote_resolver_result(result: Any, context: TurnContext | None = None) -> bool:
    tool_name = getattr(result, "tool_name", None)
    status = getattr(result, "status", None)
    data = getattr(result, "data", None)
    trace_metadata = getattr(result, "trace_metadata", None)
    if isinstance(result, dict):
        tool_name = result.get("tool_name") or result.get("name")
        status = result.get("status")
        data = result.get("data")
        trace_metadata = result.get("trace_metadata")
    if str(tool_name or "") != "quote.resolve" or str(status or "") != "succeeded":
        return False
    if context is None:
        return True
    return not _tool_result_has_cross_tenant_data(
        context,
        data if isinstance(data, dict) else {},
        trace_metadata if isinstance(trace_metadata, dict) else {},
    )


def _validated_quote_snapshot(value: Any) -> QuoteSnapshot | None:
    snapshot = coerce_quote_snapshot(value)
    if snapshot is None:
        return None
    if not snapshot.snapshot_id:
        return None
    if (
        not snapshot.product.product_id
        or not snapshot.product.sku
        or not snapshot.product.display_name
    ):
        return None
    if not (snapshot.plan_code or snapshot.plan_name):
        return None
    if not snapshot.pricing:
        return None
    if not snapshot.currency:
        return None
    if not snapshot.evidence:
        return None
    if not snapshot.created_at:
        return None
    if _source_token(snapshot.source_tool) not in {
        "quoteresolver",
        "quote resolver",
        "quote_resolver",
        "quote.resolve",
    }:
        return None
    return snapshot.with_integrity_hash()


def _quote_invalidations_for_product_change(
    *,
    context: TurnContext,
    product_value: Any,
    quote_field: str | None,
    quote_sent_field: str | None,
    allowed_fields: set[str],
) -> list[FieldUpdate]:
    if not quote_field or (allowed_fields and quote_field not in allowed_fields):
        return []
    new_product = coerce_canonical_product_ref(product_value)
    existing_quote = coerce_quote_snapshot(
        context.memory.salient_facts.get(quote_field)
        or context.memory.last_quote_snapshot
    )
    if new_product is None or existing_quote is None:
        return []
    if existing_quote.product.product_id == new_product.product_id:
        return []

    evidence = [context.inbound_text]
    updates = [
        FieldUpdate(
            field_key=quote_field,
            value=None,
            reason="Product changed; previous QuoteSnapshot no longer matches canonical product.",
            evidence=evidence,
            confidence=1.0,
            source="action",
            metadata={
                "state_writer": "deterministic",
                "quote_snapshot_invalidated": True,
                "invalidated_by_product_change": True,
                "invalidated_quote_snapshot": existing_quote.model_dump(mode="json"),
                "previous_product_id": existing_quote.product.product_id,
                "new_product_id": new_product.product_id,
            },
        )
    ]
    if quote_sent_field and (not allowed_fields or quote_sent_field in allowed_fields):
        updates.append(
            FieldUpdate(
                field_key=quote_sent_field,
                value=False,
                reason="Quote sent flag cleared because active QuoteSnapshot was invalidated.",
                evidence=evidence,
                confidence=1.0,
                source="action",
                metadata={
                    "state_writer": "deterministic",
                    "quote_snapshot_invalidated": True,
                    "invalidated_by_product_change": True,
                    "invalidated_quote_snapshot_id": existing_quote.snapshot_id,
                    "previous_product_id": existing_quote.product.product_id,
                    "new_product_id": new_product.product_id,
                },
            )
        )
    return updates


def _quote_invalidations_for_plan_change(
    *,
    context: TurnContext,
    changed_field: str,
    new_value: Any,
    quote_field: str | None,
    quote_sent_field: str | None,
    allowed_fields: set[str],
) -> list[FieldUpdate]:
    if not quote_field or (allowed_fields and quote_field not in allowed_fields):
        return []
    existing_quote = coerce_quote_snapshot(
        context.memory.salient_facts.get(quote_field)
        or context.memory.last_quote_snapshot
    )
    if existing_quote is None:
        return []
    plan = str(existing_quote.plan_code or existing_quote.plan_name or "").casefold()
    if plan == "cash" or "contado" in plan:
        return []
    new_plan = str(new_value or "").strip()
    existing_plan = str(existing_quote.plan_code or existing_quote.plan_name or "")
    if changed_field and new_plan and new_plan == existing_plan:
        return []
    evidence = [context.inbound_text]
    updates = [
        FieldUpdate(
            field_key=quote_field,
            value=None,
            reason="Plan or income changed; previous financing QuoteSnapshot is no longer active.",
            evidence=evidence,
            confidence=1.0,
            source="action",
            metadata={
                "state_writer": "deterministic",
                "quote_snapshot_invalidated": True,
                "invalidated_by_plan_change": True,
                "invalidated_quote_snapshot": existing_quote.model_dump(mode="json"),
                "changed_field": changed_field,
                "previous_plan_code": existing_quote.plan_code,
                "new_value": new_value,
            },
        )
    ]
    if quote_sent_field and (not allowed_fields or quote_sent_field in allowed_fields):
        updates.append(
            FieldUpdate(
                field_key=quote_sent_field,
                value=False,
                reason=(
                    "Quote sent flag cleared because active financing QuoteSnapshot was "
                    "invalidated."
                ),
                evidence=evidence,
                confidence=1.0,
                source="action",
                metadata={
                    "state_writer": "deterministic",
                    "quote_snapshot_invalidated": True,
                    "invalidated_by_plan_change": True,
                    "invalidated_quote_snapshot_id": existing_quote.snapshot_id,
                    "changed_field": changed_field,
                },
            )
        )
    return updates


def _configured_document_fields(context: TurnContext) -> set[str]:
    fields = _dict(_dict(context.tenant_config.ruleset.get("operational_state")).get("fields"))
    candidates = {
        "documents_complete",
        "documents_incomplete",
        "documents_checklist",
        "doc_complete",
        "doc_incomplete",
    }
    values = {str(fields[key]) for key in candidates if fields.get(key)}
    values.update({"Doc_Completos", "Doc_Incompletos", "Docs_Checklist"})
    return values


def _configured_document_stages(context: TurnContext) -> set[str]:
    rules = context.tenant_config.ruleset
    state_writer = _dict(rules.get("state_writer"))
    configured = state_writer.get("document_stages")
    if isinstance(configured, list):
        return {str(item) for item in configured if str(item).strip()}
    stages = _dict(_dict(rules.get("operational_state")).get("stages"))
    values = {
        str(stages[key])
        for key in ("documents_complete", "documents_incomplete")
        if stages.get(key)
    }
    values.update({"papeleria_completa", "papeleria_incompleta"})
    return values


def _is_blocked_document_lifecycle_change(
    context: TurnContext,
    change: AdvisorBrainStateChange,
) -> bool:
    stage = change.key or _stage_from_value(change.value)
    if not stage or stage not in _configured_document_stages(context):
        return False
    if "completa" in str(stage).casefold():
        return not _has_complete_document_checklist(context, change.value)
    return not _has_document_attachment_or_checklist(context, change.value)


def _document_update_has_evidence(
    context: TurnContext,
    change: AdvisorBrainStateChange,
) -> bool:
    key = str(change.key or "")
    value = change.value
    if "checklist" in key.casefold():
        return _has_document_attachment(context) or _has_checklist(value)
    if value is True:
        return _has_complete_document_checklist(context, value)
    return _has_document_attachment_or_checklist(context, value)


def _has_document_attachment_or_checklist(context: TurnContext, value: Any = None) -> bool:
    return _has_document_attachment(context) or _has_checklist(value) or _has_checklist(
        context.memory.documents.get("Docs_Checklist")
        or context.memory.salient_facts.get("Docs_Checklist")
    )


def _has_complete_document_checklist(context: TurnContext, value: Any = None) -> bool:
    checklist = _as_checklist(value)
    if not checklist:
        checklist = _as_checklist(
            context.memory.documents.get("Docs_Checklist")
            or context.memory.salient_facts.get("Docs_Checklist")
        )
    if not checklist:
        return False
    valid_statuses = {"accepted", "valid", "validated"}
    return all(str(item.get("status") or "").casefold() in valid_statuses for item in checklist)


def _has_document_attachment(context: TurnContext) -> bool:
    attachments = context.metadata.get("attachments")
    return isinstance(attachments, list) and bool(attachments)


def _has_checklist(value: Any) -> bool:
    return bool(_as_checklist(value))


def _as_checklist(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        nested = value.get("checklist") or value.get("documents") or value.get("items")
        if isinstance(nested, list):
            return [item for item in nested if isinstance(item, dict)]
    return []


def _source_token(value: str | None) -> str:
    return str(value or "").casefold().replace("_", " ").strip()


__all__ = ["DeterministicStateWriter", "StateWriteResult"]
