"""Lean runtime health probe.

The bug we're guarding against: a refactor or rename silently breaks
one of the layers the agent depends on at runtime (sandbox path
resolver, memory store schema, tool registration, drift parser) and
the failure only surfaces when a real user prompt happens to exercise
it. The probe runs every layer once on every invocation so the break
is loud and immediate.

This file pins:
  * each individual check returns a sane shape on success
  * a failing check is reported as ``ok=False`` with the reason
  * an exception inside a check is caught and reported (the probe
    keeps running through the rest of the list, not short-circuited)
  * the topline ``ok`` boolean is a strict AND across every probe
"""

from __future__ import annotations

import pytest

from jaeger_os.core.diagnostics import run_health_checks
from jaeger_os.core.diagnostics.probe import (
    DEFAULT_CHECKS,
    HealthCheck,
    HealthResult,
    _run_one,
)


# ── shape / runner contract ─────────────────────────────────────────


def test_runner_produces_one_result_per_check():
    checks = [
        HealthCheck("a", lambda: (True, "ok")),
        HealthCheck("b", lambda: (True, "ok")),
        HealthCheck("c", lambda: (True, "ok")),
    ]
    out = run_health_checks(checks)
    assert out["total"] == 3
    assert out["passed"] == 3
    assert out["ok"] is True
    assert [r["name"] for r in out["checks"]] == ["a", "b", "c"]


def test_failure_is_surfaced_without_short_circuit():
    """A failing check must not stop the rest of the probe — the
    operator wants the WHOLE picture, not just the first thing that
    broke."""
    calls: list[str] = []

    def make(name: str, ok: bool):
        def fn():
            calls.append(name)
            return ok, f"{name} detail"
        return HealthCheck(name, fn)

    out = run_health_checks([make("a", False), make("b", True), make("c", True)])
    assert calls == ["a", "b", "c"]
    assert out["ok"] is False
    assert out["passed"] == 2
    assert out["total"] == 3
    a, b, c = out["checks"]
    assert a["ok"] is False
    assert b["ok"] is True
    assert c["ok"] is True


def test_exception_inside_check_is_caught_as_failure():
    """A check that raises must not propagate — the probe is meant to
    diagnose, not crash. The exception text lands in ``detail``."""
    def boom():
        raise RuntimeError("synthetic")
    out = run_health_checks([HealthCheck("boom", boom)])
    assert out["ok"] is False
    assert out["passed"] == 0
    assert "synthetic" in out["checks"][0]["detail"]
    assert "RuntimeError" in out["checks"][0]["detail"]


def test_topline_ok_is_strict_and_across_every_check():
    """``ok`` flips False the moment ANY check fails, even with
    everything else passing."""
    out = run_health_checks([
        HealthCheck("a", lambda: (True, "")),
        HealthCheck("fail_one", lambda: (False, "")),
        HealthCheck("c", lambda: (True, "")),
    ])
    assert out["ok"] is False


def test_runner_records_elapsed_ms_per_check():
    """The elapsed_ms field exists and is non-negative — the operator
    uses it to spot a probe that suddenly takes 10x longer (the
    canary for a slow filesystem or a leaked file handle)."""
    out = run_health_checks([HealthCheck("instant", lambda: (True, ""))])
    assert out["checks"][0]["elapsed_ms"] >= 0
    assert isinstance(out["checks"][0]["elapsed_ms"], (int, float))


def test_run_one_wraps_callable_into_a_health_result():
    """``_run_one`` is the building block — single-check API.
    Returns a HealthResult with name, ok, detail, elapsed_ms."""
    r = _run_one(HealthCheck("solo", lambda: (True, "fine")))
    assert isinstance(r, HealthResult)
    assert r.name == "solo"
    assert r.ok is True
    assert r.detail == "fine"


# ── default probe set integrity ─────────────────────────────────────


def test_default_checks_include_every_advertised_probe():
    """The runtime probe set must include every layer the tool's
    docstring promises. A regression here would silently shrink the
    probe."""
    names = {c.name for c in DEFAULT_CHECKS}
    advertised = {
        "layout", "file_sandbox", "memory", "time", "calculate",
        "tool_registry", "skills_loaded", "drift_parser",
    }
    assert advertised.issubset(names), f"missing probes: {advertised - names}"


def test_default_checks_have_unique_names():
    """Duplicate names would collide in the result list and confuse
    any downstream renderer that keys off ``name``."""
    names = [c.name for c in DEFAULT_CHECKS]
    assert len(names) == len(set(names))


# ── regression pins (2026-05-26) ─────────────────────────────────
# These three probes silently false-negative'd in 0.1.0 — the
# expectations had drifted from the implementation but the probe
# was rarely run so nobody noticed. Pin the right shapes here so a
# future drift bites us at test time, not when a user runs
# ``system_health`` and gets 5/8 on a healthy runtime.


