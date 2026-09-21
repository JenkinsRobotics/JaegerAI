"""Regression tests for live commissioning gates (no false-positive PASS)."""

from __future__ import annotations

from pathlib import Path

import pytest

from jaeger_ai.core.entity.authority import (
    AuthorityLayer,
    ProposedAction,
    commissioning_authority_policy,
)
from jaeger_ai.core.entity.events import EventType, JaegerEvent
from jaeger_ai.core.entity.recovery import RecoveryManager
from jaeger_ai.core.entity.verification import (
    VerificationRegistry,
    VerificationStatus,
    derive_verification_action,
)
from jaeger_ai.core.instance.commissioning import write_authority_policy
from jaeger_ai.core.instance.commissioning_validation import (
    KIND_DISABLED,
    KIND_LIVE,
    KIND_STRUCTURAL,
    STATUS_DISABLED,
    STATUS_STRUCTURAL_OK,
    run_validation,
)


def test_write_file_is_an_authoritative_external_effect():
    from jaeger_agent.tools import files as _files  # noqa: F401
    from jaeger_os.core.tools.tool_registry import get_tool
    tool = get_tool("write_file")
    assert tool is not None
    assert getattr(tool, "side_effect", "") == "external"


def test_file_write_verification_uses_disk_probe(tmp_path: Path):
    target = tmp_path / "out.txt"
    target.write_text("JAEGER-COMMISSIONING-OK\n", encoding="utf-8")
    started = JaegerEvent.tool_started(
        "write_file",
        {"path": str(target), "content": "JAEGER-COMMISSIONING-OK"},
        call_id="c1",
    )
    completed = JaegerEvent.tool_completed(
        "write_file",
        {"written": True, "path": str(target)},
        call_id="c1",
        duration_s=0.01,
    )
    action = derive_verification_action(
        f"Create {target} containing exactly JAEGER-COMMISSIONING-OK",
        {},
        [started, completed],
        strategy="react_loop",
        context={"workspace": str(tmp_path)},
    )
    assert action["action_type"] == "file_write"
    result = VerificationRegistry().verify(
        f"Create {target} containing exactly JAEGER-COMMISSIONING-OK",
        action,
        {"path": str(target)},
        {"workspace": str(tmp_path)},
    )
    assert result.status == VerificationStatus.OBJECTIVE_VERIFIED
    assert result.verifier == "disk_probe"
    assert str(target) in result.evidence


