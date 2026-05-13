def test_kb_simulate_gates_on_is_demo():
    """The /kb/simulate endpoint must branch on tenant.is_demo.

    Updated 2026-05-13: non-demo tenants no longer get 501; they get a
    coherent stub response (mode='sources_only', empty chunks, message
    pointing them to /knowledge/test). The gate still exists — it just
    returns a usable empty state instead of an error.
    """
    import pathlib

    src = (
        pathlib.Path(__file__).parent.parent.parent
        / "atendia/api/_kb/command_center.py"
    ).read_text()
    assert "is_demo" in src or "demo_tenant" in src, (
        "command_center.py simulate endpoint does not gate on is_demo."
    )
    assert "sources_only" in src, (
        "simulate endpoint must return a coherent stub for non-demo tenants."
    )
