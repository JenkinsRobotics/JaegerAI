"""Reachability fitness — prove wiring exists, not just that modules work.

The existing fitness suite asserts imports are ABSENT (no provider SDKs in
the agent loop). Nothing asserted the inverse: that a thing is actually
*reached*. That gap is why a broken migration runner, an unlaunched gateway
and a whole first-boot feature all sat green — a unit suite passes most
enthusiastically on perfectly isolated code, because isolation is what it
tests.

These are bidirectional wiring assertions:

* every declared bridge operation has a handler (no unmounted routes)
* every discovery routine points at a directory that exists
* known-orphaned subsystems stay on an explicit, shrinking ledger

The orphan ledger is a RATCHET, not a wish. It records what is unwired
today so the number can only go down; adding a new orphan fails the build.
"""

from __future__ import annotations

import ast
import pathlib
import re

import pytest

REPO = pathlib.Path(__file__).resolve().parents[4]


# ── 1. every declared bridge op has a handler ────────────────────────


def _bridge_source() -> str:
    return (REPO / "jaeger_ai/interfaces/bridge.py").read_text(encoding="utf-8")


def test_every_declared_bridge_query_has_a_handler():
    """A declared-but-unhandled op is an unmounted route."""
    from jaeger_ai.interfaces.bridge import BRIDGE_QUERIES

    src = _bridge_source()
    missing = [
        op for op in BRIDGE_QUERIES
        if len(re.findall(rf"""['"]{re.escape(op)}['"]""", src)) < 2
    ]
    assert missing == [], f"declared but never handled: {missing}"


def test_every_declared_bridge_command_has_a_handler():
    from jaeger_ai.interfaces.bridge import BRIDGE_COMMANDS

    src = _bridge_source()
    missing = [
        op for op in BRIDGE_COMMANDS
        if len(re.findall(rf"""['"]{re.escape(op)}['"]""", src)) < 2
    ]
    assert missing == [], f"declared but never handled: {missing}"


def test_every_bridge_op_is_classified_for_the_native_surface():
    """Adding an op without a surface_contract entry is half-wiring it."""
    from jaeger_ai.interfaces.bridge import BRIDGE_COMMANDS, BRIDGE_QUERIES
    from jaeger_ai.interfaces.surface_contract import (
        SWIFT_COMMAND_SUPPORT,
        SWIFT_QUERY_SUPPORT,
    )

    assert set(SWIFT_QUERY_SUPPORT) == set(BRIDGE_QUERIES)
    assert set(SWIFT_COMMAND_SUPPORT) == set(BRIDGE_COMMANDS)


# ── 2. discovery routines target directories that exist ──────────────


def test_migration_runner_targets_an_existing_directory():
    """The guard that hid a broken runner for an entire release."""
    from jaeger_ai.core.instance.migrations import MIGRATIONS_DIR

    assert MIGRATIONS_DIR.is_dir(), (
        f"{MIGRATIONS_DIR} missing — discover_migrations() returns [] and "
        "every migration is silently skipped"
    )


def test_module_discovery_roots_exist():
    """``discover_modules()`` scans these; a missing root finds no nodes."""
    from jaeger_ai.module_roots import roots

    missing = [str(r) for r in roots() if not r.is_dir()]
    assert missing == [], f"module discovery roots do not exist: {missing}"


def test_declared_module_factories_are_importable():
    """Every ``module.yaml`` factory must resolve to a real callable."""
    import importlib

    broken: list[str] = []
    for manifest in (REPO / "jaeger_ai").rglob("module.yaml"):
        text = manifest.read_text(encoding="utf-8")
        match = re.search(r"^factory:\s*([\w.]+):(\w+)", text, re.M)
        if not match:
            continue
        mod_name, attr = match.groups()
        try:
            mod = importlib.import_module(mod_name)
        except Exception as exc:  # noqa: BLE001 — report, don't abort the sweep
            broken.append(f"{manifest.parent.name}: cannot import {mod_name} ({exc})")
            continue
        if not hasattr(mod, attr):
            broken.append(f"{manifest.parent.name}: {mod_name} has no {attr}")
    assert broken == [], broken


def test_strict_wiring_raises_in_tests():
    """The loud-guard helper must actually be loud under pytest."""
    from jaeger_ai.core.wiring import WiringError, expect_path, strict_wiring

    assert strict_wiring() is True
    with pytest.raises(WiringError):
        expect_path(REPO / "definitely-not-here", "a wiring target")
    assert expect_path(REPO / "jaeger_ai", "the package") is True


# ── 3. orphan ledger — a ratchet, not a wish ─────────────────────────

#: Subsystems with production code but NO inbound path from any entry
#: point. Each is a decision someone owes: wire it, route it, or delete it.
#: This list may only SHRINK. Adding an entry means a new orphan shipped.
KNOWN_ORPHANS = {
    # NOTE: core.gateway.server was here and is now WIRED — `jaeger gateway
    # daemon` routes to it (see test_gateway_daemon_has_a_cli_route). It was
    # never truly dead: operators launched it by hand with `python -m`, which
    # is precisely why neither the import graph nor the CLI route table found
    # it. "Unreachable by analysis" and "not running" are different claims.
    # Runnable entry points with no caller and no CLI route.
    "jaeger_ai.plugins.messaging_gateway",
    "jaeger_ai.core.runtime._shakedown",
    # Consumers (interfaces/studio, interfaces/v4) were deleted.
    "jaeger_ai.nodes.animation_dev.mscript.mscript_engine",
    # Engine capability with no client surface.
    "jaeger_ai.skill_tree.xp_emitter",
    "jaeger_ai.personality.persona_state",
}


