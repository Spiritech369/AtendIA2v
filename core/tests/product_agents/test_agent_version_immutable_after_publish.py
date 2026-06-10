from datetime import UTC, datetime
from uuid import uuid4

import pytest

from atendia.db.models.product_agent import AgentVersion
from atendia.product_agents.service import (
    ImmutableAgentVersionError,
    ensure_version_mutable,
    mark_version_published,
)


def test_agent_version_becomes_immutable_after_publish() -> None:
    version = AgentVersion(
        tenant_id=uuid4(),
        agent_id=uuid4(),
        version_number=1,
        status="draft",
        is_immutable=False,
    )
    published_at = datetime(2026, 6, 6, tzinfo=UTC)

    mark_version_published(version, now=published_at)

    assert version.status == "published"
    assert version.is_immutable is True
    assert version.published_at == published_at
    with pytest.raises(ImmutableAgentVersionError):
        ensure_version_mutable(version)


def test_agent_version_published_status_blocks_mutation_even_without_flag() -> None:
    version = AgentVersion(
        tenant_id=uuid4(),
        agent_id=uuid4(),
        version_number=1,
        status="published",
        is_immutable=False,
    )

    with pytest.raises(ImmutableAgentVersionError):
        ensure_version_mutable(version)