def test_authority_uses_bound_instance_not_default(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    a = tmp_path / "inst-a"
    b = tmp_path / "inst-b"
    a.mkdir()
    b.mkdir()
    write_authority_policy(a, {
        "filesystem": {"read": True, "write": True, "approved_roots": [str(a)]},
        "shell": {"risk_mode": "confirm"},
        "git": {"local_commit": True, "push": False},
        "protected_merge_deployment": False,
    })
    write_authority_policy(b, {
        "filesystem": {"read": True, "write": False, "approved_roots": [str(b)]},
        "shell": {"risk_mode": "deny"},
        "git": {"local_commit": False, "push": False},
        "protected_merge_deployment": False,
    })
    monkeypatch.setattr(
        "jaeger_ai.core.instance.instance.default_instance_name",
        lambda: "inst-a",
    )
    monkeypatch.setattr(
        "jaeger_ai.core.instance.instance.resolve_instance_dir",
        lambda name=None: a,
    )
    denied = commissioning_authority_policy(ProposedAction(
        tool_name="write_file",
        arguments={"path": "x.txt", "content": "n"},
        context={"instance_root": str(b)},
    ))
    assert not denied.is_authorized
    allowed = commissioning_authority_policy(ProposedAction(
        tool_name="write_file",
        arguments={"path": "x.txt", "content": "y"},
        context={"instance_root": str(a)},
    ))
    assert allowed.is_authorized


def test_offline_validation_does_not_claim_live_write(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("JAEGER_COMMISSIONING_OFFLINE", "1")
    inst = tmp_path / "inst"
    inst.mkdir()
    (inst / "memory").mkdir()
    report = run_validation(inst, groups=("action", "interfaces"), offline=True)
    write = next(c for c in report.checks if c.id == "safe_tool_execution")
    assert write.kind == KIND_STRUCTURAL
    assert write.status == STATUS_STRUCTURAL_OK
    idem = next(c for c in report.checks if c.id == "request_idempotency")
    assert idem.kind == KIND_STRUCTURAL
    webui = next(c for c in report.checks if c.id == "webui_attach")
    assert webui.kind == KIND_DISABLED
    assert webui.status == STATUS_DISABLED
    assert not any(c.kind == KIND_LIVE and c.status == "PASS" for c in report.checks)


def test_recovery_resumes_blocked_run_without_pending_effect(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from types import SimpleNamespace
    from jaeger_agent.memory import sqlite_store
    from jaeger_agent.cognition.sqlite_runs import SqliteRunStore, SqliteEffectLedger
    from jaeger_agent.cognition.sqlite_commitments import SqliteCommitmentStore

    monkeypatch.setenv("JAEGER_STATE_DIR", str(tmp_path))
    sqlite_store.bind(SimpleNamespace(memory_dir=tmp_path))
    commits = SqliteCommitmentStore()
    c = commits.create("turn-loop", kind="turn-loop")
    runs = SqliteRunStore()
    run = runs.create(c.id, owner_pid=999999)
    run = runs.transition(run.id, "active")
    ledger = SqliteEffectLedger()
    ledger.once(f"{run.id}:write_file:{{\"path\":\"a.txt\"}}", "write_file", lambda: {"written": True})
    blocked = runs.recover(is_alive=lambda pid: False)
    assert blocked and blocked[0].id == run.id
    report = RecoveryManager().scan_resumable_runs()
    assert run.id in report.resumed or run.id in report.blocked_runs
    refreshed = runs.get(run.id)
    assert refreshed is not None
    if run.id in report.resumed:
        assert refreshed.state == "active"
    effect = ledger.get(f"{run.id}:write_file:{{\"path\":\"a.txt\"}}")
    assert effect is not None
    assert effect.status == "done"
    _, executed = ledger.once(
        f"{run.id}:write_file:{{\"path\":\"a.txt\"}}", "write_file", lambda: {"written": "AGAIN"}
    )
    assert executed is False


def test_ensure_run_does_not_resume_pending_effect(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from types import SimpleNamespace
    from jaeger_agent.cognition.executive import TURN_LOOP_KIND, TurnExecutive
    from jaeger_agent.cognition.sqlite_commitments import SqliteCommitmentStore
    from jaeger_agent.cognition.sqlite_runs import SqliteEffectLedger, SqliteRunStore
    from jaeger_agent.memory import sqlite_store

    monkeypatch.setenv("JAEGER_STATE_DIR", str(tmp_path))
    sqlite_store.bind(SimpleNamespace(memory_dir=tmp_path))
    commits = SqliteCommitmentStore()
    c = commits.create(TURN_LOOP_KIND, kind=TURN_LOOP_KIND)
    runs = SqliteRunStore()
    run = runs.create(c.id, owner_pid=999999)
    run = runs.transition(run.id, "active")
    ledger = SqliteEffectLedger()
    key = f"{run.id}:write_file:{{\"path\":\"pending.txt\"}}"
    def _boom():
        raise RuntimeError("crash mid-effect")
    try:
        ledger.once(key, "write_file", _boom, run_id=run.id)
    except RuntimeError:
        pass
    assert ledger.get(key) is not None and ledger.get(key).status == "pending"
    runs.recover(is_alive=lambda pid: False)
    class _Agent:
        run_id = None
        last_halt_reason = None
        last_iteration_count = 0
        primary_adapter = SimpleNamespace(name="test")
        def bind_run(self, run_id):
            self.run_id = run_id
        def run_turn(self, text):
            return "ok"
    execu = TurnExecutive(_Agent(), runs, commits, provider="test")
    nxt = execu.ensure_run()
    blocked = runs.get(run.id)
    assert blocked is not None
    assert blocked.state == "blocked"
    assert nxt.id != run.id


def test_completed_turn_does_not_stay_active(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from types import SimpleNamespace
    from jaeger_agent.cognition.executive import TURN_LOOP_KIND, TurnExecutive
    from jaeger_agent.cognition.sqlite_commitments import SqliteCommitmentStore
    from jaeger_agent.cognition.sqlite_runs import SqliteRunStore
    from jaeger_agent.memory import sqlite_store

    monkeypatch.setenv("JAEGER_STATE_DIR", str(tmp_path))
    sqlite_store.bind(SimpleNamespace(memory_dir=tmp_path))
    commits = SqliteCommitmentStore()
    commits.create(TURN_LOOP_KIND, kind=TURN_LOOP_KIND)
    runs = SqliteRunStore()

    class _Agent:
        run_id = None
        last_halt_reason = None
        last_iteration_count = 1
        primary_adapter = SimpleNamespace(name="test")
        def bind_run(self, run_id):
            self.run_id = run_id
        def run_turn(self, text):
            self.last_halt_reason = None
            return "ok"

    agent = _Agent()
    execu = TurnExecutive(agent, runs, commits, provider="test")
    first = execu.run_turn("write a")
    assert first == "ok"
    run = runs.get(agent.run_id)
    assert run is not None
    assert run.state == "completed"
    agent.run_id = None
    nxt = execu.ensure_run()
    assert nxt.id != run.id


def test_autostart_plist_includes_instance_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    from jaeger_ai.cli.verbs import autostart_verb as A
    monkeypatch.setenv("JAEGER_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("JAEGER_GATEWAY_PORT", "18820")
    monkeypatch.setenv("JAEGER_INSTANCE_NAME", "commission-r5")
    txt = A._launchd_plist(tmp_path / "jaeger", tmp_path, ["start", "--no-app"])
    assert "JAEGER_STATE_DIR" in txt
    assert "18820" in txt
    assert "commission-r5" in txt
