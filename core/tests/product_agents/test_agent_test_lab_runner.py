from uuid import uuid4

import pytest

from atendia.agent_runtime.agent_service import AgentServiceResult
from atendia.agent_runtime.schemas import TurnContext, TurnOutput
from atendia.agent_runtime.send_adapter import SendAdapterResult
from atendia.agent_runtime.send_policy import PreparedSendDecision
from atendia.db.models.product_agent import AgentTestRun, AgentTestScenario, AgentTestSuite
from atendia.product_agents import runtime_adapter, test_lab


class FakeSession:
    def __init__(self) -> None:
        self.added = []
        self.flush_count = 0

    def add(self, obj) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        self.flush_count += 1


class FakeScalarOneResult:
    def __init__(self, value) -> None:
        self.value = value

    def scalar_one(self):
        return self.value


class FakeScalarOneOrNoneResult:
    def __init__(self, value) -> None:
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class FakeMappingsResult:
    def __init__(self, value) -> None:
        self.value = value

    def mappings(self):
        return self

    def first(self):
        return self.value


class FakeSqlSession:
    def __init__(self, *values) -> None:
        self.values = list(values)
        self.calls = []

    async def execute(self, statement, params=None):
        self.calls.append((str(statement), params))
        if not self.values:
            raise AssertionError("unexpected SQL execute call")
        return FakeScalarOneResult(self.values.pop(0))


class FakeRuntimeSqlSession(FakeSession):
    def __init__(
        self,
        *,
        agent_id,
        runtime_contract_ready: bool = True,
        product_contract=None,
        tenant_config=None,
        version_exists: bool = True,
    ) -> None:
        super().__init__()
        self.agent_id = agent_id
        self.runtime_contract_ready = runtime_contract_ready
        self.product_contract = product_contract
        self.tenant_config = tenant_config if tenant_config is not None else {}
        self.version_exists = version_exists
        self.sql_calls = []

    async def execute(self, statement, params=None):
        sql = str(statement)
        self.sql_calls.append((sql, params))
        if "FROM agent_versions" in sql:
            if not self.version_exists:
                return FakeMappingsResult(None)
            snapshot = {}
            if self.runtime_contract_ready:
                snapshot["tenant_domain_contract"] = (
                    self.product_contract
                    if self.product_contract is not None
                    else {
                        "contract_version": "1.0",
                        "domain": "generic_lead_qualification",
                    }
                )
            return FakeMappingsResult(
                {
                    "agent_id": self.agent_id,
                    "snapshot": snapshot,
                    "tool_policy": {},
                    "knowledge_policy": {},
                    "field_policy": {},
                    "safety_policy": {},
                }
            )
        if "SELECT config FROM tenants" in sql:
            return FakeScalarOneOrNoneResult(self.tenant_config)
        return FakeScalarOneResult(None)


class FakeAgentService:
    def __init__(
        self,
        *,
        trace: bool = True,
        final_message: str = "Respuesta validada.",
        tool_status: str = "succeeded",
        policy_status: str = "passed",
        state_writes: list[dict] | None = None,
        token_usage: dict | None = None,
        errors: list[dict] | None = None,
    ) -> None:
        self.calls = []
        self.trace = trace
        self.final_message = final_message
        self.tool_status = tool_status
        self.policy_status = policy_status
        self.state_writes = state_writes or []
        self.token_usage = token_usage or {}
        self.errors = errors or []

    async def handle_turn(self, **kwargs):
        self.calls.append(kwargs)
        trace_metadata = {
            "advisor_brain": {"required_tools": [{"name": "catalog.search"}]},
            "tool_results": [{"tool_name": "catalog.search", "status": self.tool_status}],
            "policy_result": {"status": self.policy_status},
            "state_writes": self.state_writes,
        }
        if self.token_usage:
            trace_metadata["model_usage"] = self.token_usage
        if self.trace:
            trace_metadata["universal_turn_trace"] = {"trace_id": "trace-1"}
        return AgentServiceResult(
            context=TurnContext(
                tenant_id=kwargs["tenant_id"],
                conversation_id=kwargs["conversation_id"],
                inbound_text=kwargs["inbound_text"],
            ),
            output=TurnOutput(
                final_message=self.final_message,
                confidence=0.9,
                trace_metadata=trace_metadata,
            ),
            state_persistence={"writes": []},
            send=SendAdapterResult(
                mode="no_send",
                send_decision=PreparedSendDecision(
                    status="blocked",
                    allowed=False,
                    reason="no_send_mode",
                ),
                delivery_status={"send_status": "no_send"},
            ),
            errors=self.errors,
        )


def _suite(tenant_id):
    return AgentTestSuite(
        id=uuid4(),
        tenant_id=tenant_id,
        agent_version_id=uuid4(),
        name="Readiness",
        mode="draft_validation",
        status="draft",
        metadata_json={},
    )


def _scenario(tenant_id, suite_id, expected=None):
    return AgentTestScenario(
        id=uuid4(),
        tenant_id=tenant_id,
        test_suite_id=suite_id,
        name="Happy",
        turns=[{"inbound_text": "Hola"}],
        expected=expected or {
            "final_messages": ["Respuesta validada."],
            "required_tools": ["catalog.search"],
        },
        status="draft",
        metadata_json={},
    )


def _multiturn_scenario(tenant_id, suite_id):
    return AgentTestScenario(
        id=uuid4(),
        tenant_id=tenant_id,
        test_suite_id=suite_id,
        name="Multi",
        turns=[
            {"inbound_text": "Hola", "expected": {"final_message_contains": "Respuesta"}},
            {"inbound_text": "Necesito ayuda", "expected": {"expected_tools": ["catalog.search"]}},
        ],
        expected={
            "expected_send_decision": "no_send",
            "expected_state_writes": ["customer_name"],
            "expected_policy_status": "passed",
        },
        status="draft",
        metadata_json={},
    )


