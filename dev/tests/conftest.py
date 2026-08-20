"""Pytest configuration for the JaegerAI product test suite.

0.9 step 4 split: this file did not exist in the initial staging pass
(the monorepo's ``dev/tests/conftest.py`` was pruned into JaegerAI's
copy — see JaegerAI's own conftest note — but a JaegerAI-side copy was
never written, silently stranding the tool-registry fixtures below).
Rebuilt from the monorepo's version, package names updated
(``jaeger_os`` -> ``jaeger_ai`` for the parts that moved with this
repo; ``core.tools`` stays ``jaeger_os`` — the registry itself is
framework substrate, a pinned dependency here).

``QT_QPA_PLATFORM`` is defaulted to ``offscreen`` so any interface test
that imports a GUI toolkit does not hard-abort on a headless runner
before pytest can report a normal result.

Auto-markers: rather than hand-annotating ~80 test files, this
conftest infers a marker tier from each test's path. The convention:

  * tests/jaeger_ai/daemon/ ........... subprocess + slow (real forks)
  * tests/jaeger_ai/interfaces/tui/ ... ui (TUI rendering / rumps)
  * tests/jaeger_ai/interfaces/pyside6/tray/ .. ui (menu-bar tray)
  * tests/jaeger_ai/skills/test_computer_use* .. ui (Apple Events)
  * tests/jaeger_ai/skills/test_macos_background* .. subprocess
  * tests/jaeger_ai/agent/test_context_guard_integration .. integration
  * everything else ................... unmarked (fast unit)

Plus an explicit ``smoke`` list — the curated 30-ish probes that
exercise the most surface in the least time. ``pytest -m smoke``
should turn green in under 5s on a fresh checkout. Tests still
in the smoke list keep ``smoke`` AND any path-inferred marker.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# Never launch the native app from a test: 0.7.1's GUI-first paths
# (bare ``jaeger``, ``agent create``) honour this as the headless gate.
os.environ.setdefault("JAEGER_NO_GUI", "1")


# ── live-instance isolation guard ──────────────────────────────────
#
# Tests resolve instance directories through ``core/instance/instance.py``,
# whose root is ``<install_root>/.jaeger_ai/instances/`` — and in a dev
# checkout ``install_root`` IS this repository, so the real running
# instance sits inside the tree the suite executes against. Tests that
# isolate themselves do it by setting ``JAEGER_HOME`` to a tmp_path, but
# that is a per-test convention, not something enforced anywhere: one
# test that forgets writes straight into live config, memory or logs.
#
# Forcing ``JAEGER_INSTANCE_DIR`` here was tried and is wrong — it
# outranks ``JAEGER_HOME`` in the resolver, so it breaks the wizard tests
# that assert an instance directory is NAMED from the character or CLI
# pin. Instead of overriding resolution, this watches the two real roots
# and fails the run if the suite modified either.
#
# The roots are computed the way the resolver computes them with no env
# override, so a test that sets ``JAEGER_HOME`` cannot move the target.
def _real_operator_state_roots() -> tuple[Path, ...]:
    roots: list[Path] = []
    try:
        import jaeger_ai
        package_root = Path(jaeger_ai.__file__).resolve().parent
        roots.append(package_root.parent / ".jaeger_ai")
    except Exception:  # noqa: BLE001 — the guard must never break collection
        pass
    roots.append(Path.home() / ".jaeger")   # pre-0.2.6 location, still on disk
    return tuple(roots)


_LIVE_ROOTS = _real_operator_state_roots()
_live_fingerprint_at_start: dict[str, tuple[int, int]] | None = None


def _fingerprint_live_roots() -> dict[str, tuple[int, int]]:
    """``{path: (size, mtime_ns)}`` across the live roots.

    stat only, never hashing — these trees hold real memory databases and
    this runs on every session.
    """
    out: dict[str, tuple[int, int]] = {}
    for root in _LIVE_ROOTS:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            try:
                if path.is_file():
                    st = path.stat()
                    out[str(path)] = (st.st_size, st.st_mtime_ns)
            except OSError:  # racing with the running app is not our failure
                continue
    return out


def pytest_sessionstart(session: "pytest.Session") -> None:  # noqa: ARG001
    global _live_fingerprint_at_start
    _live_fingerprint_at_start = _fingerprint_live_roots()


def pytest_sessionfinish(session: "pytest.Session", exitstatus: int) -> None:  # noqa: ARG001
    """Fail the run if the suite wrote to a live instance tree."""
    before = _live_fingerprint_at_start
    if before is None:
        return
    after = _fingerprint_live_roots()
    added = sorted(set(after) - set(before))
    removed = sorted(set(before) - set(after))
    changed = sorted(k for k in set(before) & set(after) if before[k] != after[k])
    if not (added or removed or changed):
        return
    report = ["", "=" * 70,
              "TEST ISOLATION FAILURE: the suite modified a LIVE instance tree.",
              "Tests must write only to tmp_path (set JAEGER_HOME to it).", ""]
    for label, names in (("added", added), ("removed", removed),
                         ("modified", changed)):
        for name in names[:10]:
            report.append(f"  {label}: {name}")
        if len(names) > 10:
            report.append(f"  ... and {len(names) - 10} more {label}")
    report.append("=" * 70)
    print("\n".join(report))
    session.exitstatus = 1


# Path-based marker rules. Order matters — first match wins.
_PATH_MARKERS: list[tuple[str, tuple[str, ...]]] = [
    ("/jaeger_ai/daemon/test_lifecycle_e2e",  ("subprocess", "slow")),
    ("/jaeger_ai/daemon/test_protocol",       ("subprocess",)),
    ("/jaeger_ai/daemon/test_lifecycle",      ("subprocess",)),
    ("/jaeger_ai/interfaces/tui/",            ("ui",)),
    ("/jaeger_ai/interfaces/pyside6/tray/",           ("ui",)),
    ("/jaeger_ai/skills/test_computer_use",   ("ui",)),
    ("/jaeger_ai/skills/test_macos_background", ("subprocess",)),
    ("/jaeger_ai/agent/test_context_guard_integration", ("integration",)),
    ("/jaeger_ai/agent/test_runtime_bridge",  ("integration",)),
    ("/jaeger_ai/agent/test_liveness",        ("integration",)),
    ("/jaeger_ai/agent/test_run_turn",        ("integration",)),
]


# Smoke list — the curated cheap probes. Matched as a SUBSTRING of the
# test's nodeid so a file like ``test_diagnostics.py`` adds all 8 of
# its tests to smoke in one entry.
_SMOKE_FILES: tuple[str, ...] = (
    "test_diagnostics.py",
    "test_process_slot.py",
    "test_prompt_assembly.py",
    "test_context_guard.py",   # not the integration variant — that path is excluded
    "test_drift_parser.py",
    "test_bench.py",
    "test_board_autonomy.py",
    "test_preflight.py",
    "test_session_commands.py",
)


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Apply path-derived markers + the smoke tag to every collected
    item. Idempotent — running twice yields the same marker set."""
    for item in items:
        # Pytest's nodeid looks like
        # ``tests/jaeger_ai/.../test_foo.py::test_bar``. Use the
        # path part (Path() handles both forward and back slashes).
        rel = "/" + str(Path(item.fspath)).replace("\\", "/").split("tests/", 1)[-1]
        for prefix, markers in _PATH_MARKERS:
            if prefix in rel:
                for m in markers:
                    item.add_marker(getattr(pytest.mark, m))
                break
        if any(s in rel for s in _SMOKE_FILES) \
           and "test_context_guard_integration" not in rel:
            item.add_marker(pytest.mark.smoke)


