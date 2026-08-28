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
# Never attach to the operator's RUNNING agent from a test. ``create_runtime``
# tries ``run/bridge.sock`` before it tries ``boot_for_tui``, so on any machine
# where ARES (or ``jaeger bridge``) is live, a test that monkeypatches
# ``boot_for_tui`` never reaches its own patch — it proxies real turns to the
# real brain, against real memory. CI has no live socket, so CI could not see
# it. ``setdefault``, not assignment, so the opt-in fixture below can lift it.
os.environ.setdefault("JAEGER_NO_ATTACH", "1")


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


_registry_snapshot: dict | None = None


def pytest_sessionstart(session: "pytest.Session") -> None:  # noqa: ARG001
    """Capture live-instance fingerprints AND the full tool registry.

    The registry snapshot must be taken here — after collection has
    imported tool modules, before any test calls ``clear_registry``.
    A lazy session fixture that first runs when ``dev/tests`` starts
    would capture whatever ``packages/jaeger-agent/tests`` left behind
    (usually empty), then "restore" that emptiness for the rest of
    the run.
    """
    global _live_fingerprint_at_start, _registry_snapshot
    _live_fingerprint_at_start = _fingerprint_live_roots()
    import jaeger_agent.tools  # noqa: F401 — module-level registrations
    try:
        from jaeger_ai.main import _register_builtins
        _register_builtins(None)
    except Exception:  # noqa: BLE001 — package-only runs may lack jaeger_ai.main
        pass
    from jaeger_os.core.tools.tool_registry import snapshot_registry
    _registry_snapshot = snapshot_registry()


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


@_pytest.fixture(autouse=True)
def _restore_tool_registry():
    """Put the session-start registry back before AND after every test.

    Restoring only after a test left the first ``dev/tests`` case after a
    ``packages/jaeger-agent/tests`` run looking at an empty map.
    """
    from jaeger_os.core.tools.tool_registry import restore_registry
    if _registry_snapshot is not None:
        restore_registry(_registry_snapshot)
    yield
    if _registry_snapshot is not None:
        restore_registry(_registry_snapshot)


@_pytest.fixture(autouse=True)
def _reset_self_model_cache():
    """The per-boot persona digest must not inherit another test's identity."""
    from jaeger_agent.prompts.persona_lane import reset_self_model_cache

    reset_self_model_cache()
    yield
    reset_self_model_cache()


# ── bridge-attach isolation ────────────────────────────────────────
#
# AF_UNIX socket paths are capped near 104 bytes on macOS, and pytest's
# ``tmp_path`` (/private/var/folders/<...>/pytest-of-<user>/<test>0/) blows
# straight past that. Any fixture that needs a BINDABLE instance root has to
# live somewhere short, which is why these use /tmp directly rather than
# tmp_path. They still clean up after themselves.
def _short_instance_root() -> Path:
    import tempfile
    root = Path(tempfile.mkdtemp(prefix="jgr", dir="/tmp"))
    (root / "run").mkdir(parents=True, exist_ok=True)
    for live in _LIVE_ROOTS:
        try:
            root.resolve().relative_to(live.resolve())
        except (ValueError, OSError):
            continue
        raise AssertionError(
            f"refusing to use {root}: it is inside the live instance root "
            f"{live}. A test may never bind or attach to real state."
        )
    return root


@_pytest.fixture
def bindable_instance_root():
    """A short, disposable instance root pinned as ``JAEGER_INSTANCE_DIR``.

    Does NOT lift ``JAEGER_NO_ATTACH`` — this is for tests that need a real
    socket to exist while proving nothing attaches to it.
    """
    import shutil
    root = _short_instance_root()
    previous = os.environ.get("JAEGER_INSTANCE_DIR")
    os.environ["JAEGER_INSTANCE_DIR"] = str(root)
    try:
        yield root
    finally:
        if previous is None:
            os.environ.pop("JAEGER_INSTANCE_DIR", None)
        else:
            os.environ["JAEGER_INSTANCE_DIR"] = previous
        shutil.rmtree(root, ignore_errors=True)


@_pytest.fixture
def allow_bridge_attach(bindable_instance_root):
    """Opt a single test back into bridge attachment, safely.

    Attachment is disabled suite-wide (``JAEGER_NO_ATTACH`` at the top of this
    file). A handful of tests exist precisely to prove attachment WORKS, so
    they need it back — but lifting the gate on its own would let them reach
    the operator's live socket, which is the exact hazard the gate exists for.

    So the fixture does not just lift the gate: it builds on
    ``bindable_instance_root``, which has already pinned
    ``JAEGER_INSTANCE_DIR`` to a disposable root and refused if that root
    landed anywhere inside a live instance tree. Attachment is re-enabled and
    production is still unreachable — the guarantee is structural, not a
    convention the next test author has to remember.

    Yields the pinned instance root, so the test can build its socket path
    from it rather than re-deriving one.
    """
    previous = os.environ.pop("JAEGER_NO_ATTACH", None)
    try:
        yield bindable_instance_root
    finally:
        if previous is not None:
            os.environ["JAEGER_NO_ATTACH"] = previous