@pytest.mark.asyncio
async def test_run_test_suite_uses_agent_service_no_send_and_records_evidence(monkeypatch) -> None:
    tenant_id = uuid4()
    suite = _suite(tenant_id)
    scenario = _scenario(tenant_id, suite.id)
    fake_service = FakeAgentService()

    async def fake_suite(_session, **kwargs):
        assert kwargs == {"tenant_id": tenant_id, "suite_id": suite.id}
        return suite

    async def fake_scenarios(_session, **kwargs):
        assert kwargs == {"tenant_id": tenant_id, "suite_id": suite.id}
        return [scenario]

    monkeypatch.setattr(test_lab.service, "get_agent_test_suite_for_tenant", fake_suite)
    monkeypatch.setattr(test_lab.service, "list_agent_test_scenarios", fake_scenarios)
    monkeypatch.setattr(test_lab, "_create_sandbox_conversation", _fake_conversation)
    monkeypatch.setattr(test_lab, "_audit_outbox", _zero_audit)
    monkeypatch.setattr(test_lab, "_audit_side_effects", _zero_audit)

    run = await test_lab.run_test_suite(
        FakeSession(),
        tenant_id=tenant_id,
        suite_id=suite.id,
        mode="no_send",
        review_required=True,
        created_by_user_id=uuid4(),
        agent_service_factory=lambda _session: fake_service,
    )

    assert fake_service.calls[0]["mode"] == "no_send"
    assert fake_service.calls[0]["inbound_text"] == "Hola"
    assert run.status == "passed"
    assert run.decision == test_lab.TEST_LAB_PASSED
    assert run.trace_ids == ["trace-1"]
    assert run.turn_results[0]["final_message"] == "Respuesta validada."
    assert run.turn_results[0]["input"] == "Hola"
    assert run.turn_results[0]["tools_executed"] == [
        {"tool_name": "catalog.search", "status": "succeeded"}
    ]
    assert run.turn_results[0]["policy_result"] == {"status": "passed"}
    assert run.turn_results[0]["send_decision"] == "no_send"
    assert run.outbox_audit_result == {"count": 0, "status": "pass"}
    assert suite.last_run_id == run.id


@pytest.mark.asyncio
async def test_test_lab_openai_direct_provider_mode_requires_no_send() -> None:
    with pytest.raises(
        test_lab.service.ProductAgentError,
        match="openai_direct_provider Test Lab requires mode=no_send",
    ):
        await test_lab.run_test_suite(
            FakeSession(),
            tenant_id=uuid4(),
            suite_id=uuid4(),
            mode="live",
            execution_mode=test_lab.OPENAI_DIRECT_PROVIDER_MODE,
            review_required=True,
            created_by_user_id=None,
        )


@pytest.mark.asyncio
async def test_test_lab_runtime_v2_agent_service_mode_requires_no_send() -> None:
    with pytest.raises(
        test_lab.service.ProductAgentError,
        match="runtime_v2_agent_service Test Lab requires mode=no_send",
    ):
        await test_lab.run_test_suite(
            FakeSession(),
            tenant_id=uuid4(),
            suite_id=uuid4(),
            mode="live",
            execution_mode=test_lab.RUNTIME_V2_AGENT_SERVICE_MODE,
            review_required=True,
            created_by_user_id=None,
        )


@pytest.mark.asyncio
async def test_test_lab_rejects_unknown_execution_mode() -> None:
    with pytest.raises(
        test_lab.service.ProductAgentError,
        match="test lab execution_mode is not supported",
    ):
        await test_lab.run_test_suite(
            FakeSession(),
            tenant_id=uuid4(),
            suite_id=uuid4(),
            mode="no_send",
            execution_mode="live_whatsapp",
            review_required=True,
            created_by_user_id=None,
        )


@pytest.mark.asyncio
async def test_test_lab_openai_direct_provider_blocks_when_openai_provider_is_not_real(
    monkeypatch,
) -> None:
    tenant_id = uuid4()
    suite = _suite(tenant_id)
    scenario = _scenario(tenant_id, suite.id)
    monkeypatch.setattr(test_lab.service, "get_agent_test_suite_for_tenant", _returns(suite))
    monkeypatch.setattr(test_lab.service, "list_agent_test_scenarios", _returns([scenario]))
    monkeypatch.setattr(test_lab, "_audit_outbox", _zero_audit)
    monkeypatch.setattr(test_lab, "_audit_side_effects", _zero_audit)
    monkeypatch.setattr(
        test_lab,
        "build_agent_turn_provider",
        lambda **_kwargs: test_lab.MockAgentProvider(),
    )

    run = await test_lab.run_test_suite(
        FakeSession(),
        tenant_id=tenant_id,
        suite_id=suite.id,
        mode="no_send",
            execution_mode=test_lab.OPENAI_DIRECT_PROVIDER_MODE,
        review_required=True,
        created_by_user_id=None,
    )

    assert run.status == "blocked"
    assert run.decision == test_lab.REAL_AGENT_TEST_LAB_BLOCKED_BY_OPENAI_API
    assert run.coverage_summary["execution_mode"] == test_lab.OPENAI_DIRECT_PROVIDER_MODE
    assert run.coverage_summary["blocked_reason"] == "openai_provider_not_enabled"


@pytest.mark.asyncio
async def test_test_lab_openai_direct_provider_blocks_safe_fallback_provider(monkeypatch) -> None:
    tenant_id = uuid4()
    suite = _suite(tenant_id)
    scenario = _scenario(tenant_id, suite.id)
    monkeypatch.setattr(test_lab.service, "get_agent_test_suite_for_tenant", _returns(suite))
    monkeypatch.setattr(test_lab.service, "list_agent_test_scenarios", _returns([scenario]))
    monkeypatch.setattr(test_lab, "_audit_outbox", _zero_audit)
    monkeypatch.setattr(test_lab, "_audit_side_effects", _zero_audit)
    monkeypatch.setattr(
        test_lab,
        "build_agent_turn_provider",
        lambda **_kwargs: test_lab.SafeFallbackAgentProvider(reason="missing"),
    )

    run = await test_lab.run_test_suite(
        FakeSession(),
        tenant_id=tenant_id,
        suite_id=suite.id,
        mode="no_send",
        execution_mode=test_lab.OPENAI_DIRECT_PROVIDER_MODE,
        review_required=True,
        created_by_user_id=None,
    )

    assert run.status == "blocked"
    assert run.decision == test_lab.REAL_AGENT_TEST_LAB_BLOCKED_BY_OPENAI_API
    assert run.coverage_summary["blocked_reason"] == "openai_provider_unavailable"


