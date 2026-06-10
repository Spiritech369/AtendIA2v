from pathlib import Path


def test_knowledge_binding_no_dinamo_hardcode() -> None:
    repo = Path(__file__).resolve().parents[2]
    checked_files = [
        repo / "atendia" / "product_agents" / "service.py",
        repo / "atendia" / "product_agents" / "schemas.py",
        repo / "atendia" / "api" / "product_agents_routes.py",
    ]

    combined = "\n".join(path.read_text(encoding="utf-8").lower() for path in checked_files)

    assert "dinamo" not in combined
    assert "motos" not in combined
    assert "nomina tarjeta" not in combined
    assert "nómina tarjeta" not in combined
