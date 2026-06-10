from __future__ import annotations

from tests.agent_runtime.expediente_preflight_utils import dinamo_tenant_runtime_config


def test_expediente_contract_loader_exposes_required_document_tools() -> None:
    config = dinamo_tenant_runtime_config()

    assert config.field_metadata["requirements_complete"]["allowed_sources"] == [
        "expediente.evaluate"
    ]
    assert config.field_metadata["requirements_complete"]["required_tools"] == [
        "expediente.evaluate"
    ]
    assert "document.check" in config.tool_metadata
    assert "expediente.evaluate" in config.tool_metadata