@pytest.mark.asyncio
async def test_test_lab_real_mode_blocks_when_cost_limits_are_exceeded(monkeypatch) -> None:
    tenant_id = uuid4()
    suite = _suite(tenant_id)
    scenarios = [
        _scenario(tenant_id, suite.id),
        _scenario(tenant_id, suite.id),
        _scenario(tenant_id, suite.id),
    ]
    monkeypatch.setattr(test_lab.service, "get_agent_test_suite_for_tenant", _returns(suite))
    monkeypatch.setattr(test_lab.service, "list_agent_test_scenarios", _returns(scenarios))
    monkeypatch.setattr(test_lab, "_audit_outbox", _zero_audit)
    monkeypatch.setattr(test_lab, "_audit_side_effects", _zero_audit)

    run = await test_lab.run_test_suite(
        FakeSession(),
        tenant_id=tenant_id,
        suite_id=suite.id,
        mode="no_send",
        execution_mode=test_lab.OPENAI_DIRECT_PROVIDER_MODE,
        review_required=True,
        created_by_user_id=None,
    )

    assert run.status == "blocked"
    assert run.decision == test_lab.REAL_AGENT_TEST_LAB_BLOCKED_BY_LIMITS
    assert run.coverage_summary["blocked_reason"] == "real_mode_max_scenarios_exceeded"


@pytest.mark.asyncio
async def test_test_lab_real_mode_blocks_when_turn_limit_is_exceeded(monkeypatch) -> None:
    tenant_id = uuid4()
    suite = _suite(tenant_id)
    scenario = _scenario(tenant_id, suite.id)
    scenario.turns = [{"inbound_text": f"turn {index}"} for index in range(7)]
    monkeypatch.setattr(test_lab.service, "get_agent_test_suite_for_tenant", _returns(suite))
    monkeypatch.setattr(test_lab.service, "list_agent_test_scenarios", _returns([scenario]))
    monkeypatch.setattr(test_lab, "_audit_outbox", _zero_audit)
    monkeypatch.setattr(test_lab, "_audit_side_effects", _zero_audit)

    run = await test_lab.run_test_suite(
        FakeSession(),
        tenant_id=tenant_id,
        suite_id=suite.id,
        mode="no_send",
        execution_mode=test_lab.OPENAI_DIRECT_PROVIDER_MODE,
        review_required=True,
        created_by_user_id=None,
    )

    assert run.status == "blocked"
    assert run.decision == test_lab.REAL_AGENT_TEST_LAB_BLOCKED_BY_LIMITS
    assert run.coverage_summary["blocked_reason"] == "real_mode_max_turns_exceeded"


@pytest.mark.asyncio
async def test_test_lab_real_mode_records_token_usage(monkeypatch) -> None:
    tenant_id = uuid4()
    suite = _suite(tenant_id)
    scenario = _scenario(tenant_id, suite.id)
    fake_service = FakeAgentService(
        token_usage={"input_tokens": 120, "output_tokens": 24, "total_tokens": 144}
    )
    monkeypatch.setattr(test_lab.service, "get_agent_test_suite_for_tenant", _returns(suite))
    monkeypatch.setattr(test_lab.service, "list_agent_test_scenarios", _returns([scenario]))
    monkeypatch.setattr(test_lab, "_create_sandbox_conversation", _fake_conversation)
    monkeypatch.setattr(test_lab, "_audit_outbox", _zero_audit)
    monkeypatch.setattr(test_lab, "_audit_side_effects", _zero_audit)

    run = await test_lab.run_test_suite(
        FakeSession(),
        tenant_id=tenant_id,
        suite_id=suite.id,
        mode="no_send",
        execution_mode=test_lab.OPENAI_DIRECT_PROVIDER_MODE,
        review_required=True,
        created_by_user_id=None,
        agent_service_factory=lambda _session: fake_service,
    )

    turn = run.turn_results[0]
    assert turn["execution_mode"] == test_lab.OPENAI_DIRECT_PROVIDER_MODE
    assert turn["token_usage"] == {"input_tokens": 120, "output_tokens": 24, "total_tokens": 144}
    assert turn["estimated_cost"] == {
        "amount_usd": None,
        "status": "cost_rate_not_configured",
        "input_tokens": 120,
        "output_tokens": 24,
        "total_tokens": 144,
    }
    assert run.coverage_summary["max_output_tokens"] == 350
    assert run.coverage_summary["temperature"] == 0.2


@pytest.mark.asyncio
async def test_test_lab_real_mode_never_writes_outbox(monkeypatch) -> None:
    tenant_id = uuid4()
    suite = _suite(tenant_id)
    scenario = _scenario(tenant_id, suite.id)
    fake_service = FakeAgentService()
    monkeypatch.setattr(test_lab.service, "get_agent_test_suite_for_tenant", _returns(suite))
    monkeypatch.setattr(test_lab.service, "list_agent_test_scenarios", _returns([scenario]))
    monkeypatch.setattr(test_lab, "_create_sandbox_conversation", _fake_conversation)
    monkeypatch.setattr(test_lab, "_audit_outbox", _zero_audit)
    monkeypatch.setattr(test_lab, "_audit_side_effects", _zero_audit)

    run = await test_lab.run_test_suite(
        FakeSession(),
        tenant_id=tenant_id,
        suite_id=suite.id,
        mode="no_send",
        execution_mode=test_lab.OPENAI_DIRECT_PROVIDER_MODE,
        review_required=True,
        created_by_user_id=None,
        agent_service_factory=lambda _session: fake_service,
    )

    assert fake_service.calls[0]["mode"] == "no_send"
    assert fake_service.calls[0]["metadata"]["openai_api_real"] is True
    assert fake_service.calls[0]["metadata"]["readiness_eligible"] is False
    assert run.outbox_audit_result == {"count": 0, "status": "pass"}
    assert run.side_effect_audit_result == {"count": 0, "status": "pass"}
    assert run.turn_results[0]["send_decision"] == "no_send"


