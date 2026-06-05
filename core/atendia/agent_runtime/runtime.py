from __future__ import annotations

from typing import Any, Protocol

from atendia.agent_runtime.agent_config import action_registry_for_agent
from atendia.agent_runtime.advisor_pipeline import AdvisorFirstAgentProvider
from atendia.agent_runtime.context_builder import ContextBuilder
from atendia.agent_runtime.policy_validator import PolicyValidator
from atendia.agent_runtime.schemas import TurnContext, TurnInput, TurnOutput
from atendia.config import get_settings


class AgentTurnProvider(Protocol):
    async def generate(self, context: TurnContext) -> TurnOutput | dict[str, Any]: ...


class DeterministicAgentProvider:
    """Small provider for tests and manual harnesses before LLM wiring."""

    async def generate(self, context: TurnContext) -> TurnOutput:
        return TurnOutput(
            final_message="Recibido. Voy a revisar el contexto y te ayudo con el siguiente paso.",
            confidence=0.72,
            needs_human=False,
            knowledge_citations=context.knowledge_citations,
            trace_metadata={
                "provider": "deterministic",
                "runtime": "agent_runtime_v2",
                "agent_id": context.active_agent.id if context.active_agent else None,
                "agent_template": (
                    context.active_agent.metadata.get("template")
                    if context.active_agent
                    else None
                ),
                "tone": context.active_agent.tone if context.active_agent else None,
            },
        )


class AgentRuntime:
    def __init__(
        self,
        *,
        context_builder: ContextBuilder | None = None,
        provider: AgentTurnProvider | None = None,
        policy_validator: PolicyValidator | None = None,
    ) -> None:
        self._context_builder = context_builder or ContextBuilder()
        self._provider = provider or AdvisorFirstAgentProvider()
        self._policy_validator = policy_validator or PolicyValidator()

    async def run_turn(self, turn_input: TurnInput | dict[str, Any]) -> TurnOutput:
        parsed_input = turn_input if isinstance(turn_input, TurnInput) else TurnInput(**turn_input)
        context = await self._context_builder.build(parsed_input)
        raw_output = await self._provider.generate(context)
        output = raw_output if isinstance(raw_output, TurnOutput) else TurnOutput(**raw_output)
        validator = self._policy_validator
        if context.active_agent and context.active_agent.enabled_action_ids is not None:
            validator = PolicyValidator(
                action_registry_for_agent(context.active_agent),
            )
        validator.validate_or_raise(output)
        return output


def agent_runtime_v2_enabled(settings: Any | None = None) -> bool:
    resolved_settings = settings or get_settings()
    return bool(getattr(resolved_settings, "agent_runtime_v2_enabled", False))
