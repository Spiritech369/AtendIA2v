import time
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from atendia.db.models import ToolCallRow
from atendia.tools.registry import get_tool


async def run_tool(
    session: AsyncSession,
    *,
    turn_trace_id: UUID,
    tool_name: str,
    inputs: dict,
) -> dict:
    tool = get_tool(tool_name)
    started = time.perf_counter()
    error = None
    output = None
    try:
        output = await tool.run(session, **inputs)
        return output
    except Exception as e:
        error = str(e)
        raise
    finally:
        latency_ms = int((time.perf_counter() - started) * 1000)
        session.add(ToolCallRow(
            id=uuid4(),
            turn_trace_id=turn_trace_id,
            tool_name=tool_name,
            input_payload=inputs,
            output_payload=output,
            latency_ms=latency_ms,
            error=error,
        ))
        await session.flush()
