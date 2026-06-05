from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

JsonDict = dict[str, Any]


class BlueprintContactField(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(min_length=2, max_length=64)
    label: str = Field(min_length=1, max_length=120)
    field_type: str
    field_options: JsonDict | None = None
    ordering: int = 0
    extractable_by_ai: bool = True
    write_policy: Literal["ai_auto", "ai_suggest", "human_only"] = "ai_suggest"
    confidence_threshold: float = Field(default=0.85, ge=0, le=1)
    evidence_required: bool = True
    prompt_visible: bool = True
    lifecycle_relevant: bool = False
    pii: bool = False
    sensitive: bool = False


class BlueprintLifecycleStage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    description: str = ""
    goal: str = ""
    entry_conditions: list[str] = Field(default_factory=list)
    exit_conditions: list[str] = Field(default_factory=list)
    recommended_fields: list[str] = Field(default_factory=list)
    required_fields: list[str] = Field(default_factory=list)
    recommended_actions: list[str] = Field(default_factory=list)
    allowed_actions: list[str] = Field(default_factory=list)
    automation_policy: JsonDict = Field(default_factory=dict)
    is_lost_stage: bool = False
    order: int = 0
    active: bool = True


class BlueprintAgentTemplate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    role: Literal["sales", "support", "receptionist", "custom"] = "custom"
    tone: str = "friendly"
    language_policy: JsonDict = Field(default_factory=lambda: {"primary": "es-MX"})
    instructions: str
    escalation_policy: JsonDict = Field(default_factory=dict)


class BlueprintWorkflowTemplate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    trigger_type: str
    trigger_config: JsonDict = Field(default_factory=dict)
    definition: JsonDict = Field(default_factory=lambda: {"nodes": [], "edges": []})
    active: bool = False
    stub: bool = True


class BlueprintEvalScenario(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    input_message: str
    expected_behaviors: list[str] = Field(default_factory=list)
    forbidden_behaviors: list[str] = Field(default_factory=list)
    expected_field_updates: list[str] = Field(default_factory=list)
    expected_lifecycle: str | None = None
    expected_actions: list[str] = Field(default_factory=list)
    metadata: JsonDict = Field(default_factory=dict)


class BlueprintDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    description: str
    industries: list[str]
    contact_fields: list[BlueprintContactField] = Field(default_factory=list)
    lifecycle_stages: list[BlueprintLifecycleStage] = Field(default_factory=list)
    agent_template: BlueprintAgentTemplate
    enabled_actions: list[str] = Field(default_factory=list)
    knowledge_categories: list[str] = Field(default_factory=list)
    workflow_templates: list[BlueprintWorkflowTemplate] = Field(default_factory=list)
    eval_scenarios: list[BlueprintEvalScenario] = Field(default_factory=list)

    @field_validator("id")
    @classmethod
    def _valid_id(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized or not normalized.replace("_", "").replace("-", "").isalnum():
            raise ValueError("blueprint id must be slug-like")
        return normalized


class BlueprintPreview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    blueprint: BlueprintDefinition
    field_keys: list[str]
    lifecycle_stage_ids: list[str]
    enabled_actions: list[str]
    knowledge_categories: list[str]
    eval_scenario_ids: list[str]


class BlueprintInstallResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    blueprint_id: str
    tenant_id: str
    created_field_keys: list[str] = Field(default_factory=list)
    skipped_field_keys: list[str] = Field(default_factory=list)
    created_lifecycle_stage_ids: list[str] = Field(default_factory=list)
    skipped_lifecycle_stage_ids: list[str] = Field(default_factory=list)
    agent_id: str | None = None
    agent_created: bool = False
    workflow_template_ids: list[str] = Field(default_factory=list)
    eval_scenario_ids: list[str] = Field(default_factory=list)
    already_installed: bool = False
    audit_event: str = "admin.blueprint.installed"
