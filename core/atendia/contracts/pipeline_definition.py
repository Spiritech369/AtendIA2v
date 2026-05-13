import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from atendia.contracts.flow_mode import FlowMode
from atendia.runner.flow_router import AlwaysTrigger, FlowModeRule

_FIELD_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")

# Auto-enter rule paths use dot-separated nesting so
# "DOCS_INE.status" resolves to customer.attrs["DOCS_INE"]["status"].
# The full path must be a sequence of segments where each segment looks
# like a Python identifier (uppercase allowed because document keys use
# DOCS_*); we accept both lowercase fields like "plan_credito" and
# uppercase doc keys like "DOCS_INE".
_RULE_FIELD_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*$")

# Operators that consume a value vs. operators that only check presence.
# Mirror the frontend OperatorSelector so both sides stay in lockstep.
_PRESENCE_OPERATORS: frozenset[str] = frozenset({"exists", "not_exists"})
_LIST_OPERATORS: frozenset[str] = frozenset({"in", "not_in"})
_VALUE_OPERATORS: frozenset[str] = frozenset({
    "equals", "not_equals", "contains", "greater_than", "less_than", "in", "not_in",
})
OPERATORS: frozenset[str] = _PRESENCE_OPERATORS | _VALUE_OPERATORS


def _default_flow_mode_rules() -> list[FlowModeRule]:
    """Phase 3c.2 — minimal fallback so the router never raises on a tenant
    that hasn't authored explicit rules. Routes everything to SUPPORT;
    legacy 3a/3b tenants keep their FAQ-style behavior."""
    return [
        FlowModeRule(
            id="default_always_support",
            trigger=AlwaysTrigger(),
            mode=FlowMode.SUPPORT,
        ),
    ]


class FieldSpec(BaseModel):
    name: str
    description: str = Field(default="", max_length=200)

    @field_validator("name")
    @classmethod
    def _name_pattern(cls, v: str) -> str:
        if not _FIELD_NAME_RE.fullmatch(v):
            raise ValueError(
                f"invalid field name {v!r} — must match {_FIELD_NAME_RE.pattern}"
            )
        return v

    @model_validator(mode="before")
    @classmethod
    def _accept_string(cls, data):
        if isinstance(data, str):
            return {"name": data, "description": ""}
        return data


class NLUConfig(BaseModel):
    history_turns: int = Field(default=2, ge=0, le=10)


class ComposerConfig(BaseModel):
    history_turns: int = Field(default=2, ge=0, le=10)


class Transition(BaseModel):
    to: str
    when: str


class Condition(BaseModel):
    """A single auto-enter rule clause.

    ``field`` uses dot-separated nesting so ``DOCS_INE.status`` resolves to
    ``customer.attrs["DOCS_INE"]["status"]`` at evaluation time. Operators
    are pinned to a closed allow-list (``OPERATORS``) so an operator can't
    invent a new one and silently bypass the evaluator. ``value`` is
    required for all operators except ``exists`` / ``not_exists``, and must
    be a list for ``in`` / ``not_in``.
    """

    model_config = ConfigDict(extra="forbid")

    field: str = Field(min_length=1, max_length=200)
    operator: Literal[
        "exists",
        "not_exists",
        "equals",
        "not_equals",
        "contains",
        "greater_than",
        "less_than",
        "in",
        "not_in",
    ]
    value: Any | None = None

    @field_validator("field")
    @classmethod
    def _validate_field_path(cls, v: str) -> str:
        if not _RULE_FIELD_RE.fullmatch(v):
            raise ValueError(
                f"condition field {v!r} must be dot-separated identifiers "
                f"matching {_RULE_FIELD_RE.pattern}"
            )
        return v

    @model_validator(mode="after")
    def _value_consistency(self) -> "Condition":
        if self.operator in _PRESENCE_OPERATORS:
            # Presence checks ignore value; reject if one was sent to
            # surface authoring mistakes early.
            if self.value is not None:
                raise ValueError(
                    f"operator {self.operator!r} does not accept a value"
                )
            return self
        if self.value is None:
            raise ValueError(f"operator {self.operator!r} requires a value")
        if self.operator in _LIST_OPERATORS and not isinstance(self.value, list):
            raise ValueError(
                f"operator {self.operator!r} requires a list value, got {type(self.value).__name__}"
            )
        return self


