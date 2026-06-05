from __future__ import annotations

import asyncio

import pytest

from atendia.simulation import dinamo_openai_common as common


class _FakeSession:
    closed = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        _FakeSession.closed += 1

    async def rollback(self):
        return None


def _session_factory():
    return _FakeSession()


@pytest.mark.asyncio
async def test_precheck_retry_can_run_three_times_without_leaking_sessions(monkeypatch):
    calls = 0
    _FakeSession.closed = 0

    async def _loader(session, *, settings):
        nonlocal calls
        calls += 1
        return {"critical_passed": True, "session": session.__class__.__name__}

    monkeypatch.setattr(common, "load_dinamo_precheck", _loader)

    for _ in range(3):
        result = await common.load_dinamo_precheck_with_retry(
            _session_factory,
            settings=object(),
            timeout_s=1,
        )
        assert result["critical_passed"] is True

    assert calls == 3
    assert _FakeSession.closed == 3


@pytest.mark.asyncio
async def test_precheck_retry_timeout_has_clear_error(monkeypatch):
    async def _loader(session, *, settings):
        await asyncio.sleep(0.05)
        return {"critical_passed": True}

    monkeypatch.setattr(common, "load_dinamo_precheck", _loader)

    with pytest.raises(RuntimeError, match="dinamo precheck failed after 2 attempts"):
        await common.load_dinamo_precheck_with_retry(
            _session_factory,
            settings=object(),
            attempts=2,
            timeout_s=0.001,
            backoff_s=0,
        )
