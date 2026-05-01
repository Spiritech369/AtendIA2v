import pytest

from atendia.channels.base import OutboundMessage
from atendia.queue.enqueue import enqueue_outbound


@pytest.mark.asyncio
async def test_enqueue_outbound_returns_job_id(arq_redis):
    msg = OutboundMessage(
        tenant_id="dinamomotos",
        to_phone_e164="+5215555550160",
        text="hola desde el bot",
        idempotency_key="test_t16_idem_a",
    )
    # Clear any leftover job from a previous run
    await arq_redis.delete("arq:job:test_t16_idem_a")

    job_id = await enqueue_outbound(arq_redis, msg)
    assert job_id == "test_t16_idem_a"

    # Verify the job exists in Redis (arq stores jobs with key arq:job:<job_id>)
    exists = await arq_redis.exists("arq:job:test_t16_idem_a")
    assert exists == 1


@pytest.mark.asyncio
async def test_enqueue_outbound_idempotent(arq_redis):
    """Two enqueues with the same idempotency_key result in one job (arq dedupes)."""
    await arq_redis.delete("arq:job:test_t16_idem_b")

    msg = OutboundMessage(
        tenant_id="t",
        to_phone_e164="+5215555550161",
        text="dup",
        idempotency_key="test_t16_idem_b",
    )

    job_id_1 = await enqueue_outbound(arq_redis, msg)
    job_id_2 = await enqueue_outbound(arq_redis, msg)
    assert job_id_1 == job_id_2 == "test_t16_idem_b"


@pytest.mark.asyncio
async def test_enqueue_outbound_serializes_template_payload(arq_redis):
    """A template OutboundMessage round-trips through arq enqueue."""
    await arq_redis.delete("arq:job:test_t16_idem_tpl")

    msg = OutboundMessage(
        tenant_id="t",
        to_phone_e164="+5215555550162",
        template={"name": "lead_warm_v2", "language": {"code": "es_MX"}, "components": []},
        idempotency_key="test_t16_idem_tpl",
    )
    job_id = await enqueue_outbound(arq_redis, msg)
    assert job_id == "test_t16_idem_tpl"
    assert await arq_redis.exists("arq:job:test_t16_idem_tpl") == 1