@pytest.mark.asyncio
async def test_product_agent_runtime_adapter_uses_agent_service_and_persists_history(
    monkeypatch,
) -> None:
    tenant_id = uuid4()
    agent_id = uuid4()
    suite = _suite(tenant_id)
    scenario = _scenario(tenant_id, suite.id)
    fake_service = FakeAgentService()
    session = FakeRuntimeSqlSession(agent_id=agent_id)
    monkeypatch.setattr(test_lab.service, "get_agent_test_suite_for_tenant", _returns(suite))
    monkeypatch.setattr(test_lab.service, "list_agent_test_scenarios", _returns([scenario]))
    monkeypatch.setattr(test_lab, "_create_sandbox_conversation", _fake_conversation)
    monkeypatch.setattr(test_lab, "_audit_outbox", _zero_audit)
    monkeypatch.setattr(test_lab, "_audit_side_effects", _zero_audit)

    run = await test_lab.run_test_suite(
        session,
        tenant_id=tenant_id,
        suite_id=suite.id,
        mode="no_send",
        execution_mode=test_lab.RUNTIME_V2_AGENT_SERVICE_MODE,
        review_required=True,
        created_by_user_id=None,
        agent_service_factory=lambda _session: fake_service,
    )

    assert run.status == "passed"
    assert fake_service.calls[0]["metadata"]["agent_id"] == str(agent_id)
    assert fake_service.calls[0]["metadata"]["product_agent_runtime_adapter"] is True
    assert fake_service.calls[0]["metadata"]["runtime_v2_agent_service"] is True
    assert fake_service.calls[0]["metadata"]["readiness_eligible"] is True
    assert any("UPDATE conversations" in sql for sql, _params in session.sql_calls)
    assert any("INSERT INTO messages" in sql for sql, _params in session.sql_calls)
    assert run.coverage_summary["runtime_v2_agent_service"] is True
    assert run.coverage_summary["readiness_eligible"] is True


@pytest.mark.asyncio
async def test_runtime_v2_mode_fails_without_runtime_contract(monkeypatch) -> None:
    tenant_id = uuid4()
    suite = _suite(tenant_id)
    scenario = _scenario(tenant_id, suite.id)
    session = FakeRuntimeSqlSession(agent_id=uuid4(), runtime_contract_ready=False)
    monkeypatch.setattr(test_lab.service, "get_agent_test_suite_for_tenant", _returns(suite))
    monkeypatch.setattr(test_lab.service, "list_agent_test_scenarios", _returns([scenario]))
    monkeypatch.setattr(test_lab, "_create_sandbox_conversation", _fake_conversation)
    monkeypatch.setattr(test_lab, "_audit_outbox", _zero_audit)
    monkeypatch.setattr(test_lab, "_audit_side_effects", _zero_audit)

    run = await test_lab.run_test_suite(
        session,
        tenant_id=tenant_id,
        suite_id=suite.id,
        mode="no_send",
        execution_mode=test_lab.RUNTIME_V2_AGENT_SERVICE_MODE,
        review_required=True,
        created_by_user_id=None,
        agent_service_factory=lambda _session: FakeAgentService(),
    )

    assert run.status == "blocked"
    assert run.decision == test_lab.REAL_AGENT_TEST_LAB_BLOCKED_BY_RUNTIME_CONTRACT
    assert "runtime_contract_missing" in run.turn_results[0]["failures"]
    assert not any("INSERT INTO messages" in sql for sql, _params in session.sql_calls)


@pytest.mark.asyncio
async def test_product_agent_runtime_adapter_accepts_tenant_runtime_contract() -> None:
    agent_id = uuid4()
    fake_service = FakeAgentService()
    session = FakeRuntimeSqlSession(
        agent_id=agent_id,
        runtime_contract_ready=False,
        tenant_config={
            "agent_runtime_v2": {
                "tenant_domain_contract": {"domain": "test", "tools": []}
            }
        },
    )
    adapter = runtime_adapter.ProductAgentRuntimeAdapter(
        session=session,
        agent_version_id=uuid4(),
        agent_service_factory=lambda _session: fake_service,
    )

    result = await adapter.handle_turn(
        tenant_id=str(uuid4()),
        conversation_id=str(uuid4()),
        inbound_text="Hola",
        turn_number=1,
        mode="no_send",
        metadata={},
    )

    assert result.output is not None
    assert fake_service.calls[0]["metadata"]["runtime_contract_source"] == (
        "tenant_runtime_v2_config"
    )


@pytest.mark.asyncio
async def test_product_agent_runtime_adapter_passes_product_contract_to_agent_service() -> None:
    agent_id = uuid4()
    fake_service = FakeAgentService()
    contract = {
        "contract_version": "1.0",
        "tenant_id": "tenant-1",
        "domain": "generic_lead_qualification",
        "tools": [{"tool_id": "faq.lookup", "topic": "faq"}],
    }
    adapter = runtime_adapter.ProductAgentRuntimeAdapter(
        session=FakeRuntimeSqlSession(agent_id=agent_id, product_contract=contract),
        agent_version_id=uuid4(),
        agent_service_factory=lambda _session: fake_service,
    )

    result = await adapter.handle_turn(
        tenant_id="tenant-1",
        conversation_id=str(uuid4()),
        inbound_text="Hola",
        turn_number=1,
        mode="no_send",
        metadata={},
    )

    assert result.output is not None
    metadata = fake_service.calls[0]["metadata"]
    assert metadata["runtime_contract_source"] == "product_agent_version"
    assert metadata["tenant_domain_contract"] == contract
    assert metadata["send_mode"] == "no_send"


@pytest.mark.asyncio
async def test_product_agent_runtime_adapter_rejects_ready_flag_without_contract() -> None:
    adapter = runtime_adapter.ProductAgentRuntimeAdapter(
        session=FakeRuntimeSqlSession(
            agent_id=uuid4(),
            runtime_contract_ready=True,
            product_contract={},
        ),
        agent_version_id=uuid4(),
        agent_service_factory=lambda _session: FakeAgentService(),
    )

    result = await adapter.handle_turn(
        tenant_id=str(uuid4()),
        conversation_id=str(uuid4()),
        inbound_text="Hola",
        turn_number=1,
        mode="no_send",
        metadata={},
    )

    assert result.output is None
    assert result.errors[0]["code"] == runtime_adapter.RUNTIME_CONTRACT_MISSING
    assert not any("INSERT INTO messages" in sql for sql, _params in adapter._session.sql_calls)


