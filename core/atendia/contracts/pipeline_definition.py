import re

from pydantic import BaseModel, Field, field_validator, model_validator


_FIELD_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")


class FieldSpec(BaseModel):
    name: str
    description: str = ""

    @field_validator("name")
    @classmethod
    def _name_pattern(cls, v: str) -> str:
        if not _FIELD_NAME_RE.match(v):
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


class Transition(BaseModel):
    to: str
    when: str


class StageDefinition(BaseModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    required_fields: list[str] = Field(default_factory=list)
    actions_allowed: list[str] = Field(default_factory=list)
    transitions: list[Transition] = Field(default_factory=list)
    timeout_hours: int | None = None
    timeout_action: str | None = None


class PipelineDefinition(BaseModel):
    version: int = Field(ge=1)
    stages: list[StageDefinition] = Field(min_length=1)
    tone: dict
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