def test_check_memory_uses_explicit_submodule_imports():
    """``from jaeger_os.agent.tools import memory`` resolves to the
    umbrella *function* (re-exported in __init__), not the submodule —
    so the probe must import remember/recall/forget by name to avoid
    the shadowing. Pin the actual import lines (not docstring text)
    so a refactor that goes back to the ambiguous form gets caught."""
    import inspect
    from jaeger_os.core.diagnostics import probe
    src = inspect.getsource(probe._check_memory)
    # Only look at executable code, not the docstring.
    code_lines = [
        ln for ln in src.splitlines()
        if "import" in ln and ln.lstrip().startswith(("from ", "import "))
    ]
    code_text = "\n".join(code_lines)
    # The fix: explicit submodule path.
    assert "from jaeger_os.agent.tools.memory import" in code_text
    # The trap: package-level import that shadows the submodule with
    # the re-exported umbrella function.
    assert "from jaeger_os.agent.tools import memory" not in code_text


def test_check_memory_round_trip_succeeds_on_bound_layout(tmp_path):
    """Wire memory + tool layout at a fresh tmp dir, then run the
    real probe. Catches: (a) the import-shadowing regression, (b) any
    future change to the remember/recall return shape that makes the
    probe's ``.get('value')`` extraction fail."""
    from types import SimpleNamespace
    from jaeger_os.core.memory import memory as memmod
    from jaeger_os.core.memory import sqlite_store
    from jaeger_os.agent.tools import _common
    from jaeger_os.core.diagnostics.probe import _check_memory

    sqlite_store.close()
    layout = SimpleNamespace(
        memory_dir=tmp_path / "memory",
        logs_dir=tmp_path / "logs",
        audit_log_path=tmp_path / "logs" / "audit.log",
        skills_dir=tmp_path / "skills",
    )
    (tmp_path / "logs").mkdir()
    (tmp_path / "skills").mkdir()
    memmod.bind(layout)
    _common._layout = layout
    try:
        ok, detail = _check_memory()
        assert ok, f"memory probe failed on a clean instance: {detail}"
        assert "round trip" in detail
    finally:
        sqlite_store.close()


def test_check_drift_parser_uses_real_gemma_dialect():
    """The canonical sample must be a dialect ``extract_tool_calls``
    actually recognises. The bracketed form ``[get_time(...)]`` is
    NOT a recognised dialect (Gemma never emits that); the real
    form is ``<|tool_call>call:name(args)<tool_call|>``. Pin the
    fixed sample so a regression doesn't go back to the bogus form."""
    import inspect
    from jaeger_os.core.diagnostics import probe
    src = inspect.getsource(probe._check_drift_parser)
    assert "<|tool_call>" in src
    # The earlier bogus sample.
    assert "'[get_time(timezone=\"UTC\")]'" not in src


def test_check_drift_parser_returns_pass_on_canonical_sample():
    """Run the actual probe — should report ok with one parsed
    call named ``get_time``."""
    from jaeger_os.core.diagnostics.probe import _check_drift_parser
    ok, detail = _check_drift_parser()
    assert ok, f"drift parser probe failed: {detail}"
    assert "parsed 1" in detail


def test_check_tool_registry_returns_not_checked_when_no_agent():
    """Pre-boot — no JaegerAgent in ``_jaeger_agents_by_session``,
    no legacy ``_pipeline['agent']``. Must report ok with a
    "not checked" detail rather than scanning ``dir(core.tools)``
    (which would always false-negative because the Python function
    names there don't match CORE's agent-facing names)."""
    from jaeger_os.core.diagnostics.probe import _check_tool_registry
    from jaeger_os import main as jmain
    saved_agents = dict(jmain._jaeger_agents_by_session)
    saved_pipeline_agent = jmain._pipeline.get("agent")
    jmain._jaeger_agents_by_session.clear()
    jmain._pipeline["agent"] = None
    try:
        ok, detail = _check_tool_registry()
        assert ok
        assert "not checked" in detail
    finally:
        jmain._jaeger_agents_by_session.update(saved_agents)
        if saved_pipeline_agent is not None:
            jmain._pipeline["agent"] = saved_pipeline_agent


def test_check_tool_registry_reads_jaeger_agent_dispatch_map():
    """Phase-9 ``JaegerAgent`` exposes ``_dispatch_by_name`` (not the
    legacy ``_function_toolset``). A stub agent with the right shape
    must be detected; missing CORE names surface as a failure."""
    from jaeger_os.core.diagnostics.probe import _check_tool_registry
    from jaeger_os.agent.skill_registry.toolset_scoping import CORE
    from jaeger_os import main as jmain

    # Stub: a CORE-complete dispatch map should pass.
    class _StubAgent:
        _dispatch_by_name = {n: object() for n in CORE}

    saved = dict(jmain._jaeger_agents_by_session)
    jmain._jaeger_agents_by_session["_probe_test"] = _StubAgent()
    try:
        ok, detail = _check_tool_registry()
        assert ok, f"unexpected failure: {detail}"
        assert "jaeger_agent" in detail
    finally:
        jmain._jaeger_agents_by_session.clear()
        jmain._jaeger_agents_by_session.update(saved)

    # And missing names → failure with a useful list.
    class _PartialAgent:
        _dispatch_by_name = {"get_time": object(), "calculate": object()}

    jmain._jaeger_agents_by_session["_probe_test"] = _PartialAgent()
    try:
        ok, detail = _check_tool_registry()
        assert not ok
        assert "missing" in detail.lower()
    finally:
        jmain._jaeger_agents_by_session.clear()
        jmain._jaeger_agents_by_session.update(saved)
