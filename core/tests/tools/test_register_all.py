import pytest

from atendia.tools import register_all_tools
from atendia.tools.registry import _registry, list_tools


@pytest.fixture(autouse=True)
def reset_registry():
    saved = dict(_registry)
    _registry.clear()
    yield
    _registry.clear()
    _registry.update(saved)


def test_register_all_tools_registers_six_tools():
    register_all_tools()
    names = list_tools()
    assert names == [
        "book_appointment",
        "escalate_to_human",
        "lookup_faq",
        "quote",
        "schedule_followup",
        "search_catalog",
    ]


def test_register_all_tools_is_idempotent():
    register_all_tools()
    register_all_tools()  # second call should not raise or duplicate
    names = list_tools()
    assert len(names) == 6
