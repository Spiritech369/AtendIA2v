from atendia.tools.base import Tool, ToolNotFoundError

_registry: dict[str, Tool] = {}


def register_tool(tool: Tool) -> None:
    _registry[tool.name] = tool


def get_tool(name: str) -> Tool:
    try:
        return _registry[name]
    except KeyError as ke:
        raise ToolNotFoundError(name) from ke


def list_tools() -> list[str]:
    return sorted(_registry.keys())
