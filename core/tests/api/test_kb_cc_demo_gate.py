def test_kb_simulate_gates_on_is_demo():
    """The /kb/simulate endpoint must check tenant.is_demo."""
    import pathlib
    # Resolve relative to this test file: tests/api/ -> ../../ -> core/ -> atendia/...
    src = (
        pathlib.Path(__file__).parent.parent.parent
        / "atendia/api/_kb/command_center.py"
    ).read_text()
    assert "is_demo" in src or "demo_tenant" in src, (
        "command_center.py simulate endpoint does not gate on is_demo."
    )
    assert "501" in src, (
        "simulate endpoint must raise 501 for non-demo tenants."
    )
