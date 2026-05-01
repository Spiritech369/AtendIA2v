import pytest

from atendia.tools.base import Tool, ToolNotFoundError
from atendia.tools.registry import register_tool, get_tool, _registry


@pytest.fixture(autouse=True)
def clean_registry():
    saved = dict(_registry)
    _registry.clear()
    yield
    _registry.clear()
    _registry.update(saved)


def test_register_and_get_tool():
    class FakeTool(Tool):
        name = "fake"
        async def run(self, session, **kwargs):
            return {"ok": True}

    register_tool(FakeTool())
    t = get_tool("fake")
    assert t.name == "fake"


def test_get_unknown_tool_raises():
    with pytest.raises(ToolNotFoundError):
        get_tool("nonexistent")
