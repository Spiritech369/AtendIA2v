from atendia.db.models.product_agent import (
    AgentActionBinding,
    AgentDeployment,
    AgentFieldPermission,
    AgentKnowledgeSourceBinding,
    AgentPublishEvent,
    AgentTestRun,
    AgentTestScenario,
    AgentTestSuite,
    AgentToolBinding,
    AgentVersion,
    AgentWorkflowBinding,
)

PRODUCT_AGENT_MODELS = [
    AgentVersion,
    AgentDeployment,
    AgentKnowledgeSourceBinding,
    AgentToolBinding,
    AgentActionBinding,
    AgentFieldPermission,
    AgentWorkflowBinding,
    AgentTestSuite,
    AgentTestScenario,
    AgentTestRun,
    AgentPublishEvent,
]


def test_product_agent_models_are_tenant_scoped() -> None:
    for model in PRODUCT_AGENT_MODELS:
        table = model.__table__
        assert "tenant_id" in table.c, f"{table.name} must carry tenant_id"
        tenant_fks = {
            fk.column.table.name
            for fk in table.c.tenant_id.foreign_keys
        }
        assert tenant_fks == {"tenants"}


def test_product_agent_core_tables_reference_agent_or_version() -> None:
    assert {
        fk.column.table.name
        for fk in AgentVersion.__table__.c.agent_id.foreign_keys
    } == {"agents"}
    assert {
        fk.column.table.name
        for fk in AgentDeployment.__table__.c.agent_id.foreign_keys
    } == {"agents"}
    for model in [
        AgentKnowledgeSourceBinding,
        AgentToolBinding,
        AgentActionBinding,
        AgentFieldPermission,
        AgentWorkflowBinding,
        AgentTestSuite,
        AgentTestRun,
    ]:
        assert {
            fk.column.table.name
            for fk in model.__table__.c.agent_version_id.foreign_keys
        } == {"agent_versions"}
