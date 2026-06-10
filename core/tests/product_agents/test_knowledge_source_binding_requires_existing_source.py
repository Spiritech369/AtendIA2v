from atendia.db.models.product_agent import AgentKnowledgeSourceBinding


def test_knowledge_source_binding_has_required_source_foreign_key() -> None:
    table = AgentKnowledgeSourceBinding.__table__

    assert table.c.knowledge_source_id.nullable is False
    assert {
        fk.column.table.name
        for fk in table.c.knowledge_source_id.foreign_keys
    } == {"knowledge_sources"}


def test_knowledge_source_binding_is_unique_per_agent_version_source() -> None:
    constraint_names = {
        constraint.name
        for constraint in AgentKnowledgeSourceBinding.__table__.constraints
    }

    assert "uq_agent_knowledge_source_bindings_source" in constraint_names
