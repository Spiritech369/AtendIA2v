"""Verify non-demo tenants get empty providers instead of 501.

Before this fix, _deps.py raised HTTPException(501) when a non-demo
tenant requested advisor/vehicle/messaging. That broke Appointments
for any tenant that wasn't `is_demo=True`.

Now those tenants receive EmptyXxxProvider which returns [] / None /
noop responses, keeping the UI usable.
"""
from __future__ import annotations

import asyncio
from uuid import uuid4

from atendia.api._deps import (
    _get_advisor_provider_for,
    _get_messaging_provider_for,
    _get_vehicle_provider_for,
)


def test_advisor_provider_demo_returns_demo():
    p = _get_advisor_provider_for(is_demo=True)
    advisors = asyncio.run(p.list_advisors())
    assert isinstance(advisors, list)
    assert len(advisors) > 0  # demo provider seeds advisors


def test_advisor_provider_non_demo_returns_empty():
    """Critical: this used to raise 501. Now returns empty list."""
    p = _get_advisor_provider_for(is_demo=False)
    advisors = asyncio.run(p.list_advisors())
    assert advisors == []
    one = asyncio.run(p.get_advisor("any-id"))
    assert one is None


def test_vehicle_provider_non_demo_returns_empty():
    p = _get_vehicle_provider_for(is_demo=False)
    assert asyncio.run(p.list_vehicles()) == []
    assert asyncio.run(p.get_vehicle("x")) is None


def test_messaging_provider_non_demo_returns_noop():
    p = _get_messaging_provider_for(is_demo=False)
    result = asyncio.run(p.send_reminder(uuid4()))
    assert result["status"] == "noop"
    assert "messaging_provider_not_configured" in result["reason"]
