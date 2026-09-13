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
    assert "Welcome to" in out["turn"]["text"] and "OS 1" in out["turn"]["text"]
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
    # begin() now opens on Probe 1, not the voice question.
    assert payload["status"] == "AWAITING_BENCH"
    assert payload["schema_version"] == fb.SCHEMA_VERSION


# ── probe telemetry reaches the state machine ────────────────────────

def test_bridge_routes_the_social_probe_with_telemetry(tmp_path):
    """The acoustic evidence must survive the bridge hop.

    The client measures latency and energy variance; if the handler drops
    them, hesitance is read from hedging words alone and a long silent
    pause before a confident answer reads as confidence.
    """
    from jaeger_ai.interfaces.bridge import _command

    root = tmp_path / "inst"
    root.mkdir()
    boot = type("B", (), {"layout": root})()
    fb.begin(root)

    ok, _ = _command("first_boot_answer", {
        "question": "social", "reply": "Social.",
        "latency_ms": 2600, "energy_variance": 0.1,
    }, boot)
    assert ok

    # A confident word with a 2.6 s pause must still read as hesitance.
    assert fb.status(root) is FirstBootStatus.AWAITING_HESITANCE
    signals = fb.snapshot(root)["social_signals"]
    assert signals["latency_ms"] == 2600
    assert signals["hesitance"]["value"] is True


def test_bridge_routes_the_hesitance_reply(tmp_path):
    from jaeger_ai.interfaces.bridge import _command

    root = tmp_path / "inst"
    root.mkdir()
    boot = type("B", (), {"layout": root})()
    fb.begin(root)
    fb.record_social(root, "Well, I guess?", latency_ms=2400)

    ok, _ = _command("first_boot_answer",
                     {"question": "hesitance", "reply": "No, not really."}, boot)
    assert ok
    assert fb.snapshot(root)["hesitance_confirmed"] is False
    assert fb.status(root) is FirstBootStatus.AWAITING_VOICE


def test_missing_telemetry_degrades_to_text_only(tmp_path):
    """A typed answer has no acoustics and must not be rejected."""
    from jaeger_ai.interfaces.bridge import _command

    root = tmp_path / "inst"
    root.mkdir()
    boot = type("B", (), {"layout": root})()
    fb.begin(root)

    ok, _ = _command("first_boot_answer",
                     {"question": "social", "reply": "Anti-social."}, boot)
    assert ok
    assert fb.status(root) is FirstBootStatus.AWAITING_VOICE


def test_malformed_telemetry_is_ignored_not_fatal(tmp_path):
    from jaeger_ai.interfaces.bridge import _command

    root = tmp_path / "inst"
    root.mkdir()
    boot = type("B", (), {"layout": root})()
    fb.begin(root)

    ok, _ = _command("first_boot_answer", {
        "question": "social", "reply": "Social.",
        "latency_ms": "not-a-number", "energy_variance": None,
    }, boot)
    assert ok


def test_bridge_replay_preserves_instance_configuration(tmp_path):
    from types import SimpleNamespace
    from jaeger_ai.interfaces.bridge import _command, _query
    (tmp_path / "config.yaml").write_text("model: preserved\n")
    boot = SimpleNamespace(layout=tmp_path)
    fb.begin(tmp_path)
    fb.record_voice(tmp_path, "female")
    fb.record_q2(tmp_path, "skip")
    fb.complete(tmp_path)
    assert _command("first_boot_reset", {}, boot) == (True, None)
    state = _query("first_boot", {}, boot)
    assert not state["complete"]
    assert state["status"] == "AWAITING_BENCH"
    assert (tmp_path / "config.yaml").read_text() == "model: preserved\n"
