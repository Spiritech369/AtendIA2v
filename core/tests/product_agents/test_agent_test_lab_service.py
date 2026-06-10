from uuid import uuid4

import pytest

from atendia.db.models.agent import Agent
from atendia.db.models.product_agent import AgentTestScenario, AgentTestSuite, AgentVersion
from atendia.product_agents import service


class FakeScalarResult:
    def __init__(self, values):
        self._values = values

    def all(self):
        return self._values


class FakeResult:
    def __init__(self, scalar=None, values=None):
        self._scalar = scalar
        self._values = values or []

    def scalar_one_or_none(self):
        return self._scalar

    def scalars(self):
        return FakeScalarResult(self._values)


class FakeSession:
    def __init__(self, *results):
        self.results = list(results)
        self.added = []
        self.flush_count = 0

    async def execute(self, _statement):
        if not self.results:
            raise AssertionError("unexpected execute call")
        return self.results.pop(0)

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        self.flush_count += 1


def _agent(tenant_id):
    return Agent(id=uuid4(), tenant_id=tenant_id, name="Builder", role="support", status="draft")


def _version(tenant_id, agent_id):
    return AgentVersion(
        id=uuid4(),
        tenant_id=tenant_id,
        agent_id=agent_id,
        version_number=1,
        status="draft",
        is_immutable=False,
    )


def _suite(tenant_id, version_id):
    return AgentTestSuite(
        id=uuid4(),
        tenant_id=tenant_id,
        agent_version_id=version_id,
        name="Readiness",
        mode="draft_validation",
        status="draft",
        metadata_json={},
    )


@pytest.mark.asyncio
async def test_test_suite_crud_is_version_and_tenant_scoped() -> None:
    tenant_id = uuid4()
    agent = _agent(tenant_id)
    version = _version(tenant_id, agent.id)
    existing = _suite(tenant_id, version.id)

    suites = await service.list_agent_test_suites(
        FakeSession(FakeResult(version), FakeResult(values=[existing])),
        tenant_id=tenant_id,
        version_id=version.id,
    )
    assert suites == [existing]

    session = FakeSession(FakeResult(version))
    created = await service.create_agent_test_suite(
        session,
        tenant_id=tenant_id,
        version_id=version.id,
        name="Regression",
        mode="regression",
        metadata={"owner": "qa"},
    )
    assert created.name == "Regression"
    assert created.mode == "regression"
    assert created.metadata_json == {"owner": "qa"}
    assert session.added == [created]


@pytest.mark.asyncio
async def test_test_suite_rejects_invalid_mode_and_metadata() -> None:
    tenant_id = uuid4()
    version_id = uuid4()
    with pytest.raises(service.TestLabValidationError, match="mode"):
        await service.create_agent_test_suite(
            FakeSession(FakeResult(_version(tenant_id, uuid4()))),
            tenant_id=tenant_id,
            version_id=version_id,
            name="Bad",
            mode="live_smoke",
            metadata={},
        )
    with pytest.raises(service.TestLabValidationError, match="metadata"):
        await service.create_agent_test_suite(
            FakeSession(FakeResult(_version(tenant_id, uuid4()))),
            tenant_id=tenant_id,
            version_id=version_id,
            name="Bad",
            mode="draft_validation",
            metadata=[],  # type: ignore[arg-type]
        )


@pytest.mark.asyncio
async def test_get_test_suite_for_tenant_rejects_missing_suite() -> None:
    with pytest.raises(service.ProductAgentNotFoundError, match="test suite"):
        await service.get_agent_test_suite_for_tenant(
            FakeSession(FakeResult(None)),
            tenant_id=uuid4(),
            suite_id=uuid4(),
        )


@pytest.mark.asyncio
async def test_test_scenario_crud_validates_turns_expected_and_metadata() -> None:
    tenant_id = uuid4()
    suite = _suite(tenant_id, uuid4())
    scenario = AgentTestScenario(
        id=uuid4(),
        tenant_id=tenant_id,
        test_suite_id=suite.id,
        name="Happy path",
        turns=[{"inbound_text": "Hola"}],
        expected={"send_status": "no_send"},
        status="draft",
        metadata_json={},
    )

    scenarios = await service.list_agent_test_scenarios(
        FakeSession(FakeResult(suite), FakeResult(values=[scenario])),
        tenant_id=tenant_id,
        suite_id=suite.id,
    )
    assert scenarios == [scenario]

    session = FakeSession(FakeResult(suite))
    created = await service.create_agent_test_scenario(
        session,
        tenant_id=tenant_id,
        suite_id=suite.id,
        name="One turn",
        turns=[{"text": "Hola"}],
        expected={"final_messages": ["Va."]},
        metadata={"source": "manual"},
    )
    assert created.turns == [{"text": "Hola"}]
    assert created.expected == {"final_messages": ["Va."]}
    assert session.added == [created]


@pytest.mark.asyncio
async def test_test_scenario_rejects_invalid_payloads() -> None:
    tenant_id = uuid4()
    suite = _suite(tenant_id, uuid4())

    for turns, expected, metadata, match in [
        ("hola", {}, {}, "JSON list"),
        ([], {}, {}, "at least one"),
        (["hola"], {}, {}, "JSON object"),
        ([{}], {}, {}, "inbound"),
        ([{"message": "Hola", "attachments": {}}], {}, {}, "attachments"),
        ([{"message": "Hola", "expected": []}], {}, {}, "turn expected"),
        ([{"message": "Hola"}], [], {}, "expected"),
        ([{"message": "Hola"}], {"turns": {}}, {}, "expected turns"),
        ([{"message": "Hola"}], {"turns": ["bad"]}, {}, "expected turn"),
        ([{"message": "Hola"}], {"expected_tools": "catalog.search"}, {}, "expected_tools"),
        ([{"message": "Hola"}], {}, [], "metadata"),
    ]:
        with pytest.raises(service.TestLabValidationError, match=match):
            await service.create_agent_test_scenario(
                FakeSession(FakeResult(suite)),
                tenant_id=tenant_id,
                suite_id=suite.id,
                name="Bad",
                turns=turns,  # type: ignore[arg-type]
                expected=expected,  # type: ignore[arg-type]
                metadata=metadata,  # type: ignore[arg-type]
            )


@pytest.mark.asyncio
async def test_latest_test_run_and_run_record_defaults() -> None:
    tenant_id = uuid4()
    suite = _suite(tenant_id, uuid4())
    run = service.create_agent_test_run_record(
        tenant_id=tenant_id,
        agent_version_id=suite.agent_version_id,
        suite_id=suite.id,
        mode="no_send",
        review_required=True,
        created_by_user_id=uuid4(),
    )
    latest = await service.get_latest_agent_test_run(
        FakeSession(FakeResult(suite), FakeResult(run)),
        tenant_id=tenant_id,
        suite_id=suite.id,
    )
    assert latest is run
    assert run.status == "running"
    assert run.outbox_audit_result == {"status": "not_checked"}

    with pytest.raises(service.TestLabValidationError, match="mode"):
        service.create_agent_test_run_record(
            tenant_id=tenant_id,
            agent_version_id=suite.agent_version_id,
            suite_id=suite.id,
            mode="live",
            review_required=True,
            created_by_user_id=None,
        )