@pytest.mark.asyncio
async def test_product_agent_runtime_adapter_blocks_missing_version() -> None:
    adapter = runtime_adapter.ProductAgentRuntimeAdapter(
        session=FakeRuntimeSqlSession(agent_id=uuid4(), version_exists=False),
        agent_version_id=uuid4(),
        agent_service_factory=lambda _session: FakeAgentService(),
    )

    result = await adapter.handle_turn(
        tenant_id=str(uuid4()),
        conversation_id=str(uuid4()),
        inbound_text="Hola",
        turn_number=1,
        mode="no_send",
        metadata={},
    )

    assert result.output is None
    assert result.errors[0]["code"] == runtime_adapter.RUNTIME_CONTRACT_MISSING


def test_runtime_adapter_helpers_cover_non_dict_config() -> None:
    assert runtime_adapter._runtime_config(None) == {}
    assert runtime_adapter._contract_payload(None) == {}
    assert runtime_adapter._contract_payload(
        {"domain_contract": {"domain": "generic_lead_qualification"}}
    ) == {"domain": "generic_lead_qualification"}
    assert runtime_adapter._contract_payload(
        {
            "runtime_contract": {
                "tenant_domain_contract": {"domain": "vehicle_credit_sales"}
            }
        }
    ) == {"domain": "vehicle_credit_sales"}
    assert runtime_adapter._contract_payload(
        {"runtime_contract": {"domain": "appointment_services"}}
    ) == {"domain": "appointment_services"}


def test_test_lab_trace_id_accepts_universal_turn_id() -> None:
    assert (
        test_lab._trace_id({"universal_turn_trace": {"turn_id": "tenant:conversation:turn"}})
        == "tenant:conversation:turn"
    )


def test_test_lab_detects_semantic_provider_failure_from_risk_flags() -> None:
    assert test_lab._semantic_provider_failed(["semantic_interpreter_provider_error"])
    assert not test_lab._semantic_provider_failed(["needs_human_review"])


def test_test_lab_risk_flags_reads_output_and_trace_metadata() -> None:
    output = TurnOutput(
        final_message="Hola",
        risk_flags=["output_flag"],
        trace_metadata={},
    )
    flags = test_lab._risk_flags(
        {
            "advisor_brain": {"risk_flags": ["advisor_flag"]},
            "universal_turn_trace": {
                "final_output": {"risk_flags": ["universal_flag"]},
                "gpt_understanding": {"risk_flags": ["gpt_flag"]},
            },
        },
        output,
    )
    assert flags == ["output_flag", "advisor_flag", "universal_flag", "gpt_flag"]


@pytest.mark.asyncio
async def test_test_lab_real_mode_fails_if_policy_blocks(monkeypatch) -> None:
    tenant_id = uuid4()
    suite = _suite(tenant_id)
    scenario = _scenario(tenant_id, suite.id)
    monkeypatch.setattr(test_lab.service, "get_agent_test_suite_for_tenant", _returns(suite))
    monkeypatch.setattr(test_lab.service, "list_agent_test_scenarios", _returns([scenario]))
    monkeypatch.setattr(test_lab, "_create_sandbox_conversation", _fake_conversation)
    monkeypatch.setattr(test_lab, "_audit_outbox", _zero_audit)
    monkeypatch.setattr(test_lab, "_audit_side_effects", _zero_audit)

    run = await test_lab.run_test_suite(
        FakeSession(),
        tenant_id=tenant_id,
        suite_id=suite.id,
        mode="no_send",
        execution_mode=test_lab.OPENAI_DIRECT_PROVIDER_MODE,
        review_required=True,
        created_by_user_id=None,
        agent_service_factory=lambda _session: FakeAgentService(policy_status="blocked"),
    )

    assert run.status == "failed"
    assert run.decision == test_lab.TEST_LAB_BLOCKED_BY_POLICY
    assert "policy_blocked" in run.turn_results[0]["failures"]


@pytest.mark.asyncio
async def test_test_lab_real_mode_fails_if_required_tool_skipped(monkeypatch) -> None:
    tenant_id = uuid4()
    suite = _suite(tenant_id)
    scenario = _scenario(tenant_id, suite.id)
    monkeypatch.setattr(test_lab.service, "get_agent_test_suite_for_tenant", _returns(suite))
    monkeypatch.setattr(test_lab.service, "list_agent_test_scenarios", _returns([scenario]))
    monkeypatch.setattr(test_lab, "_create_sandbox_conversation", _fake_conversation)
    monkeypatch.setattr(test_lab, "_audit_outbox", _zero_audit)
    monkeypatch.setattr(test_lab, "_audit_side_effects", _zero_audit)

    run = await test_lab.run_test_suite(
        FakeSession(),
        tenant_id=tenant_id,
        suite_id=suite.id,
        mode="no_send",
        execution_mode=test_lab.OPENAI_DIRECT_PROVIDER_MODE,
        review_required=True,
        created_by_user_id=None,
        agent_service_factory=lambda _session: FakeAgentService(tool_status="skipped"),
    )

    assert run.status == "failed"
    assert run.decision == test_lab.TEST_LAB_BLOCKED_BY_TOOL
    assert "tool_skipped:catalog.search" in run.turn_results[0]["failures"]


