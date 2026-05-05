import re

from pydantic import BaseModel, Field, field_validator, model_validator


_FIELD_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")


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


class StageDefinition(BaseModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    required_fields: list[FieldSpec] = Field(default_factory=list)
    optional_fields: list[FieldSpec] = Field(default_factory=list)
    actions_allowed: list[str] = Field(default_factory=list)
    transitions: list[Transition] = Field(default_factory=list)
    timeout_hours: int | None = None
    timeout_action: str | None = None

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


class PipelineDefinition(BaseModel):
    version: int = Field(ge=1)
    nlu: NLUConfig = Field(default_factory=NLUConfig)
    composer: ComposerConfig = Field(default_factory=ComposerConfig)
    stages: list[StageDefinition] = Field(min_length=1)
    # tone field removed in Phase 3b — moved to tenant_branding.voice
    fallback: str

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
