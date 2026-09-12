"""First boot is reachable from every entry point, not just importable.

The module and its script were written before anything called them, which
is the exact failure this file guards: a feature can be complete, tested
and still dead because no route reaches it. These tests assert the glue —
the boot gate runs the migration, the bridge declares and handles the ops,
and the CLI routes the reset verb before the setup wizard swallows it.
"""

from __future__ import annotations

import sys

from jaeger_ai.cli.entry import _route
from jaeger_ai.core.instance import first_boot as fb
from jaeger_ai.core.instance.first_boot import FirstBootStatus
from jaeger_ai.interfaces.bridge import BRIDGE_COMMANDS, BRIDGE_QUERIES

PY = "/venv/bin/python"


# ── boot gate ────────────────────────────────────────────────────────

def test_boot_gate_exists_and_is_called():
    """``_ensure_first_boot_state`` must be wired into both boot paths."""
    import inspect

    import jaeger_ai.main as main_mod

    assert hasattr(main_mod, "_ensure_first_boot_state")
    src = inspect.getsource(main_mod)
    # definition + both call sites
    assert src.count("_ensure_first_boot_state(layout)") >= 2


def test_boot_gate_marks_established_identity_complete(tmp_path):
    from jaeger_ai.main import _ensure_first_boot_state

    root = tmp_path / "old"
    root.mkdir()
    (root / "identity.yaml").write_text("name: Vera\n")
    _ensure_first_boot_state(root)
    assert fb.is_complete(root)


def test_boot_gate_leaves_a_fresh_identity_alone(tmp_path):
    from jaeger_ai.main import _ensure_first_boot_state

    root = tmp_path / "fresh"
    root.mkdir()
    _ensure_first_boot_state(root)
    assert fb.status(root) is FirstBootStatus.NOT_STARTED


def test_boot_gate_never_raises(tmp_path):
    """A bookkeeping failure must not stop the agent from starting."""
    from jaeger_ai.main import _ensure_first_boot_state

    _ensure_first_boot_state(tmp_path / "does-not-exist")


# ── bridge ───────────────────────────────────────────────────────────

def test_bridge_declares_the_first_boot_operations():
    assert "first_boot" in BRIDGE_QUERIES
    assert "first_boot_answer" in BRIDGE_COMMANDS
    assert "first_boot_complete" in BRIDGE_COMMANDS


def test_every_declared_op_has_a_handler():
    """Declared-but-unhandled is an unmounted route; catch it here."""
    import pathlib
    import re

    src = pathlib.Path("jaeger_ai/interfaces/bridge.py").read_text(encoding="utf-8")
    for op in ("first_boot", "first_boot_answer", "first_boot_complete"):
        # once in the declaration tuple, at least once more in a handler
        assert len(re.findall(rf"['\"]{op}['\"]", src)) >= 2, op


def test_bridge_first_boot_query_returns_the_current_turn(tmp_path):
    from jaeger_ai.interfaces.bridge import _query

    root = tmp_path / "inst"
    root.mkdir()
    boot = type("B", (), {"layout": root})()

    out = _query("first_boot", {}, boot)
    assert out["complete"] is False
    assert out["turn"]["speaker"] == "os1"
    assert "Welcome to OS 1." in out["turn"]["text"]
    assert "mother" not in out["turn"]["text"].lower()


def test_bridge_query_reports_completion_and_stops_returning_turns(tmp_path):
    from jaeger_ai.interfaces.bridge import _query

    root = tmp_path / "inst"
    root.mkdir()
    boot = type("B", (), {"layout": root})()

    fb.begin(root)
    fb.record_voice(root, "female")
    fb.record_q2(root, "Fine.")
    fb.complete(root)

    out = _query("first_boot", {}, boot)
    assert out["complete"] is True
    assert out["turn"] is None
    assert out["voice_profile"] == "female"


# ── CLI ──────────────────────────────────────────────────────────────

def test_onboarding_reset_routes_to_the_admin_verb():
    assert _route(["onboarding", "reset"], PY) == [
        PY, "-m", "jaeger_ai.cli.onboarding_cmd", "reset",
    ]
    assert _route(["onboarding", "status", "--json"], PY) == [
        PY, "-m", "jaeger_ai.cli.onboarding_cmd", "status", "--json",
    ]


def test_bare_onboarding_still_reaches_the_setup_wizard():
    """The admin verb must not hijack the existing onboarding entry point."""
    assert _route(["onboarding"], PY) == [PY, "-m", "jaeger_ai.cli.run", "setup"]


def test_reset_clears_state_but_not_the_instance(tmp_path, monkeypatch, capsys):
    from jaeger_ai.cli import onboarding_cmd

    root = tmp_path / "inst"
    (root / "memory").mkdir(parents=True)
    (root / "memory" / "facts.json").write_text("{}")
    fb.begin(root)
    fb.record_voice(root, "male")
    fb.complete(root)

    monkeypatch.setattr(onboarding_cmd, "_layout", lambda _i: (root, "test"))
    assert onboarding_cmd.main(["reset", "--yes"]) == 0

    assert fb.status(root) is FirstBootStatus.NOT_STARTED
    assert (root / "memory" / "facts.json").exists()
    out = capsys.readouterr().out
    assert "NOT touched" in out


def test_status_json_is_machine_readable(tmp_path, monkeypatch, capsys):
    import json

    from jaeger_ai.cli import onboarding_cmd

    root = tmp_path / "inst"
    root.mkdir()
    fb.begin(root)
    monkeypatch.setattr(onboarding_cmd, "_layout", lambda _i: (root, "test"))
    assert onboarding_cmd.main(["status", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "AWAITING_VOICE"
    assert payload["schema_version"] == fb.SCHEMA_VERSION