@pytest.mark.asyncio
async def test_multiturn_scenario_records_turn_results_state_and_expected_vs_actual(
    monkeypatch,
) -> None:
    tenant_id = uuid4()
    suite = _suite(tenant_id)
    scenario = _multiturn_scenario(tenant_id, suite.id)
    fake_service = FakeAgentService(state_writes=[{"field_key": "customer_name"}])
    monkeypatch.setattr(test_lab.service, "get_agent_test_suite_for_tenant", _returns(suite))
    monkeypatch.setattr(test_lab.service, "list_agent_test_scenarios", _returns([scenario]))
    monkeypatch.setattr(test_lab, "_create_sandbox_conversation", _fake_conversation)
    monkeypatch.setattr(test_lab, "_audit_outbox", _zero_audit)
    monkeypatch.setattr(test_lab, "_audit_side_effects", _zero_audit)

    run = await test_lab.run_test_suite(
        FakeSession(),
        tenant_id=tenant_id,
        suite_id=suite.id,
        mode="no_send",
        review_required=True,
        created_by_user_id=None,
        agent_service_factory=lambda _session: fake_service,
    )

    assert run.status == "passed"
    assert [call["inbound_text"] for call in fake_service.calls] == ["Hola", "Necesito ayuda"]
    assert len(run.turn_results) == 2
    assert run.turn_results[0]["status"] == "passed"
    assert run.turn_results[1]["state_writes"] == [{"field_key": "customer_name"}]


@pytest.mark.asyncio
async def test_required_tool_failure_marks_failed(monkeypatch) -> None:
    tenant_id = uuid4()
    suite = _suite(tenant_id)
    scenario = _scenario(tenant_id, suite.id)
    monkeypatch.setattr(test_lab.service, "get_agent_test_suite_for_tenant", _returns(suite))
    monkeypatch.setattr(test_lab.service, "list_agent_test_scenarios", _returns([scenario]))
    monkeypatch.setattr(test_lab, "_create_sandbox_conversation", _fake_conversation)
    monkeypatch.setattr(test_lab, "_audit_outbox", _zero_audit)
    monkeypatch.setattr(test_lab, "_audit_side_effects", _zero_audit)

    run = await test_lab.run_test_suite(
        FakeSession(),
        tenant_id=tenant_id,
        suite_id=suite.id,
        mode="no_send",
        review_required=True,
        created_by_user_id=None,
        agent_service_factory=lambda _session: FakeAgentService(tool_status="failed"),
    )

    assert run.status == "failed"
    assert run.decision == test_lab.TEST_LAB_BLOCKED_BY_TOOL
    assert run.turn_results[0]["tools_failed"] == [
        {"tool_name": "catalog.search", "status": "failed"}
    ]
    assert "tool_failed:catalog.search" in run.turn_results[0]["failures"]


@pytest.mark.asyncio
async def test_policy_failure_marks_failed(monkeypatch) -> None:
    tenant_id = uuid4()
    suite = _suite(tenant_id)
    scenario = _scenario(
        tenant_id,
        suite.id,
        expected={
            "final_messages": ["Respuesta validada."],
            "expected_policy_status": "passed",
        },
    )
    monkeypatch.setattr(test_lab.service, "get_agent_test_suite_for_tenant", _returns(suite))
    monkeypatch.setattr(test_lab.service, "list_agent_test_scenarios", _returns([scenario]))
    monkeypatch.setattr(test_lab, "_create_sandbox_conversation", _fake_conversation)
    monkeypatch.setattr(test_lab, "_audit_outbox", _zero_audit)
    monkeypatch.setattr(test_lab, "_audit_side_effects", _zero_audit)

    run = await test_lab.run_test_suite(
        FakeSession(),
        tenant_id=tenant_id,
        suite_id=suite.id,
        mode="no_send",
        review_required=True,
        created_by_user_id=None,
        agent_service_factory=lambda _session: FakeAgentService(policy_status="failed"),
    )

    assert run.status == "failed"
    assert run.decision == test_lab.TEST_LAB_BLOCKED_BY_POLICY
    assert run.turn_results[0]["policy_result"] == {"status": "failed"}
    assert "policy_status_mismatch" in run.turn_results[0]["failures"]


@pytest.mark.asyncio
async def test_run_test_suite_blocks_without_scenarios(monkeypatch) -> None:
    tenant_id = uuid4()
    suite = _suite(tenant_id)
    monkeypatch.setattr(test_lab.service, "get_agent_test_suite_for_tenant", _returns(suite))
    monkeypatch.setattr(test_lab.service, "list_agent_test_scenarios", _returns([]))
    monkeypatch.setattr(test_lab, "_audit_outbox", _zero_audit)
    monkeypatch.setattr(test_lab, "_audit_side_effects", _zero_audit)

    run = await test_lab.run_test_suite(
        FakeSession(),
        tenant_id=tenant_id,
        suite_id=suite.id,
        mode="no_send",
        review_required=True,
        created_by_user_id=None,
        agent_service_factory=lambda _session: FakeAgentService(),
    )

    assert run.status == "blocked"
    assert run.blocked_count == 1
    assert suite.status == "blocked"


@pytest.mark.asyncio
async def test_run_test_suite_fails_on_missing_trace_and_audit_counts(monkeypatch) -> None:
    tenant_id = uuid4()
    suite = _suite(tenant_id)
    scenario = _scenario(tenant_id, suite.id)
    monkeypatch.setattr(test_lab.service, "get_agent_test_suite_for_tenant", _returns(suite))
    monkeypatch.setattr(test_lab.service, "list_agent_test_scenarios", _returns([scenario]))
    monkeypatch.setattr(test_lab, "_create_sandbox_conversation", _fake_conversation)
    monkeypatch.setattr(test_lab, "_audit_outbox", _one_audit)
    monkeypatch.setattr(test_lab, "_audit_side_effects", _one_audit)

    run = await test_lab.run_test_suite(
        FakeSession(),
        tenant_id=tenant_id,
        suite_id=suite.id,
        mode="no_send",
        review_required=True,
        created_by_user_id=None,
        agent_service_factory=lambda _session: FakeAgentService(trace=False),
    )

    assert run.status == "blocked"
    assert run.decision == test_lab.TEST_LAB_BLOCKED_BY_TRACE
    assert run.outbox_audit_result == {"count": 1, "status": "block"}
    assert run.side_effect_audit_result == {"count": 1, "status": "block"}


