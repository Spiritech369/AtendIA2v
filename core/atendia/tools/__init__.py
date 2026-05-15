from atendia.tools.base import Tool
from atendia.tools.book_appointment import BookAppointmentTool
from atendia.tools.escalate import EscalateToHumanTool
from atendia.tools.followup import ScheduleFollowupTool
from atendia.tools.lookup_faq import LookupFAQTool
from atendia.tools.quote import QuoteTool
from atendia.tools.registry import register_tool
from atendia.tools.search_catalog import SearchCatalogTool


def register_all_tools() -> None:
    # Each entry is a concrete `Tool` subclass that implements `run`.
    # The explicit `list[type[Tool]]` annotation tells mypy the list is
    # heterogeneous over concrete subclasses, so `tool_cls()` isn't
    # confused for "instantiating the abstract base".
    tools: list[type[Tool]] = [
        SearchCatalogTool,
        QuoteTool,
        LookupFAQTool,
        BookAppointmentTool,
        EscalateToHumanTool,
        ScheduleFollowupTool,
    ]
    for tool_cls in tools:
        register_tool(tool_cls())  # type: ignore[abstract]


__all__ = ["register_all_tools"]
