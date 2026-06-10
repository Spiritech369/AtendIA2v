from atendia.agent_runtime.context_builder import (
    _runtime_config_with_product_agent_overlay,
    _tenant_config_from_runtime_config,
)


def test_product_agent_runtime_overlay_loads_contract_only_for_no_send_adapter() -> None:
    contract = _contract("tenant-1", domain="generic_lead_qualification")

    runtime_config = _runtime_config_with_product_agent_overlay(
        {},
        {
            "product_agent_runtime_adapter": True,
            "send_mode": "no_send",
            "tenant_domain_contract": contract,
        },
    )

    tenant_config = _tenant_config_from_runtime_config(
        runtime_config,
        tenant_id="tenant-1",
        agent_id="agent-1",
    )
    assert tenant_config.safe_mode is False
    assert tenant_config.domain == "generic_lead_qualification"
    assert tenant_config.metadata["product_agent_runtime_contract_overlay"] is True


def test_product_agent_runtime_overlay_ignored_outside_no_send_adapter() -> None:
    contract = _contract("tenant-1", domain="generic_lead_qualification")

    runtime_config = _runtime_config_with_product_agent_overlay(
        {},
        {
            "product_agent_runtime_adapter": True,
            "send_mode": "live",
            "tenant_domain_contract": contract,
        },
    )

    tenant_config = _tenant_config_from_runtime_config(
        runtime_config,
        tenant_id="tenant-1",
        agent_id="agent-1",
    )
    assert runtime_config == {}
    assert tenant_config.safe_mode is True
    assert tenant_config.metadata["tenant_domain_contract"]["reason"] == "missing_contract"


def test_product_agent_runtime_overlay_does_not_replace_tenant_contract() -> None:
    tenant_contract = _contract("tenant-1", domain="appointment_services")
    product_contract = _contract("tenant-1", domain="generic_lead_qualification")

    runtime_config = _runtime_config_with_product_agent_overlay(
        {"tenant_domain_contract": tenant_contract},
        {
            "product_agent_runtime_adapter": True,
            "send_mode": "no_send",
            "tenant_domain_contract": product_contract,
        },
    )

    tenant_config = _tenant_config_from_runtime_config(
        runtime_config,
        tenant_id="tenant-1",
        agent_id="agent-1",
    )
    assert tenant_config.safe_mode is False
    assert tenant_config.domain == "appointment_services"
    assert "product_agent_runtime_contract_overlay" not in tenant_config.metadata


def _contract(tenant_id: str, *, domain: str) -> dict:
    return {
        "contract_version": "1.0",
        "tenant_id": tenant_id,
        "agent_id": "agent-1",
        "domain": domain,
        "tools": [{"tool_id": "faq.lookup", "topic": "faq"}],
    }