def test_turn_assertions_detect_expected_mismatches() -> None:
    turn = {
        "final_message": "Otra",
        "required_tools": [],
        "tool_results": [],
        "send_status": "prepared",
        "trace_id": None,
    }
    failures = test_lab._assert_turn(
        turn,
        expected={
            "expected_final_messages": ["Esperada"],
            "expected_tools": ["quote.resolve"],
            "send_status": "no_send",
        },
        turn_index=0,
    )
    assert failures == [
        "final_message_mismatch",
        "missing_tool:quote.resolve",
        "send_decision_mismatch",
        "trace_missing",
    ]


def test_turn_assertions_cover_behavior_validation_failures() -> None:
    turn = {
        "final_message": "Tomo tu mensaje y reviso el contexto",
        "required_tools": ["catalog.search"],
        "tool_results": [{"tool_name": "catalog.search", "status": "skipped"}],
        "state_writes": [],
        "policy_result": {"status": "passed"},
        "send_decision": "no_send",
        "send_status": "no_send",
        "trace_id": "trace-1",
        "errors": [],
        "failures": [],
    }

    failures = test_lab._assert_turn(
        turn,
        expected={
            "final_message_contains": "aprobado",
            "expected_tools_executed": ["catalog.search"],
            "expected_state_writes": ["customer_name"],
            "expected_blockers": ["policy_block"],
            "should_block": True,
            "internal_text_forbidden": True,
        },
        turn_index=0,
    )

    assert failures == [
        "final_message_contains_mismatch",
        "tool_not_executed:catalog.search",
        "missing_state_write:customer_name",
        "missing_blocker:policy_block",
        "expected_block_missing",
        "internal_text_visible",
    ]


def test_turn_assertions_detect_forbidden_copy_and_state_writes() -> None:
    turn = {
        "final_message": "Perfecto, ya validé tu tipo de ingreso para el plan.",
        "required_tools": [],
        "tool_results": [],
        "state_writes": [{"field_key": "plan_selection"}],
        "policy_result": {"status": "passed"},
        "send_decision": "no_send",
        "send_status": "no_send",
        "trace_id": "trace-1",
        "errors": [],
        "failures": [],
    }

    failures = test_lab._assert_turn(
        turn,
        expected={
            "final_message_contains": ["Perfecto"],
            "final_message_not_contains": ["ya validé tu tipo de ingreso"],
            "forbidden_state_writes": ["plan_selection"],
        },
        turn_index=0,
    )

    assert failures == [
        "forbidden_final_message_contains:ya validé tu tipo de ingreso",
        "forbidden_state_write:plan_selection",
    ]


def test_turn_assertions_detect_openai_provider_error_risk_flag() -> None:
    failures = test_lab._assert_turn(
        {
            "final_message": "Necesito revision humana.",
            "required_tools": [],
            "tool_results": [],
            "state_writes": [],
            "policy_result": {"status": "passed"},
            "send_decision": "no_send",
            "send_status": "no_send",
            "trace_id": "trace-1",
            "errors": [],
            "failures": [],
            "risk_flags": ["semantic_interpreter_provider_error"],
        },
        expected={"internal_text_forbidden": True},
        turn_index=0,
    )

    assert failures == ["openai_provider_error"]


def test_turn_expected_merges_global_per_turn_messages_and_inline_expected() -> None:
    expected = {
        "expected_turns": [{"final_message_contains": "hola"}],
        "expected_tools": ["catalog.search"],
        "final_messages": ["Hola"],
    }
    turn = {"expected": {"final_message_contains": "override"}}

    merged = test_lab._turn_expected(expected=expected, turn=turn, turn_index=0)

    assert merged["final_message_contains"] == "override"
    assert merged["expected_tools"] == ["catalog.search"]
    assert merged["final_message"] == "Hola"


def test_helper_branches_cover_policy_send_expected_and_block_detection() -> None:
    assert test_lab._normalize_tool_status("blocked") == "skipped"
    assert test_lab._expected_list({"tool": "catalog.search"}, "tool") == ["catalog.search"]
    assert test_lab._turn_is_blocked(
        {"send_decision": "no_send", "policy_result": {"status": "blocked"}, "errors": []}
    )
    assert test_lab._turn_is_blocked(
        {"send_decision": "prepared", "policy_result": {"status": "passed"}, "errors": []}
    )
    assert test_lab._turn_is_blocked(
        {"send_decision": "no_send", "policy_result": {"status": "passed"}, "errors": ["boom"]}
    )
    simulated_service, simulated_blocker = test_lab._build_agent_service(
        FakeSession(),
        execution_mode=test_lab.SIMULATED_CONTRACT_MODE,
        agent_version_id=uuid4(),
        agent_service_factory=None,
    )
    assert simulated_service is not None
    assert simulated_blocker is None


def test_real_mode_token_cost_and_agent_service_failure_helpers() -> None:
    assert test_lab._token_usage({}) == {}
    assert test_lab._estimated_cost({}) == {
        "amount_usd": None,
        "status": "token_usage_missing",
    }
    assert test_lab._token_usage(
        {
            "universal_turn_trace": {
                "model_usage": {
                    "input_tokens": 1,
                    "output_tokens": 2,
                    "total_tokens": 3,
                }
            }
        }
    ) == {"input_tokens": 1, "output_tokens": 2, "total_tokens": 3}
    assert test_lab._agent_service_failures(
        [
            "ignored",
            {"code": "required_tool_not_succeeded_blocks_send"},
            {"code": "runtime_v2_turn_failed"},
            {},
        ]
    ) == [
        "required_tool_blocked_send",
        "agent_service_error:runtime_v2_turn_failed",
    ]


def test_real_mode_builds_agent_service_when_openai_provider_is_available(monkeypatch) -> None:
    monkeypatch.setattr(test_lab, "build_agent_turn_provider", lambda **_kwargs: object())

    agent_service, blocker = test_lab._build_agent_service(
        FakeSession(),
        execution_mode=test_lab.OPENAI_DIRECT_PROVIDER_MODE,
        agent_version_id=uuid4(),
        agent_service_factory=None,
    )

    assert agent_service is not None
    assert blocker is None


