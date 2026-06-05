from __future__ import annotations

from dataclasses import dataclass

from atendia.agent_runtime.action_registry import (
    ActionRegistry,
    default_action_registry,
)
from atendia.agent_runtime.schemas import (
    ActionRequest,
    TurnOutput,
    customer_visible_text_paths,
)

PLACEHOLDER_TOKENS = (
    "$X",
    "$Y",
    "$Z",
    "{precio}",
    "{enganche}",
    "{pago}",
    "{modelo}",
    "N quincenas",
    "TBD",
)
APPROVAL_PROMISES = (
    "aprobado seguro",
    "seguro te aprueban",
    "te aprueban seguro",
    "aprobacion garantizada",
    "aprobación garantizada",
)


@dataclass(frozen=True)
class PolicyIssue:
    code: str
    message: str


class PolicyValidationError(ValueError):
    def __init__(self, issues: list[PolicyIssue]) -> None:
        self.issues = issues
        super().__init__("; ".join(f"{issue.code}: {issue.message}" for issue in issues))


class PolicyValidator:
    def __init__(
        self,
        registry: ActionRegistry | None = None,
        *,
        low_confidence_threshold: float = 0.5,
    ) -> None:
        self._registry = registry or default_action_registry()
        self._low_confidence_threshold = low_confidence_threshold

    def validate(self, output: TurnOutput) -> list[PolicyIssue]:
        issues: list[PolicyIssue] = []

        final_message = output.final_message
        if isinstance(final_message, list):
            issues.append(
                PolicyIssue(
                    "multiple_final_messages",
                    "TurnOutput must contain a single final_message string.",
                )
            )
        elif not output.needs_human and not str(final_message or "").strip():
            issues.append(
                PolicyIssue(
                    "missing_final_message",
                    "final_message is required when needs_human is false.",
                )
            )
        final_text = str(final_message or "")
        if any(token in final_text for token in PLACEHOLDER_TOKENS):
            issues.append(
                PolicyIssue(
                    "final_message_placeholder",
                    "final_message must not expose quote placeholders.",
                )
            )
        folded_final = final_text.casefold()
        if any(promise in folded_final for promise in APPROVAL_PROMISES):
            issues.append(
                PolicyIssue(
                    "approval_promise",
                    "final_message must not promise credit approval.",
                )
            )

        if not 0 <= float(output.confidence) <= 1:
            issues.append(
                PolicyIssue("invalid_confidence", "confidence must be between 0 and 1.")
            )
        elif (
            output.confidence < self._low_confidence_threshold
            and not output.needs_human
            and not output.risk_flags
        ):
            issues.append(
                PolicyIssue(
                    "low_confidence_unflagged",
                    "Low confidence must set needs_human or at least one risk_flag.",
                )
            )

        for update in output.field_updates:
            if not (update.reason or update.evidence):
                issues.append(
                    PolicyIssue(
                        "field_update_missing_evidence",
                        f"Field update {update.field_key!r} needs reason or evidence.",
                    )
                )
            if update.confidence is None:
                issues.append(
                    PolicyIssue(
                        "field_update_missing_confidence",
                        f"Field update {update.field_key!r} requires confidence.",
                    )
                )
            elif not 0 <= float(update.confidence) <= 1:
                issues.append(
                    PolicyIssue(
                        "field_update_invalid_confidence",
                        f"Field update {update.field_key!r} confidence must be between 0 and 1.",
                    )
                )

        if output.lifecycle_update is not None:
            if not output.lifecycle_update.reason:
                issues.append(
                    PolicyIssue(
                        "lifecycle_update_missing_reason",
                        "lifecycle_update requires a reason.",
                    )
                )
            if not output.lifecycle_update.evidence:
                issues.append(
                    PolicyIssue(
                        "lifecycle_update_missing_evidence",
                        "lifecycle_update requires evidence.",
                    )
                )
            if output.lifecycle_update.confidence is None:
                issues.append(
                    PolicyIssue(
                        "lifecycle_update_missing_confidence",
                        "lifecycle_update requires confidence.",
                    )
                )
            elif not 0 <= float(output.lifecycle_update.confidence) <= 1:
                issues.append(
                    PolicyIssue(
                        "lifecycle_update_invalid_confidence",
                        "lifecycle_update confidence must be between 0 and 1.",
                    )
                )

        for action in output.actions:
            issues.extend(self._validate_action(action))

        return issues

    def validate_or_raise(self, output: TurnOutput) -> None:
        issues = self.validate(output)
        if issues:
            raise PolicyValidationError(issues)

    def _validate_action(self, action: ActionRequest) -> list[PolicyIssue]:
        issues: list[PolicyIssue] = []
        if not self._registry.has_action(action.name):
            return [
                PolicyIssue(
                    "unknown_action",
                    f"Action {action.name!r} is not registered in ActionRegistry.",
                )
            ]

        forbidden_paths = sorted(customer_visible_text_paths(action.payload))
        if forbidden_paths:
            issues.append(
                PolicyIssue(
                    "action_returns_visible_text",
                    f"Action {action.name!r} payload contains customer-visible text keys: "
                    + ", ".join(forbidden_paths),
                )
            )

        definition = self._registry.get(action.name)
        if definition.requires_evidence and not action.evidence:
            issues.append(
                PolicyIssue(
                    "sensitive_action_missing_evidence",
                    f"Action {action.name!r} requires evidence.",
                )
            )
        if (
            definition.requires_approval
            or definition.execution_mode == "human_approval"
        ) and not action.requires_approval:
            issues.append(
                PolicyIssue(
                    "sensitive_action_missing_approval",
                    f"Action {action.name!r} requires an explicit approval marker.",
                )
            )
        return issues
