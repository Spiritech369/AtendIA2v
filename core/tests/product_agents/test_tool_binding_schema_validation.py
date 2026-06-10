import pytest

from atendia.product_agents.service import ProductAgentError, validate_tool_binding_schema


def test_tool_binding_schema_accepts_object_schemas() -> None:
    validate_tool_binding_schema(
        input_schema={"type": "object", "properties": {"query": {"type": "string"}}},
        output_schema={"type": "object", "properties": {"answer": {"type": "string"}}},
    )


def test_tool_binding_schema_rejects_non_object_schema_type() -> None:
    with pytest.raises(ProductAgentError):
        validate_tool_binding_schema(
            input_schema={"type": "array"},
            output_schema={"type": "object"},
        )


def test_tool_binding_schema_rejects_non_mapping_schema() -> None:
    with pytest.raises(ProductAgentError):
        validate_tool_binding_schema(
            input_schema=[],  # type: ignore[arg-type]
            output_schema={"type": "object"},
        )


def test_tool_binding_schema_rejects_non_object_properties() -> None:
    with pytest.raises(ProductAgentError):
        validate_tool_binding_schema(
            input_schema={"type": "object", "properties": []},
            output_schema={"type": "object"},
        )
