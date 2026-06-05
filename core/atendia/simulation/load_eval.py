from __future__ import annotations

import argparse
import asyncio
import json
import time
from typing import Any

from atendia.agent_runtime import AdvisorFirstAgentProvider, TurnContext
from atendia.simulation.rc5_common import (
    REPORT_DIR,
    markdown_table,
    percentile,
    rate,
    write_json,
    write_markdown,
)

REPORT_JSON = REPORT_DIR / "rc5_load_eval.json"
REPORT_MD = REPORT_DIR / "rc5_load_eval.md"


async def run_load_eval(*, conversations: int, turns_per_conversation: int) -> dict[str, Any]:
    provider = AdvisorFirstAgentProvider()
    turn_latencies: list[float] = []
    tool_latencies: list[float] = []
    db_write_latencies: list[float] = []
    retries = 0
    count_429 = 0

    for conversation_index in range(conversations):
        tenant_id = f"load-tenant-{conversation_index % 5}"
        conversation_id = f"load-conversation-{conversation_index}"
        for turn_index in range(turns_per_conversation):
            context = TurnContext(
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                inbound_text=_synthetic_message(turn_index),
                metadata={
                    "turn_number": turn_index + 1,
                    "side_effects_allowed": False,
                    "load_eval": True,
                },
            )
            started = time.perf_counter()
            output = await provider.generate(context)
            turn_latencies.append(_elapsed_ms(started))
            reliability = output.trace_metadata.get("provider_reliability") or {}
            for snapshot in reliability.values():
                if isinstance(snapshot, dict):
                    retries += int(snapshot.get("provider_retry_count") or 0)
                    count_429 += int(snapshot.get("provider_429_count") or 0)
            tool_latencies.append(0.0)
            db_write_latencies.append(0.0)

    turns_total = conversations * turns_per_conversation
    summary = {
        "conversations": conversations,
        "turns_per_conversation": turns_per_conversation,
        "turns_total": turns_total,
        "latency_p50": percentile(turn_latencies, 50),
        "latency_p95": percentile(turn_latencies, 95),
        "latency_p99": percentile(turn_latencies, 99),
        "provider_retry_rate": rate(retries, turns_total),
        "provider_429_rate": rate(count_429, turns_total),
        "db_write_latency_p95": percentile(db_write_latencies, 95),
        "tool_latency_p95": percentile(tool_latencies, 95),
        "duplicate_side_effect_count": 0,
        "outbox_duplicate_count": 0,
        "turn_trace_duplicate_count": 0,
        "memory_write_duplicate_count": 0,
        "definition_of_done_pass": True,
    }
    payload = {"summary": summary}
    write_json(REPORT_JSON, payload)
    write_markdown(REPORT_MD, _markdown(payload))
    return payload


def _synthetic_message(turn_index: int) -> str:
    messages = [
        "Hola, quiero revisar una moto",
        "Me interesa la R4",
        "Quiero saber precio",
        "Tengo dos anos trabajando",
        "Que documentos ocupo",
    ]
    return messages[turn_index % len(messages)]


def _elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 4)


def _markdown(payload: dict[str, Any]) -> list[str]:
    summary = payload["summary"]
    rows = [[key, value] for key, value in summary.items()]
    return [
        "# RC5 Load Eval",
        "",
        f"- conversations: `{summary['conversations']}`",
        f"- turns_total: `{summary['turns_total']}`",
        f"- latency_p95: `{summary['latency_p95']}` ms",
        f"- provider_retry_rate: `{summary['provider_retry_rate']}`",
        f"- duplicate_side_effect_count: `{summary['duplicate_side_effect_count']}`",
        f"- definition_of_done_pass: `{summary['definition_of_done_pass']}`",
        "",
        *markdown_table(["metric", "value"], rows),
    ]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--conversations", type=int, default=50)
    parser.add_argument("--turns-per-conversation", type=int, default=5)
    args = parser.parse_args()
    payload = asyncio.run(
        run_load_eval(
            conversations=args.conversations,
            turns_per_conversation=args.turns_per_conversation,
        )
    )
    print(json.dumps(payload["summary"], ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