class AutoEnterRules(BaseModel):
    """Per-stage auto-enter rule group.

    The evaluator (M3) walks every stage with ``enabled=True`` and checks
    its conditions against the conversation's extracted fields. When
    ``match='all'``, every condition must pass; when ``match='any'``, one
    is enough. A stage with ``enabled=True`` must have at least one
    condition — silently-active rules with empty condition lists would
    auto-match any field state and trap conversations in the wrong stage.
    """

    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    match: Literal["all", "any"] = "all"
    conditions: list[Condition] = Field(default_factory=list)

    @model_validator(mode="after")
    def _enabled_requires_conditions(self) -> "AutoEnterRules":
        if self.enabled and not self.conditions:
            raise ValueError(
                "auto_enter_rules.enabled=true requires at least one condition"
            )
        return self


class StageDefinition(BaseModel):
    # We keep `extra="allow"` for now because the JSONB definition carries
    # presentation-only fields the frontend renders (label, color) that
    # the runner doesn't need to validate. Dropping them via extra="forbid"
    # would force a migration of every persisted pipeline. The fields the
    # *runner* depends on are explicitly typed below.
    model_config = ConfigDict(extra="allow")

    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    required_fields: list[FieldSpec] = Field(default_factory=list)
    optional_fields: list[FieldSpec] = Field(default_factory=list)
    actions_allowed: list[str] = Field(default_factory=list)
    transitions: list[Transition] = Field(default_factory=list)
    timeout_hours: int | None = None
    timeout_action: str | None = None
    # M1: declarative auto-enter rules. The evaluator (M3) drives stage
    # transitions off these. None means "no auto-enter for this stage".
    auto_enter_rules: AutoEnterRules | None = None
    # M3 honors this when picking a target stage: with `is_terminal=True`,
    # a conversation in this stage never moves forward or backward via
    # auto-enter rules. Manual moves still work (operator can intervene).
    is_terminal: bool = False
    # When False (default), the evaluator never moves a conversation to a
    # stage whose order is earlier than the conversation's current stage.
    # Terminal stages override this — a terminal stage never allows
    # backward movement regardless of this flag.
    allow_auto_backward: bool = False

    @model_validator(mode="after")
    def _no_duplicate_field_names(self) -> "StageDefinition":
        req = {f.name for f in self.required_fields}
        opt = {f.name for f in self.optional_fields}
        overlap = req & opt
        if overlap:
            raise ValueError(
                f"fields appear in both required and optional: {sorted(overlap)}"
            )
        return self

    @model_validator(mode="after")
    def _terminal_blocks_backward(self) -> "StageDefinition":
        # Conceptually contradictory and a frequent operator error: terminal
        # stages with allow_auto_backward=True would re-open work that was
        # marked closed (cancelled, won, lost). Reject at validation time.
        if self.is_terminal and self.allow_auto_backward:
            raise ValueError(
                f"stage '{self.id}': is_terminal=true is incompatible with allow_auto_backward=true"
            )
        return self


class PipelineDefinition(BaseModel):
    version: int = Field(ge=1)
    nlu: NLUConfig = Field(default_factory=NLUConfig)
    composer: ComposerConfig = Field(default_factory=ComposerConfig)
    stages: list[StageDefinition] = Field(min_length=1)
    # tone field removed in Phase 3b — moved to tenant_branding.voice
    fallback: str
    # Phase 3c.2 — deterministic flow router config:
    flow_mode_rules: list[FlowModeRule] = Field(
        default_factory=_default_flow_mode_rules,
    )
    docs_per_plan: dict[str, list[str]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_stage_ids_unique(self) -> "PipelineDefinition":
        ids = [s.id for s in self.stages]
        if len(ids) != len(set(ids)):
            raise ValueError("stage ids must be unique")
        return self

    @model_validator(mode="after")
    def _validate_transitions_target_existing_stages(self) -> "PipelineDefinition":
        ids = {s.id for s in self.stages}
        for stage in self.stages:
            for t in stage.transitions:
                if t.to not in ids:
                    raise ValueError(f"transition target '{t.to}' is not a known stage")
        return self
