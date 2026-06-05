"""Agent-first runtime v2 contracts and orchestration.

This package is intentionally side-effect free: it does not send WhatsApp
messages, persist outbound rows, or mutate customer/lifecycle state.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

from atendia.agent_runtime.action_registry import (
    ActionRegistry,
    default_action_registry,
)
from atendia.agent_runtime.canonical import (
    AliasMap,
    CanonicalProduct,
    CanonicalProductReference,
    QuoteSnapshot,
    SKUIndex,
)
from atendia.agent_runtime.policy_validator import PolicyValidationError, PolicyValidator
from atendia.agent_runtime.schemas import (
    ActionDefinition,
    ActionRequest,
    ActionResult,
    AdvisorBrainDecision,
    AdvisorBrainStateChange,
    AdvisorBrainToolRequest,
    ConversationMemoryContext,
    FieldUpdate,
    LifecycleUpdate,
    TenantRuntimeConfigContext,
    ToolExecutionResult,
    TurnContext,
    TurnInput,
    TurnOutput,
)

_LAZY_EXPORTS = {
    "AGENT_WORKFLOW_EVENT_TYPES": "atendia.agent_runtime.workflow_events",
    "AdvisorBrainProvider": "atendia.agent_runtime.advisor_pipeline",
    "AdvisorFirstAgentProvider": "atendia.agent_runtime.advisor_pipeline",
    "AgentModelProvider": "atendia.agent_runtime.model_provider",
    "AgentRuntime": "atendia.agent_runtime.runtime",
    "AgentWorkflowEvent": "atendia.agent_runtime.workflow_events",
    "AgentWorkflowEventEmitter": "atendia.agent_runtime.workflow_events",
    "AgentRuntimeV2PilotPolicyService": "atendia.agent_runtime.pilot_policy",
    "BusinessEvent": "atendia.agent_runtime.business_events",
    "BusinessEventBundle": "atendia.agent_runtime.business_events",
    "ContextBuilder": "atendia.agent_runtime.context_builder",
    "DeterministicAgentProvider": "atendia.agent_runtime.runtime",
    "DeterministicAdvisorBrain": "atendia.agent_runtime.advisor_pipeline",
    "MockAgentProvider": "atendia.agent_runtime.model_provider",
    "MandatoryToolApplyResult": "atendia.agent_runtime.mandatory_tools",
    "MandatoryToolEvaluation": "atendia.agent_runtime.mandatory_tools",
    "MandatoryToolGuard": "atendia.agent_runtime.mandatory_tools",
    "NoopToolLayer": "atendia.agent_runtime.advisor_pipeline",
    "OpenAIAgentProvider": "atendia.agent_runtime.model_provider",
    "PostTurnActionExecutor": "atendia.agent_runtime.post_turn_executor",
    "ProviderReliabilityConfig": "atendia.agent_runtime.provider_reliability",
    "ProviderReliabilityLayer": "atendia.agent_runtime.provider_reliability",
    "ProviderRetryExhaustedError": "atendia.agent_runtime.provider_reliability",
    "RolloutDecision": "atendia.agent_runtime.rollout_policy",
    "RolloutPolicy": "atendia.agent_runtime.rollout_policy",
    "RolloutPolicyService": "atendia.agent_runtime.rollout_policy",
    "SafeFallbackAgentProvider": "atendia.agent_runtime.model_provider",
    "DeterministicStateWriter": "atendia.agent_runtime.state_writer",
    "StructuredRuntimeComposer": "atendia.agent_runtime.advisor_pipeline",
    "StateWriteResult": "atendia.agent_runtime.state_writer",
    "AgentRuntimeShadowService": "atendia.agent_runtime.shadow_service",
    "ShadowRunResult": "atendia.agent_runtime.shadow_service",
    "TenantDomainContract": "atendia.agent_runtime.tenant_domain_contract",
    "TenantDomainContractLoadResult": "atendia.agent_runtime.tenant_domain_contract",
    "TenantDomainField": "atendia.agent_runtime.tenant_domain_contract",
    "TenantDomainTool": "atendia.agent_runtime.tenant_domain_contract",
    "TurnOutputDraft": "atendia.agent_runtime.model_provider",
    "ToolRequirementDecision": "atendia.agent_runtime.mandatory_tools",
    "ToolRequirementRule": "atendia.agent_runtime.mandatory_tools",
    "WorkflowResult": "atendia.agent_runtime.business_events",
    "build_universal_turn_trace": "atendia.agent_runtime.universal_turn_trace",
    "agent_model_provider_enabled": "atendia.agent_runtime.model_provider",
    "attach_universal_turn_trace": "atendia.agent_runtime.universal_turn_trace",
    "build_agent_turn_provider": "atendia.agent_runtime.model_provider",
    "derive_business_event_bundle": "atendia.agent_runtime.business_events",
    "why_answer_from_universal_trace": "atendia.agent_runtime.universal_turn_trace",
}

__all__ = [
    "AGENT_WORKFLOW_EVENT_TYPES",
    "ActionDefinition",
    "ActionRegistry",
    "ActionRequest",
    "ActionResult",
    "AdvisorBrainDecision",
    "AdvisorBrainStateChange",
    "AdvisorBrainToolRequest",
    "AgentModelProvider",
    "AgentRuntime",
    "AgentRuntimeShadowService",
    "AgentRuntimeV2PilotPolicyService",
    "AgentWorkflowEvent",
    "AgentWorkflowEventEmitter",
    "AliasMap",
    "BusinessEvent",
    "BusinessEventBundle",
    "CanonicalProduct",
    "CanonicalProductReference",
    "ContextBuilder",
    "ConversationMemoryContext",
    "DeterministicAdvisorBrain",
    "DeterministicAgentProvider",
    "DeterministicStateWriter",
    "FieldUpdate",
    "LifecycleUpdate",
    "MandatoryToolApplyResult",
    "MandatoryToolEvaluation",
    "MandatoryToolGuard",
    "MockAgentProvider",
    "NoopToolLayer",
    "OpenAIAgentProvider",
    "PolicyValidationError",
    "PolicyValidator",
    "PostTurnActionExecutor",
    "ProviderReliabilityConfig",
    "ProviderReliabilityLayer",
    "ProviderRetryExhaustedError",
    "QuoteSnapshot",
    "RolloutDecision",
    "RolloutPolicy",
    "RolloutPolicyService",
    "SKUIndex",
    "SafeFallbackAgentProvider",
    "ShadowRunResult",
    "TenantDomainContract",
    "TenantDomainContractLoadResult",
    "TenantDomainField",
    "TenantDomainTool",
    "TenantRuntimeConfigContext",
    "ToolExecutionResult",
    "ToolRequirementDecision",
    "ToolRequirementRule",
    "TurnContext",
    "TurnInput",
    "TurnOutput",
    "TurnOutputDraft",
    "WorkflowResult",
    "agent_model_provider_enabled",
    "attach_universal_turn_trace",
    "build_agent_turn_provider",
    "build_universal_turn_trace",
    "default_action_registry",
    "derive_business_event_bundle",
    "why_answer_from_universal_trace",
]


def __getattr__(name: str) -> Any:
    module_name = _LAZY_EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module 'atendia.agent_runtime' has no attribute {name!r}")
    value = getattr(import_module(module_name), name)
    globals()[name] = value
    return value
