from __future__ import annotations

import pytest

from tests.agent_runtime.expediente_preflight_utils import (
    field_values,
    latest_field,
    run_documental_preflight,
)


@pytest.mark.asyncio
async def test_documental_preflight_no_send() -> None:
    outputs, _interpreter = await run_documental_preflight()

    assert len(outputs) == 6
    assert all(output.actions == [] for output in outputs)
    assert all("universal_turn_trace" in output.trace_metadata for output in outputs)

    final = outputs[-1]
    checklist = latest_field(final, "requirements_checklist")
    payroll = next(
        item
        for item in checklist["items"]
        if item["key"] == "nomina_1_mes_dentro_estado_cuenta"
    )

    assert latest_field(final, "requirements_complete") is False
    assert payroll["nominas_requeridas"] == 4
    assert payroll["nominas_recibidas"] == 1
    assert payroll["nominas_faltantes"] == 3
    assert (
        "Ya tengo tu INE, comprobante, estados de cuenta y 1 recibo de nomina"
        in final.final_message
    )
    assert "faltan 3 recibos" in final.final_message
    forbidden = [
        "expediente completo",
        "ya quedo",
        "aprobado",
        "validacion final",
        "te doy continuidad",
        "reviso el contexto",
    ]
    assert not any(text in final.final_message.casefold() for text in forbidden)

    trace = final.trace_metadata["universal_turn_trace"]
    tools = {item["tool_id"]: item for item in trace["tool_results"]}
    assert tools["expediente.evaluate"]["status"] == "succeeded"
    structured = tools["expediente.evaluate"]["structured_output"]
    assert structured["contract"] == "Expedientes"
    assert structured["rules_applied"][0]["missing_count"] == 3
    assert trace["state_changes"]["summary"]["accepted_count"] >= 1
    assert not field_values(final, "human_handoff_needed")