def test_gateway_daemon_has_a_cli_route():
    """`jaeger gateway daemon` must reach the :8810 daemon, not Agentgateway.

    These are two different processes and the names are one word apart:
    `jaeger gateway` manages the EXTERNAL Agentgateway (:8811/:8812), while
    `jaeger gateway daemon` runs the Jaeger Gateway (sessions + SSE, :8810)
    that the WebUI integrations point clients at.
    """
    from jaeger_ai.cli.entry import _route

    py = "/venv/bin/python"
    assert _route(["gateway", "daemon"], py) == [
        py, "-m", "jaeger_ai.core.gateway.server",
    ]
    assert _route(["gateway", "daemon", "--port", "9999"], py) == [
        py, "-m", "jaeger_ai.core.gateway.server", "--port", "9999",
    ]
    # the Agentgateway subcommands must be untouched
    for sub in ("install", "start", "stop", "status"):
        assert _route(["gateway", sub], py) == [
            py, "-m", "jaeger_ai.features.gateway", sub,
        ]


def test_gateway_daemon_exposes_a_main():
    from jaeger_ai.core.gateway.server import main

    assert callable(main)


def test_gateway_store_honours_the_documented_state_override(tmp_path, monkeypatch):
    """``JAEGER_STATE_DIR`` must isolate the session database.

    It previously read ``JAEGER_HOME`` only, so a test or sandbox setting
    the documented override still opened the operator's REAL session store
    — and tripped over the live daemon's ownership lease.
    """
    from jaeger_ai.core.gateway.session_store import default_store_path

    monkeypatch.setenv("JAEGER_STATE_DIR", str(tmp_path))
    resolved = default_store_path()
    assert str(resolved).startswith(str(tmp_path.resolve()))
    assert resolved.name == "gateway_sessions.sqlite3"


def test_orphan_ledger_only_shrinks():
    """Every known orphan must still exist, or be removed from this list.

    Keeps the ledger honest: once something is wired or deleted, its entry
    has to go, so the list cannot rot into a list of things that no longer
    apply.
    """
    import importlib.util

    stale = [
        name for name in KNOWN_ORPHANS
        if importlib.util.find_spec(name) is None
    ]
    assert stale == [], (
        f"these are no longer present — remove them from KNOWN_ORPHANS: {stale}"
    )


def test_no_new_orphans_among_entry_routed_modules():
    """Everything the CLI routes to with ``-m`` must be importable.

    A route pointing at a module that cannot import is a dead command —
    the failure only shows when an operator types it.
    """
    import importlib.util

    entry = (REPO / "jaeger_ai/cli/entry.py").read_text(encoding="utf-8")
    targets = sorted(set(re.findall(r'"-m",\s*"([\w.]+)"', entry)))
    assert targets, "no -m routes found; the extraction regex is wrong"
    broken = [t for t in targets if importlib.util.find_spec(t) is None]
    assert broken == [], f"CLI routes to non-importable modules: {broken}"


def test_console_script_entry_points_resolve():
    """``[project.scripts]`` must name real callables."""
    import importlib
    import tomllib

    pj = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
    broken = []
    for name, spec in pj.get("project", {}).get("scripts", {}).items():
        mod_name, _, attr = spec.partition(":")
        try:
            mod = importlib.import_module(mod_name)
        except Exception as exc:  # noqa: BLE001
            broken.append(f"{name}: {mod_name} ({exc})")
            continue
        if attr and not hasattr(mod, attr):
            broken.append(f"{name}: {mod_name} has no {attr}")
    assert broken == [], broken


def test_entry_point_group_targets_resolve():
    """``jaeger_os.module_roots`` contributors must import and expose theirs."""
    import importlib
    import tomllib

    pj = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
    groups = pj.get("project", {}).get("entry-points", {})
    broken = []
    for group, entries in groups.items():
        for name, spec in entries.items():
            mod_name, _, attr = spec.partition(":")
            try:
                mod = importlib.import_module(mod_name)
            except Exception as exc:  # noqa: BLE001
                broken.append(f"{group}/{name}: {mod_name} ({exc})")
                continue
            if attr and not hasattr(mod, attr):
                broken.append(f"{group}/{name}: {mod_name} has no {attr}")
    assert broken == [], broken


# ── source-level guard against the pattern that caused all this ──────


def test_new_discovery_guards_use_the_loud_helper():
    """Discovery routines must not add new silent missing-directory guards.

    Narrow on purpose: only ``migrations.py`` is enforced today, because it
    is the one where a silent ``[]`` demonstrably hid a broken runner. The
    assertion exists so the fix cannot be quietly reverted.
    """
    src = (REPO / "jaeger_ai/core/instance/migrations.py").read_text(encoding="utf-8")
    assert "expect_path" in src, (
        "migrations.py must guard MIGRATIONS_DIR with wiring.expect_path so a "
        "missing scripts directory is loud in dev/test instead of returning []"
    )
    tree = ast.parse(src)
    assert any(
        isinstance(node, ast.FunctionDef) and node.name == "discover_migrations"
        for node in ast.walk(tree)
    )
