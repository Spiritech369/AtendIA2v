def test_admin_email_gate_removed_from_customers_routes():
    """Guard: customers_routes.py must not gate on admin@demo.com email."""
    import pathlib

    src = pathlib.Path(__file__).parent.parent.parent / "atendia" / "api" / "customers_routes.py"
    src = src.read_text(encoding="utf-8")
    assert "admin@demo.com" not in src, (
        "customers_routes.py still uses admin@demo.com as a gate. Use tenant.is_demo instead."
    )
