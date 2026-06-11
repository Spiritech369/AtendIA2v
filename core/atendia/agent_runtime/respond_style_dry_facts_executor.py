from __future__ import annotations

from typing import Any

from atendia.agent_runtime.respond_style_tool_loop import ToolExecutionResult
from atendia.agent_runtime.respond_style_turn_contract import (
    AgentContextPackage,
    LLMToolCallProposal,
)

JsonDict = dict[str, Any]


class DryFactsToolExecutor:
    """Generic config-driven fact-only executor for no-send runs.

    Each tool binding may declare ``dry_facts`` (the facts a successful run
    returns) and ``preconditions`` (contact-state keys that must be known,
    either from contact state — including same-turn provisional fields — or
    from the structured tool arguments). No I/O, no side effects, no
    customer copy, no tenant or vertical assumptions: everything comes from
    the bindings.
    """

    def __init__(self, tool_bindings: list[JsonDict]) -> None:
        self._facts_by_tool: dict[str, JsonDict] = {}
        self._preconditions_by_tool: dict[str, list[str]] = {}
        for binding in tool_bindings:
            if not isinstance(binding, dict):
                continue
            name = str(binding.get("name") or binding.get("tool_name") or "").strip()
            if not name:
                continue
            self._facts_by_tool[name] = dict(binding.get("dry_facts") or {})
            self._preconditions_by_tool[name] = [
                str(item) for item in binding.get("preconditions") or []
            ]

    def execute_tool(
        self,
        tool_call: LLMToolCallProposal,
        context: AgentContextPackage,
    ) -> ToolExecutionResult:
        if tool_call.tool_name not in self._facts_by_tool:
            return self._skip(tool_call, "tool_not_available")
        resolved, missing = self._resolve_preconditions(tool_call, context)
        if missing:
            return self._skip(tool_call, f"missing_precondition:{missing[0]}")
        facts = dict(self._facts_by_tool[tool_call.tool_name])
        facts.update(resolved)
        return ToolExecutionResult(
            tool_name=tool_call.tool_name,
            status="succeeded",
            facts=facts,
            citations=[f"{tool_call.tool_name}-dry-source"],
            source_refs=[tool_call.tool_name],
            is_required=tool_call.required,
            can_support_claims=True,
            source_kind="dry_facts",
        )

    def _resolve_preconditions(
        self,
        tool_call: LLMToolCallProposal,
        context: AgentContextPackage,
    ) -> tuple[JsonDict, list[str]]:
        contact_state = context.agent_identity.get("contact_state") or {}
        resolved: JsonDict = {}
        missing: list[str] = []
        for key in self._preconditions_by_tool.get(tool_call.tool_name, []):
            value = contact_state.get(key)
            if value in (None, ""):
                value = _argument_value(tool_call, key)
            if value in (None, ""):
                missing.append(key)
            else:
                resolved[key] = value
        return resolved, missing

    @staticmethod
    def _skip(tool_call: LLMToolCallProposal, error_code: str) -> ToolExecutionResult:
        return ToolExecutionResult(
            tool_name=tool_call.tool_name,
            status="skipped",
            error_code=error_code,
            is_required=tool_call.required,
            can_support_claims=False,
        )


def _argument_value(tool_call: LLMToolCallProposal, key: str) -> Any:
    arguments = tool_call.arguments or {}
    for item in arguments.get("values") or []:
        if isinstance(item, dict) and item.get("key") == key:
            for value_key in ("string_value", "number_value", "boolean_value"):
                if item.get(value_key) is not None:
                    return item[value_key]
    return arguments.get(key)


__all__ = ["DryFactsToolExecutor"]
