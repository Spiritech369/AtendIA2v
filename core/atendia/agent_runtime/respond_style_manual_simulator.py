"""Manual live simulator over the Respond-Style direct route.

A local, operator-facing chat harness: type messages, get the simulated
reply produced by ProductAgentRuntime (context builder -> tool loop ->
validator), inspect traces and simulated state, and save evidence reports.
WhatsApp-shaped, never WhatsApp: no outbox, no delivery adapter, no
workflow/action execution, no DB writes — state lives only in memory.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from atendia.agent_runtime.respond_style_live_simulated_channel import (
    LiveSimulatedChannel,
    SimulatedTurnRecord,
)
from atendia.agent_runtime.respond_style_product_agent_config_adapter import (
    ProductAgentPublishedConfig,
)
from atendia.agent_runtime.respond_style_tool_loop import RespondStyleToolLoop

JsonDict = dict[str, Any]

COMMANDS_HELP = (
    "/exit end the session | /trace last turn trace | /state simulated state | "
    "/save write JSON+MD report | /reset restart conversation"
)


class SimulatorOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["turn", "info", "exit"]
    lines: list[str] = Field(default_factory=list)
    turn: SimulatedTurnRecord | None = None
    saved_paths: list[str] = Field(default_factory=list)


class ReportWriter(Protocol):
    def write(self, basename: str, *, json_text: str, md_text: str) -> list[str]: ...


class ManualLiveSimulator:
    """Command-driven wrapper around LiveSimulatedChannel.

    The simulator authors no customer copy: every visible candidate comes
    from the LLM decision via the direct route; blocked turns surface their
    structured reason instead of any fallback text.
    """

    def __init__(
        self,
        *,
        config: ProductAgentPublishedConfig,
        tool_loop_factory: Callable[[], RespondStyleToolLoop],
        report_writer: ReportWriter,
        run_label: str,
        conversation_label: str = "manual-sim",
    ) -> None:
        self._config = config
        self._tool_loop_factory = tool_loop_factory
        self._report_writer = report_writer
        self._run_label = run_label
        self._conversation_label = conversation_label
        self._session_index = 0
        self._channel = self._new_channel()

    @property
    def channel(self) -> LiveSimulatedChannel:
        return self._channel

    async def handle_input(self, raw_text: str) -> SimulatorOutput:
        text = raw_text.strip()
        if not text:
            return SimulatorOutput(kind="info", lines=[COMMANDS_HELP])
        if text.startswith("/"):
            return await self._handle_command(text)
        record = await self._channel.receive(text)
        return SimulatorOutput(
            kind="turn",
            lines=_format_turn(record),
            turn=record,
        )

    async def _handle_command(self, command: str) -> SimulatorOutput:
        name = command.split()[0].casefold()
        if name == "/exit":
            return SimulatorOutput(kind="exit", lines=["session ended"])
        if name == "/trace":
            records = self._channel.records
            if not records:
                return SimulatorOutput(kind="info", lines=["no turns yet"])
            return SimulatorOutput(
                kind="info",
                lines=[json.dumps(records[-1].trace, indent=2, ensure_ascii=False)],
            )
        if name == "/state":
            return SimulatorOutput(
                kind="info",
                lines=[
                    json.dumps(
                        {
                            "simulated_fields": self._channel.field_values,
                            "transcript_messages": len(self._channel.transcript),
                            "turns": len(self._channel.records),
                        },
                        indent=2,
                        ensure_ascii=False,
                    )
                ],
            )
        if name == "/save":
            paths = self.save_report()
            return SimulatorOutput(
                kind="info",
                lines=[f"saved: {path}" for path in paths],
                saved_paths=paths,
            )
        if name == "/reset":
            self._session_index += 1
            self._channel = self._new_channel()
            return SimulatorOutput(kind="info", lines=["conversation reset"])
        return SimulatorOutput(
            kind="info",
            lines=[f"unknown command {name}", COMMANDS_HELP],
        )

    def save_report(self) -> list[str]:
        payload = self.report_payload()
        json_text = json.dumps(payload, indent=2, ensure_ascii=False, default=str)
        md_text = _report_markdown(payload)
        basename = f"manual_live_simulator_run_{self._run_label}"
        return self._report_writer.write(basename, json_text=json_text, md_text=md_text)

    def report_payload(self) -> JsonDict:
        records = self._channel.records
        summary = self._channel.summary().model_dump(mode="json")
        failures = [
            {
                "turn": record.turn_number,
                "inbound": record.inbound_text,
                "no_send_reason": record.blocked_reason,
            }
            for record in records
            if record.blocked_reason is not None
        ]
        return {
            "decision_context": "MANUAL_LIVE_SIMULATOR_NO_SEND",
            "run_label": self._run_label,
            "agent": {
                "tenant_id": self._config.tenant_id,
                "agent_id": self._config.agent_id,
                "agent_version_id": self._config.agent_version_id,
            },
            "mode": "no_send",
            "turns": [record.model_dump(mode="json") for record in records],
            "transcript": self._channel.transcript,
            "simulated_fields_final": self._channel.field_values,
            "failures": failures,
            "summary": {
                **summary,
                "outbound_outbox_writes": 0,
                "side_effects": {
                    "delivery": False,
                    "workflows": False,
                    "actions": False,
                    "field_writes": False,
                },
            },
        }

    def _new_channel(self) -> LiveSimulatedChannel:
        return LiveSimulatedChannel(
            config=self._config,
            tool_loop=self._tool_loop_factory(),
            conversation_id=f"{self._conversation_label}-{self._session_index}",
        )


def _format_turn(record: SimulatedTurnRecord) -> list[str]:
    lines = [
        f"inbound_text: {record.inbound_text}",
        f"simulated_final_message: {record.final_message_candidate or '(none)'}",
        f"send_decision: {record.send_decision}",
    ]
    if record.blocked_reason:
        lines.append(f"no_send_reason: {record.blocked_reason}")
    tools_requested = [item.get("tool_name") for item in record.tool_results]
    lines.append(f"tools_requested: {tools_requested or '[]'}")
    lines.append(
        "tool_results: "
        + json.dumps(
            [
                {"tool_name": item.get("tool_name"), "status": item.get("status")}
                for item in record.tool_results
            ],
            ensure_ascii=False,
        )
    )
    lines.append(
        "field_proposals: "
        + json.dumps(record.field_update_proposals, ensure_ascii=False, default=str)
    )
    lines.append(
        "simulated_fields_after_turn: "
        + json.dumps(record.simulated_field_writes, ensure_ascii=False, default=str)
    )
    lines.append(
        "workflow_proposals: "
        + json.dumps(record.workflow_event_proposals, ensure_ascii=False, default=str)
    )
    lines.append(
        "handoff_proposal: "
        + json.dumps(record.handoff_proposal, ensure_ascii=False, default=str)
    )
    lines.append(
        "validator_result: "
        + json.dumps(
            {
                "status": record.validation_result.get("status"),
                "blocked_reason": record.validation_result.get("blocked_reason"),
            },
            ensure_ascii=False,
        )
    )
    return lines


def _report_markdown(payload: JsonDict) -> str:
    lines = [
        "# Manual Live Simulator Run (no-send)",
        "",
        f"Run: {payload['run_label']}",
        f"Agent: {payload['agent']['agent_id']} (version {payload['agent']['agent_version_id']})",
        f"Tenant: {payload['agent']['tenant_id']}",
        "Mode: no_send | outbox=0 | side_effects=0",
        "",
        "## Transcript",
        "",
    ]
    for message in payload["transcript"]:
        prefix = "C>" if message["role"] == "customer" else "A>"
        lines.append(f"- {prefix} {message['text']}")
    lines += ["", "## Turns", ""]
    for turn in payload["turns"]:
        lines.append(
            f"- turn {turn['turn_number']}: send_decision={turn['send_decision']}"
            f", outbound={'yes' if turn['simulated_outbound'] else 'no'}"
            + (
                f", no_send_reason={turn['blocked_reason']}"
                if turn["blocked_reason"]
                else ""
            )
        )
    if payload["failures"]:
        lines += ["", "## Failures", ""]
        for failure in payload["failures"]:
            lines.append(
                f"- turn {failure['turn']}: {failure['no_send_reason']}"
            )
    lines += [
        "",
        "## Summary",
        "",
        "```json",
        json.dumps(payload["summary"], indent=2, ensure_ascii=False),
        "```",
        "",
    ]
    return "\n".join(lines)


__all__ = ["COMMANDS_HELP", "ManualLiveSimulator", "SimulatorOutput"]