# Reset the live agent-status indicator before every test so state set
# in one test (e.g. the agent_status / TUI tests) doesn't leak into
# tests that assume a clean idle state. Tiny dict write; doesn't affect
# any test that doesn't read or write ``_pipeline["agent_status"]``.
import pytest as _pytest


@_pytest.fixture(autouse=True)
def _reset_agent_status() -> None:
    """Reset the global live-activity snapshot to ``ready`` before each
    test. Prevents the previous test's status from bleeding into the
    next — important because ``set_agent_status`` is a process-global
    write, not a per-instance one."""
    try:
        from jaeger_ai.main import set_agent_status
    except Exception:  # noqa: BLE001 — agent_status is optional during partial migrations
        return
    set_agent_status("ready", "")


@_pytest.fixture(autouse=True)
def _reset_pipeline_config() -> None:
    """Drop ``_pipeline["config"]`` before each test.

    Same process-global hazard as ``agent_status`` above, but with a
    wider blast radius: a test that installs a config and doesn't remove
    it changes what LATER tests read out of the shared pipeline. Two
    real leaks this closes — the TUI's ``_configured_busy_mode()`` read
    a previous test's ``display.busy_input_mode`` ("steer") instead of
    the documented "interrupt" default, and bridge turn telemetry picked
    up a stale ``ctx_max``. Both passed in isolation and only failed in
    a full run, which is the signature of shared-state bleed.

    Clearing BEFORE (not restoring after) mirrors ``_reset_agent_status``:
    whatever a test sets for itself still applies for that test.
    """
    try:
        from jaeger_ai.main import _pipeline
    except Exception:  # noqa: BLE001
        return
    _pipeline.pop("config", None)


@_pytest.fixture(scope="session")
def _full_tool_registry_snapshot():
    """The COMPLETE tool registry, captured once: module-registered tools
    (registered as an import side-effect in tools/*.py, which CANNOT be
    re-run after a clear_registry() because the modules are import-cached)
    PLUS the remaining main.py builtins."""
    import jaeger_agent.tools  # noqa: F401 — module-level tool registrations
    from jaeger_os.core.tools import tool_registry as R
    try:
        from jaeger_ai.main import _register_builtins
        _register_builtins(None)   # register-only; client is unused at def time
    except Exception:  # noqa: BLE001
        pass
    return dict(R._registry)


@_pytest.fixture(autouse=True)
def _restore_tool_registry(_full_tool_registry_snapshot):
    """Restore the full tool registry after every test. Post
    tool-standardization, most tools register on module import; a test that
    calls clear_registry() would otherwise strand those module tools for the
    whole rest of the session (imports are cached, so they can't re-fire)."""
    from jaeger_os.core.tools import tool_registry as R
    yield
    R._registry.clear()
    R._registry.update(_full_tool_registry_snapshot)
