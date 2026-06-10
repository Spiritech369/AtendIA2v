"""Import-graph audit for the Product Agent direct route.

Single source of truth for the Customer Copy Kill Map hard block: the test
battery and Publish Control both call ``audit_direct_route_imports`` to
prove (in a fresh interpreter) that the direct route cannot load any legacy
customer-copy source.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

DIRECT_ROUTE_MODULES: tuple[str, ...] = (
    "atendia.agent_runtime.respond_style_turn_contract",
    "atendia.agent_runtime.respond_style_turn_validator",
    "atendia.agent_runtime.respond_style_llm_provider",
    "atendia.agent_runtime.respond_style_tool_loop",
    "atendia.agent_runtime.respond_style_context_builder",
    "atendia.agent_runtime.respond_style_product_agent_runtime",
    "atendia.agent_runtime.respond_style_product_agent_config_adapter",
    "atendia.agent_runtime.respond_style_live_simulated_channel",
    "atendia.agent_runtime.respond_style_test_lab_direct",
    "atendia.agent_runtime.respond_style_deployment_resolver",
    "atendia.agent_runtime.respond_style_dry_facts_executor",
)

FORBIDDEN_MODULE_FRAGMENTS: tuple[str, ...] = (
    "runner.conversation_runner",
    "runner.composer_prompts",
    "runner.composer_openai",
    "runner.response_contract",
    "runner.response_frame",
    "agent_runtime.human_response_composer",
    "agent_runtime.advisor_pipeline",
    "agent_runtime.validated_response_plan",
    "agent_runtime.conversation_progress",
    "agent_runtime.quote_safety",
    "agent_runtime.mandatory_tools",
    "agent_runtime.model_provider",
    "agent_runtime.send_adapter",
    "agent_runtime.agent_service",
    "runner.outbound_dispatcher",
    "queue.outbox",
    "workflows.engine",
)


def audit_direct_route_imports(timeout_seconds: float = 60.0) -> list[str]:
    """Imports the whole direct route in a fresh interpreter and returns the
    list of forbidden legacy modules that got loaded (empty = clean)."""
    code = (
        "import importlib, sys\n"
        + "\n".join(
            f"importlib.import_module('{module}')" for module in DIRECT_ROUTE_MODULES
        )
        + "\nprint('\\n'.join(sorted(m for m in sys.modules if m.startswith('atendia'))))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        cwd=_core_root(),
        timeout=timeout_seconds,
        check=True,
    )
    loaded_modules = result.stdout.splitlines()
    return [
        module
        for module in loaded_modules
        if any(fragment in module for fragment in FORBIDDEN_MODULE_FRAGMENTS)
    ]


def _core_root() -> str:
    # .../core/atendia/agent_runtime/respond_style_route_audit.py -> .../core
    return str(Path(__file__).resolve().parents[2])


__all__ = [
    "DIRECT_ROUTE_MODULES",
    "FORBIDDEN_MODULE_FRAGMENTS",
    "audit_direct_route_imports",
]
