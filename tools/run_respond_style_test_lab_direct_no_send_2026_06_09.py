from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CORE_ROOT = REPO_ROOT / "core"
if str(CORE_ROOT) not in sys.path:
    sys.path.insert(0, str(CORE_ROOT))

from atendia.agent_runtime import (  # noqa: E402
    InMemoryEvidenceSink,
    RespondStyleLLMTurnProvider,
    RespondStyleTestLabDirect,
    RespondStyleToolLoop,
    TestLabScenario,
)

sys.path.insert(0, str(REPO_ROOT / "tools"))
from run_live_simulated_channel_no_send_2026_06_09 import (  # noqa: E402
    _api_key_from_env,
    _DryFactToolExecutor,
    _generic_config,
)

SCENARIOS = [
    TestLabScenario(name="greeting_info", turns=["hola", "que opciones tienen?"]),
    TestLabScenario(
        name="chaotic_compound",
        turns=[
            "quiero la opcion estandar trabajo por mi cuenta que necesito y cuanto cuesta"
        ],
    ),
    TestLabScenario(
        name="handoff",
        turns=["quiero hablar con una persona real por favor"],
    ),
]


async def main() -> int:
    api_key, env_source = _api_key_from_env()
    if not api_key:
        print(
            json.dumps(
                {
                    "decision": "PHASE_10_BLOCKED_BY_OPENAI",
                    "reason": "OPENAI_API_KEY and ATENDIA_V2_OPENAI_API_KEY are not set",
                },
                indent=2,
            )
        )
        return 0

    sink = InMemoryEvidenceSink()
    lab = RespondStyleTestLabDirect(
        config=_generic_config(),
        tool_loop_factory=lambda: RespondStyleToolLoop(
            provider=RespondStyleLLMTurnProvider(api_key=api_key),
            executor=_DryFactToolExecutor(),
        ),
        evidence_sink=sink,
    )
    results = await lab.run_scenarios(SCENARIOS)

    all_turns = [turn for result in results for turn in result.turns]
    ready = (
        all(turn.send_decision == "no_send" for turn in all_turns)
        and all(result.outbound_outbox_writes == 0 for result in results)
        and all(not any(result.side_effects.values()) for result in results)
        and len(sink.saved) == len(SCENARIOS)
        and any(turn.simulated_outbound for turn in all_turns)
    )
    print(
        json.dumps(
            {
                "decision": (
                    "PHASE_10_RESPOND_STYLE_SIMULATED_LIVE_FIXES_AND_TESTLAB_API_READY"
                    if ready
                    else "PHASE_10_BLOCKED_BY_TEST_LAB_BEHAVIOR"
                ),
                "mode": "no_send",
                "env_source": env_source,
                "evidence_saved": len(sink.saved),
                "results": [result.model_dump(mode="json") for result in results],
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
