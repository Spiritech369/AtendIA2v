import pytest

from atendia.sandbox.transport import CapturingArqPool


@pytest.mark.asyncio
async def test_enqueue_job_is_captured_not_sent():
    pool = CapturingArqPool()
    job = await pool.enqueue_job("send_whatsapp", {"to": "+521", "text": "hola"})
    assert job is not None  # callers expect a truthy job handle
    assert pool.captured == [("send_whatsapp", ({"to": "+521", "text": "hola"},), {})]
    assert pool.send_count == 0  # nothing actually dispatched
