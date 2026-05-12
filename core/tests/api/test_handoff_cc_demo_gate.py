def test_human_agent_seed_moved_to_fixtures():
    """HUMAN_AGENT_SEED must not be defined inline in command_center.py."""
    import pathlib
    # Resolve relative to this test file so the path is correct regardless of cwd
    src = (
        pathlib.Path(__file__).parent.parent.parent
        / "atendia/api/_handoffs/command_center.py"
    ).read_text()
    assert "andrea@demo.com" not in src, (
        "HUMAN_AGENT_SEED is still inline in command_center.py. "
        "Move it to _demo/fixtures.py and import DEMO_HUMAN_AGENTS from there."
    )
