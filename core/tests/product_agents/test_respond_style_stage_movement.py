"""The stage movement hook is a pure no-op unless the deployment opted in
via metadata — every other tenant/deployment keeps today's behavior."""

import pytest

from atendia.product_agents.respond_style_stage_movement import (
    STAGE_MOVEMENT_FLAG,
    maybe_move_stage,
)


class _Deployment:
    def __init__(self, metadata):
        self.metadata_json = metadata


@pytest.mark.asyncio
async def test_noop_without_flag() -> None:
    # session=None proves no DB access happens on the default path
    result = await maybe_move_stage(
        None,
        deployment=_Deployment({}),
        tenant_id="00000000-0000-0000-0000-000000000001",
        conversation_id="00000000-0000-0000-0000-000000000002",
        field_values={"income_type": "nomina"},
    )
    assert result is None


@pytest.mark.asyncio
async def test_noop_with_flag_false_or_truthy_string() -> None:
    for value in (False, "true", 1, None):
        result = await maybe_move_stage(
            None,
            deployment=_Deployment({STAGE_MOVEMENT_FLAG: value}),
            tenant_id="00000000-0000-0000-0000-000000000001",
            conversation_id="00000000-0000-0000-0000-000000000002",
            field_values=None,
        )
        assert result is None
