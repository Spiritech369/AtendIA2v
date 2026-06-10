from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import sys
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
CORE_ROOT = REPO_ROOT / "core"
if str(CORE_ROOT) not in sys.path:
    sys.path.insert(0, str(CORE_ROOT))

from atendia.agent_runtime import (  # noqa: E402
    AgentContextPackage,
    AgentTurnInput,
    RespondStyleLLMTurnProvider,
)


def _turn_input(text: str, *, conversation_id: str) -> AgentTurnInput:
    return AgentTurnInput(
        tenant_id="generic-tenant",
        deployment_id="generic-deployment",
        agent_id="generic-agent",
        agent_version_id="generic-version",
        runtime_mode="test_lab_no_send",
        send_mode="no_send",
        channel="manual_no_send",
        conversation_id=conversation_id,
        contact_id="generic-contact",
        inbound_text=text,
        recent_messages=[],
    )


def _context() -> AgentContextPackage:
    return AgentContextPackage(
        agent_identity={"name": "Generic AtendIA assistant", "role": "customer advisor"},
        instructions="Help customers with general information using only provided facts.",
        voice_guide={"tone": "brief, human, clear"},
        retrieved_context=[
            {
                "source_id": "generic-info",
                "title": "General service information",
                "snippet": "The team can answer questions and collect the next useful detail.",
            }
        ],
        tool_schemas=[
            {"name": "requirements.lookup", "description": "Looks up exact requirements."},
            {"name": "quote.resolve", "description": "Resolves exact prices or quotes."},
        ],
        field_policies=[
            {"field_key": "lead_intent", "writable": True},
            {"field_key": "objection", "writable": True},
        ],
        workflow_trigger_schemas=[{"binding_name": "lead_review", "enabled": True}],
        action_schemas=[{"name": "task.create", "enabled": True, "permitted": True}],
        handoff_policy={"enabled": True, "targets": ["sales", "support"]},
    )


def _api_key_from_env(
    env_file_paths: tuple[Path, ...] | None = None,
) -> tuple[str | None, str | None]:
    for env_name in ("OPENAI_API_KEY", "ATENDIA_V2_OPENAI_API_KEY"):
        value = os.getenv(env_name)
        if value:
            return value, env_name
    paths = env_file_paths or (REPO_ROOT / ".env", CORE_ROOT / ".env")
    for path in paths:
        for env_name in ("OPENAI_API_KEY", "ATENDIA_V2_OPENAI_API_KEY"):
            value = _read_env_file_value(path, env_name)
            if value:
                return value, f"{_display_path(path)}:{env_name}"
    return None, None


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return path.name


def _read_env_file_value(path: Path, env_name: str) -> str | None:
    if not path.exists():
        return None
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() != env_name:
            continue
        cleaned = value.strip().strip("'\"")
        return cleaned or None
    return None


async def main() -> int:
    api_key, env_source = _api_key_from_env()
    if not api_key:
        print(
            json.dumps(
                {
                    "decision": "RESPOND_STYLE_LLM_TURN_PROVIDER_BLOCKED_BY_OPENAI",
                    "reason": "OPENAI_API_KEY and ATENDIA_V2_OPENAI_API_KEY are not set",
                    "side_effects": {
                        "outbox": False,
                        "workflows": False,
                        "actions": False,
                    },
                },
                indent=2,
            )
        )
        return 0

    provider = RespondStyleLLMTurnProvider(api_key=api_key)
    scenarios = [
        ("lead_new_greeting", "hola"),
        ("lead_new_info", "busco info"),
        ("requirements_question", "que ocupo"),
        ("price_objection", "esta caro"),
    ]
    results: list[dict[str, Any]] = []
    context = _context()
    for index, (name, text) in enumerate(scenarios, start=1):
        decision = await provider.generate(
            turn_input=_turn_input(text, conversation_id=f"manual-{index}"),
            context=context,
        )
        results.append(
            {
                "scenario": name,
                "inbound_text": text,
                "send_decision": decision.send_decision,
                "final_message": decision.final_message,
                "validation": (
                    decision.validation.model_dump(mode="json")
                    if decision.validation is not None
                    else None
                ),
                "retry_instruction": (
                    decision.retry_instruction.model_dump(mode="json")
                    if decision.retry_instruction is not None
                    else None
                ),
                "side_effects": {
                    "outbox": False,
                    "workflows": False,
                    "actions": False,
                },
            }
        )

    print(
        json.dumps(
            {
                "decision": "RESPOND_STYLE_LLM_TURN_PROVIDER_READY",
                "mode": "no_send",
                "env_source": env_source,
                "results": results,
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
