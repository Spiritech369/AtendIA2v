from pathlib import Path

SOURCE_FILES = [
    Path("atendia/db/models/product_agent.py"),
    Path("atendia/product_agents/service.py"),
    Path("atendia/product_agents/schemas.py"),
    Path("atendia/api/product_agents_routes.py"),
    Path("atendia/db/migrations/versions/066_product_first_agent_entities.py"),
]


def test_product_agent_entities_do_not_hardcode_tenant_vertical_terms() -> None:
    core_dir = Path(__file__).resolve().parents[2]
    forbidden_terms = [
        "dinamo",
        "skeleton",
        "comando",
        "motocicleta",
        "nomina_tarjeta",
    ]

    for relative_path in SOURCE_FILES:
        content = (core_dir / relative_path).read_text(encoding="utf-8").lower()
        for term in forbidden_terms:
            assert term not in content, f"{term} found in {relative_path}"