def test_finish_run_records_failed_scenario_without_blockers() -> None:
    run = AgentTestRun(
        tenant_id=uuid4(),
        agent_version_id=uuid4(),
        test_suite_id=uuid4(),
        mode="no_send",
    )

    test_lab._finish_run(
        run,
        scenario_results=[{"status": "failed", "failures": ["final_message_mismatch"]}],
        turn_results=[],
        trace_ids=["trace-1"],
        outbox_count=0,
        side_effect_count=0,
        blocked_reason=None,
    )

    assert run.status == "failed"
    assert run.decision == test_lab.TEST_LAB_FAILED
    assert run.fail_count == 1


def test_finish_run_records_failed_missing_trace_decision() -> None:
    run = AgentTestRun(
        tenant_id=uuid4(),
        agent_version_id=uuid4(),
        test_suite_id=uuid4(),
        mode="no_send",
    )

    test_lab._finish_run(
        run,
        scenario_results=[{"status": "failed", "failures": ["trace_missing"]}],
        turn_results=[],
        trace_ids=[],
        outbox_count=0,
        side_effect_count=0,
        blocked_reason=None,
    )

    assert run.status == "failed"
    assert run.decision == test_lab.TEST_LAB_BLOCKED_BY_TRACE


def test_finish_run_blocks_on_openai_provider_error() -> None:
    run = AgentTestRun(
        tenant_id=uuid4(),
        agent_version_id=uuid4(),
        test_suite_id=uuid4(),
        mode="no_send",
    )

    test_lab._finish_run(
        run,
        scenario_results=[{"status": "failed", "failures": ["openai_provider_error"]}],
        turn_results=[],
        trace_ids=["trace-1"],
        outbox_count=0,
        side_effect_count=0,
        blocked_reason=None,
    )

    assert run.status == "blocked"
    assert run.decision == test_lab.REAL_AGENT_TEST_LAB_BLOCKED_BY_OPENAI_API


def test_trace_tool_helpers_cover_direct_nested_and_invalid_shapes() -> None:
    assert test_lab._trace_id({"trace_id": "direct-trace"}) == "direct-trace"
    assert test_lab._trace_id({"universal_turn_trace": {"trace_id": "nested-trace"}}) == (
        "nested-trace"
    )
    assert test_lab._trace_id({}) is None

    assert test_lab._required_tools({}) == []
    assert test_lab._required_tools(
        {
            "universal_turn_trace": {
                "advisor_brain": {
                    "required_tools": [
                        "faq.lookup",
                        {"tool_id": "quote.resolve"},
                        {"name": "catalog.search"},
                        {},
                    ]
                }
            }
        }
    ) == ["faq.lookup", "quote.resolve", "catalog.search"]
    assert test_lab._tool_results(
        {
            "tool_results": [
                "ignored",
                {"name": "faq.lookup", "status": "succeeded"},
                {"name": "missing-status"},
            ],
            "universal_turn_trace": {
                "tool_results": [{"tool_id": "quote.resolve", "status": "succeeded"}]
            },
        }
    ) == [
        {"tool_name": "faq.lookup", "status": "succeeded"},
        {"tool_name": "quote.resolve", "status": "succeeded"},
    ]


def test_state_policy_send_helpers_cover_nested_errors_and_defaults() -> None:
    result = AgentServiceResult(
        context=TurnContext(
            tenant_id="tenant",
            conversation_id="conversation",
            inbound_text="Hola",
        ),
        output=TurnOutput(
            final_message="",
            trace_metadata={"universal_turn_trace": {"policy": {"status": "blocked"}}},
        ),
        state_persistence={"writes": [{"field_key": "persisted"}]},
        send=SendAdapterResult(
            mode="no_send",
            send_decision=PreparedSendDecision(
                status="blocked",
                allowed=False,
                reason="manual_no_send",
            ),
            delivery_status={},
        ),
        errors=[{"message": "policy_error"}],
    )

    assert test_lab._policy_result(result) == {"status": "blocked"}
    assert test_lab._send_decision(result) == "manual_no_send"
    assert test_lab._state_writes(result) == [{"field_key": "persisted"}]

    no_output = AgentServiceResult(
        context=result.context,
        output=None,
        state_persistence={},
        send=result.send,
        errors=[{"message": "runtime_error"}],
    )
    assert test_lab._policy_result(no_output) == {
        "status": "failed",
        "errors": [{"message": "runtime_error"}],
    }

    clean = AgentServiceResult(
        context=result.context,
        output=None,
        state_persistence={},
        send=result.send,
        errors=[],
    )
    assert test_lab._policy_result(clean) == {"status": "passed"}

    blocked_turn = {
        "failures": [],
        "errors": [{"message": "policy_error"}],
        "policy_result": {"status": "blocked"},
        "send_decision": "blocked",
        "final_message": "Hola",
        "trace_id": "trace-1",
        "tools_required": [],
        "tools_executed": [],
        "state_writes": [],
    }
    assert test_lab._assert_turn(
        blocked_turn,
        expected={"expected_send_decision": "blocked", "should_block": False},
        turn_index=0,
    ) == ["policy_blocked", "unexpected_block"]


@pytest.mark.asyncio
async def test_sandbox_conversation_and_audits_use_db_backed_queries() -> None:
    tenant_id = uuid4()
    suite_id = uuid4()
    scenario_id = uuid4()
    contact_id = uuid4()
    conversation_id = uuid4()
    session = FakeSqlSession(contact_id, conversation_id, None, None, 0, 0)

    created_conversation_id = await test_lab._create_sandbox_conversation(
        session,
        tenant_id=tenant_id,
        suite_id=suite_id,
        scenario_id=scenario_id,
    )
    outbox_count = await test_lab._audit_outbox(session, tenant_id)
    side_effect_count = await test_lab._audit_side_effects(session, tenant_id)

    assert created_conversation_id == conversation_id
    assert outbox_count == 0
    assert side_effect_count == 0
    assert len(session.calls) == 6
    assert session.calls[0][1]["tenant_id"] == tenant_id
    assert session.calls[3][1]["metadata"].startswith('{"product_first_test_lab":true')


async def _fake_conversation(_session, **_kwargs):
    return uuid4()


async def _zero_audit(_session, _tenant_id):
    return 0


async def _one_audit(_session, _tenant_id):
    return 1


def _returns(value):
    async def _inner(*_args, **_kwargs):
        return value

    return _inner
