from arq.connections import ArqRedis

from atendia.channels.base import OutboundMessage


async def enqueue_outbound(redis: ArqRedis, msg: OutboundMessage) -> str:
    """Enqueue an outbound send job. Returns the arq job id (always == msg.idempotency_key).

    arq dedupes by `_job_id`: calling this twice with the same `idempotency_key` results
    in one queued job (the second call returns None and we fall back to the key).
    """
    job = await redis.enqueue_job(
        "send_outbound",  # name of the worker function (defined in T17)
        msg.model_dump(mode="json"),
        _job_id=msg.idempotency_key,
    )
    if job is None:
        # already enqueued (idempotency hit)
        return msg.idempotency_key
    return job.job_id
