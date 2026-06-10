"""Parity gate: no_send Test Lab mode vs simulated live-candidate mode.

Runs the SAME scenario through the SAME direct route twice — once labeled
``no_send`` (Test Lab evidence mode) and once labeled
``live_candidate_simulated`` (delivery simulated) — with a deterministic
provider, and asserts the evidence is identical except for the send-policy
label. Both runs remain strictly no_send. This proves the future live
candidate is the same code path as Test Lab with delivery as the only
difference.
"""

from __future__ import annotations

from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from atendia.agent_runtime.respond_style_live_simulated_channel import (
    LiveSimulatedChannel,
    SimulatedTurnRecord,
)
from atendia.agent_runtime.respond_style_product_agent_config_adapter import (
    ProductAgentPublishedConfig,
)
from atendia.agent_runtime.respond_style_route_audit import audit_direct_route_imports
from atendia.agent_runtime.respond_style_tool_loop import RespondStyleToolLoop

JsonDict = dict[str, Any]

COMPARED_FIELDS = (
    "inbound_text",
    "final_message_candidate",
    "send_decision",
    "blocked_reason",
    "simulated_outbound",
    "simulated_field_writes",
    "field_update_proposals",
    "workflow_event_proposals",
    "action_proposals",
    "handoff_proposal",
)


class ToolLoopFactory(Protocol):
    def __call__(self) -> RespondStyleToolLoop: ...


class ParityDifference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    turn_number: int
    field: str
    no_send_value: Any = None
    live_candidate_value: Any = None


class ParityGateResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    parity_ok: bool
    turns_compared: int
    differences: list[ParityDifference] = Field(default_factory=list)
    both_paths_no_send: bool
    legacy_path_used: Literal[False] = False
    legacy_import_violations: list[str] = Field(default_factory=list)
    no_send_policy_labels: list[str] = Field(default_factory=list)
    live_candidate_policy_labels: list[str] = Field(default_factory=list)


async def run_parity_gate(
    *,
    config: ProductAgentPublishedConfig,
    turns: list[str],
    tool_loop_factory: ToolLoopFactory,
    audit_imports: bool = True,
) -> ParityGateResult:
    """``tool_loop_factory`` must produce a DETERMINISTIC loop per call
    (scripted provider) so both runs see identical decisions."""
    no_send_channel = LiveSimulatedChannel(
        config=config,
        tool_loop=tool_loop_factory(),
        conversation_id="parity-no-send",
        send_policy_label="no_send",
    )
    live_candidate_channel = LiveSimulatedChannel(
        config=config,
        tool_loop=tool_loop_factory(),
        conversation_id="parity-live-candidate-simulated",
        send_policy_label="live_candidate_simulated",
    )

    for inbound_text in turns:
        await no_send_channel.receive(inbound_text)
        await live_candidate_channel.receive(inbound_text)

    no_send_records = no_send_channel.records
    live_records = live_candidate_channel.records
    differences = _compare(no_send_records, live_records)

    both_no_send = all(
        record.send_decision == "no_send"
        for record in (*no_send_records, *live_records)
    )
    violations = audit_direct_route_imports() if audit_imports else []
    return ParityGateResult(
        parity_ok=not differences and both_no_send and not violations,
        turns_compared=len(no_send_records),
        differences=differences,
        both_paths_no_send=both_no_send,
        legacy_import_violations=violations,
        no_send_policy_labels=[
            str(record.send_policy.get("send_policy_label"))
            for record in no_send_records
        ],
        live_candidate_policy_labels=[
            str(record.send_policy.get("send_policy_label"))
            for record in live_records
        ],
    )


def _compare(
    no_send_records: list[SimulatedTurnRecord],
    live_records: list[SimulatedTurnRecord],
) -> list[ParityDifference]:
    differences: list[ParityDifference] = []
    if len(no_send_records) != len(live_records):
        differences.append(
            ParityDifference(
                turn_number=0,
                field="turn_count",
                no_send_value=len(no_send_records),
                live_candidate_value=len(live_records),
            )
        )
        return differences
    for left, right in zip(no_send_records, live_records, strict=True):
        for field in COMPARED_FIELDS:
            left_value = getattr(left, field)
            right_value = getattr(right, field)
            if left_value != right_value:
                differences.append(
                    ParityDifference(
                        turn_number=left.turn_number,
                        field=field,
                        no_send_value=left_value,
                        live_candidate_value=right_value,
                    )
                )
    return differences


__all__ = ["ParityDifference", "ParityGateResult", "run_parity_gate"]
