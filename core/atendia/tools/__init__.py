from atendia.tools.book_appointment import BookAppointmentTool
from atendia.tools.escalate import EscalateToHumanTool
from atendia.tools.followup import ScheduleFollowupTool
from atendia.tools.lookup_faq import LookupFAQTool
from atendia.tools.quote import QuoteTool
from atendia.tools.registry import register_tool
from atendia.tools.search_catalog import SearchCatalogTool


def register_all_tools() -> None:
    for tool_cls in [
        SearchCatalogTool,
        QuoteTool,
        LookupFAQTool,
        BookAppointmentTool,
        EscalateToHumanTool,
        ScheduleFollowupTool,
    ]:
        register_tool(tool_cls())


__all__ = ["register_all_tools"]
