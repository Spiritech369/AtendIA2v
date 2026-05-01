from pydantic import BaseModel, Field, model_validator


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
