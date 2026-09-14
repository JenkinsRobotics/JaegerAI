"""The self-check runs, and passes, on this install.

Two different jobs here. The first test is the sanity gate: if the tool
surface, toolsets, skills, dialects, adapters or prompt registry are
broken, CI fails with the specific check that broke rather than a
thousand cryptic downstream errors.

The rest verify the checker ITSELF behaves — a health check that cannot
fail is worse than no health check, because it reports green while the
thing it watches burns.
"""

from __future__ import annotations


import pytest

from jaeger_agent.core import selfcheck


@pytest.fixture(autouse=True)
def _live_surface():
    """Every check here reads the real registry — see tests/conftest.py."""
    from tests.conftest import _register_tool_surface

    _register_tool_surface()
    yield


def test_selfcheck_passes() -> None:
    report = selfcheck.run()
    assert report.ok, "self-check failed:\n" + "\n".join(
        f"  {c.name}: {c.detail}" for c in report.failures
    )


def test_selfcheck_covers_the_whole_surface() -> None:
    """Guard against a check silently disappearing from CHECKS."""
    report = selfcheck.run()
    assert len(report.checks) == len(selfcheck.CHECKS)
    assert len(selfcheck.CHECKS) >= 15


def test_a_broken_check_is_reported_not_raised() -> None:
    """A check that raises must become a FAILED check. If it propagated,
    one bad probe would take down the whole report and hide the others."""

    def _boom() -> selfcheck.Check:
        raise RuntimeError("deliberate")

    original = selfcheck.CHECKS
    selfcheck.CHECKS = (*original, _boom)
    try:
        report = selfcheck.run()
        assert not report.ok
        assert any("deliberate" in c.detail for c in report.failures)
    finally:
        selfcheck.CHECKS = original


def test_exit_code_follows_health() -> None:
    """``python3 -m jaeger_agent selfcheck`` is meant for CI, so the exit
    code has to mean something."""
    assert selfcheck.main([]) == 0


def test_json_output_is_machine_readable(capsys) -> None:
    import json

    selfcheck.main(["--json"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["checks"] and all("name" in c for c in payload["checks"])


# ── the usage seam (1.0.3) ─────────────────────────────────────────


def test_usage_counts_in_memory_without_a_host() -> None:
    """The point of the inversion: an embedder that is not JaegerAI still
    gets working counters, where before it got none."""
    from jaeger_agent.core import usage

    usage.set_sink(None)
    usage.reset()
    usage.record_tool("read_file", ok=True, elapsed=0.5)
    usage.record_tool("read_file", ok=False, elapsed=0.25)
    usage.record_skill("debugging")

    top = usage.top_tools(3)[0]
    assert top["name"] == "read_file"
    assert top["calls"] == 2 and top["failures"] == 1
    assert usage.top_skills(3)[0] == {"name": "debugging", "views": 1}
    usage.reset()


def test_a_registered_sink_wins_for_reads() -> None:
    """A host with persisted history should beat this process's slice."""
    from jaeger_agent.core import usage

    class Sink:
        def top_tools(self, limit):
            return [{"name": "from_host"}]

    usage.reset()
    usage.record_tool("local_only")
    usage.set_sink(Sink())
    try:
        assert usage.top_tools(3) == [{"name": "from_host"}]
    finally:
        usage.set_sink(None)
        usage.reset()


def test_a_raising_sink_never_breaks_a_turn() -> None:
    """Telemetry is best-effort. A broken host backend must degrade to the
    in-memory counters, not take down the tool call being counted."""
    from jaeger_agent.core import usage

    class Bad:
        def record_tool(self, *a, **k):
            raise RuntimeError("boom")

        def top_tools(self, limit):
            raise RuntimeError("boom")

    usage.reset()
    usage.set_sink(Bad())
    try:
        usage.record_tool("still_counted")          # must not raise
        assert usage.top_tools(3)[0]["name"] == "still_counted"
    finally:
        usage.set_sink(None)
        usage.reset()
