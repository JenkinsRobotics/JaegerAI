"""One Gateway turn path: conversation stays a conversation, work becomes one TaskCard.

These drive the real ``JaegerGatewayApp._execute_turn_inner`` with the real
``GatewayTaskOwner``, store, verifier and ``authoritative_transition``. Only the
model worker is replaced, because a model is not available to unit tests.
"""
from __future__ import annotations

import asyncio
import hashlib
import threading
from types import SimpleNamespace

import pytest

from jaeger_ai.core.entity.events import JaegerEvent
from jaeger_ai.core.entity.executive import ExecutiveStrategySelector
from jaeger_ai.core.entity.runtime import EntityRuntime, PreparedTurn
from jaeger_ai.core.gateway.event_bus import project_presence
from jaeger_ai.core.gateway.server import JaegerGatewayApp
from jaeger_ai.core.gateway.session_store import GatewaySessionStore
from jaeger_ai.core.tasks.models import TaskState

REQUEST = "inspect this project and create a verified report"


class _Runtime:
    """What the Gateway reads from the resident Entity around a turn."""

    def __init__(self, workspace):
        self.executive_selector = ExecutiveStrategySelector()
        self.current_state = SimpleNamespace(active_goals=[])
        self.identity = SimpleNamespace(entity_id="jaeger-entity-test", display_name="Jaeger")
        self.layout = SimpleNamespace(workspace_dir=workspace)
        self.finished: list[str] = []
        self.claims: list[tuple[str, str, str, str]] = []

    def record_world_claim(self, subject, predicate, value, *, provenance, **_):
        self.claims.append((subject, predicate, str(value), provenance))

    def prepare_turn(self, text, *, session_id, **_):
        event = JaegerEvent.human_message(text, actor="human:operator", source="gateway", session_id=session_id)
        return PreparedTurn(prompt=text, event=event, user_text=text, session_id=session_id)

    def finish_turn(self, prepared, response_text):
        self.finished.append(response_text)


@pytest.fixture
def env(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    runtime = _Runtime(workspace)
    monkeypatch.setattr(EntityRuntime, "get_singleton", classmethod(lambda cls, *a, **k: runtime))
    app = JaegerGatewayApp(store=GatewaySessionStore(tmp_path / "gateway.sqlite3"))
    app.store.ensure_session("s", workspace=str(workspace))
    monkeypatch.setattr(app, "_resolve_session_agent", lambda sid: None)
    return SimpleNamespace(app=app, workspace=workspace, runtime=runtime)


def _execution(env):
    return {"model": "test-model", "workspace": str(env.workspace), "caller": "human:operator", "options": {}}


async def _run(env, text, request_id, *, worker):
    env.app._continued_owner_react = lambda prompt, **kw: worker(prompt, **kw)
    admitted = env.app.store.admit_request("s", text, request_id=request_id)
    await env.app._execute_turn("s", admitted["turn_id"], text, request_id=request_id, execution=_execution(env))
    return env.app.store.get_request(request_id)


def _events(env, *names):
    return [e for e in env.app.event_bus.get_replay_events("s", since_event_id=0) if e.event in names]


def _states(env):
    return [e.data["state"] for e in _events(env, "jaeger.state")]


def _evidence_for(path):
    return {"text": "Report written.", "task_completion": {"ok": True, "verification_receipts": [
        {"kind": "file_sha256", "path": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}]}}


@pytest.mark.asyncio
async def test_hello_is_a_conversation_and_creates_no_task(env):
    row = await _run(env, "hello", "r-hello", worker=lambda prompt, **kw: {"text": "Hello.", "status": "completed"})

    assert row["status"] == "completed"
    assert row["result"]["output"] == "Hello."
    assert env.app.task_owner.store.list_tasks() == []
    assert "receipt" not in row["result"] and "task_id" not in row["result"]
    assert _states(env) == ["listening", "thinking", "done"]
    assert _events(env, "task.created", "task.updated") == []


@pytest.mark.asyncio
async def test_operational_request_becomes_one_verified_task_with_one_receipt(env):
    report = env.workspace / "report.md"

    def worker(prompt, **kw):
        report.write_text("# Project report\nfiles inspected: 12\n")
        return _evidence_for(report)

    row = await _run(env, REQUEST, "r-work", worker=worker)

    [task] = env.app.task_owner.store.list_tasks()
    assert task.state == TaskState.COMPLETED_VERIFIED
    assert task.provenance["turn_owned"] and task.provenance["session_id"] == "s"
    assert task.payload["turn_card"]["goal"] == REQUEST
    assert task.payload["turn_card"]["strategy"] in {"react_loop", "deliberate_planning", "specialist_delegation"}
    assert task.payload["verification"][0]["sha256"]

    result = row["result"]
    assert row["status"] == "completed"
    assert result["task_id"] == task.task_id and result["task_state"] == "completed_verified"
    assert result["receipt"]["verification"] == "verified"
    assert result["receipt"]["entity_id"] == "jaeger-entity-test"
    assert result["receipt"]["task_id"] == task.task_id

    assert _states(env) == ["listening", "thinking", "planning", "working", "verifying", "done"]
    assert len(_events(env, "task.created")) == 1
    assert _events(env, "task.updated")[-1].data["task"]["state"] == "completed_verified"
    # One terminal event for the one request, in the same session.
    assert [e.event for e in _events(env, "turn.finish", "turn.failed")] == ["turn.finish"]
    assert env.app.store.get_session("s")["messages"][-1]["content"] == "Report written."


@pytest.mark.asyncio
@pytest.mark.parametrize("claim", [
    {"text": "Done."},
    {"text": "success"},
    {"text": "ok", "task_completion": {"ok": True, "success": True, "status": "done"}},
    {"text": "", "task_completion": {"ok": True, "verification_receipts": []}},
])
async def test_a_bare_claim_never_becomes_completed_verified(env, claim):
    row = await _run(env, REQUEST, "r-bare", worker=lambda prompt, **kw: dict(claim))

    [task] = env.app.task_owner.store.list_tasks()
    assert task.state == TaskState.FAILED
    assert row["result"]["task_state"] == "failed"
    assert row["result"]["receipt"]["verification"] == "unverified"
    assert _states(env)[-1] == "failed"


@pytest.mark.asyncio
async def test_a_worker_cannot_choose_the_task_state(env):
    forged = {"text": "all good", "state": "completed_verified", "task_state": "completed_verified",
              "status": "completed_verified", "verification": "verified", "evidence": "trust me"}
    row = await _run(env, REQUEST, "r-forge", worker=lambda prompt, **kw: dict(forged))

    [task] = env.app.task_owner.store.list_tasks()
    assert task.state == TaskState.FAILED
    assert row["result"]["task_state"] == "failed"


@pytest.mark.asyncio
async def test_a_receipt_for_a_file_that_changed_afterwards_does_not_verify(env):
    report = env.workspace / "report.md"

    def worker(prompt, **kw):
        report.write_text("original")
        evidence = _evidence_for(report)
        report.write_text("changed after the receipt")
        return evidence

    await _run(env, REQUEST, "r-tamper", worker=worker)

    [task] = env.app.task_owner.store.list_tasks()
    assert task.state == TaskState.FAILED


@pytest.mark.asyncio
async def test_owner_decline_ends_the_task_as_blocked(env):
    def worker(prompt, **kw):
        env.app._owner_declined.add("r-deny")
        return {"text": "I could not write the file: the owner declined.", "halt_reason": "blocked",
                "evidence": {"declined_by_owner": True}}

    row = await _run(env, REQUEST, "r-deny", worker=worker)

    [task] = env.app.task_owner.store.list_tasks()
    assert task.state == TaskState.BLOCKED
    assert row["result"]["task_state"] == "blocked"
    assert _states(env)[-1] == "blocked"


@pytest.mark.asyncio
async def test_needs_owner_is_distinct_from_blocked_and_failed(env):
    row = await _run(env, REQUEST, "r-need", worker=lambda prompt, **kw: {
        "text": "Which project do you mean?", "halt_reason": "needs_owner", "evidence": {"question": "which project?"}})

    [task] = env.app.task_owner.store.list_tasks()
    assert task.state == TaskState.NEEDS_OWNER
    assert _states(env)[-1] == "needs_owner"
    assert row["result"]["receipt"]["state"] == "needs_owner"


@pytest.mark.asyncio
async def test_cancelling_a_running_turn_settles_the_task_as_cancelled(env):
    def worker(prompt, **kw):
        env.app._cancellations.cancel("r-cancel")
        return {"text": "partial"}

    await _run(env, REQUEST, "r-cancel", worker=worker)

    [task] = env.app.task_owner.store.list_tasks()
    assert task.state == TaskState.CANCELLED
    assert _states(env)[-1] == "stopped"


@pytest.mark.asyncio
async def test_global_stop_cancelling_the_turn_task_never_leaves_the_card_running(env):
    started, release = threading.Event(), threading.Event()

    def worker(prompt, **kw):
        started.set()
        release.wait(10)
        return {"text": "late"}

    env.app._continued_owner_react = lambda prompt, **kw: worker(prompt, **kw)
    admitted = env.app.store.admit_request("s", REQUEST, request_id="r-stop")
    running = asyncio.create_task(env.app._execute_turn(
        "s", admitted["turn_id"], REQUEST, request_id="r-stop", execution=_execution(env)))
    while not started.is_set():
        await asyncio.sleep(0.01)
    running.cancel()                                  # what _halt_for_stop does to _running_tasks
    await asyncio.gather(running, return_exceptions=True)
    release.set()

    [task] = env.app.task_owner.store.list_tasks()
    assert task.state == TaskState.CANCELLED
    assert not task.state == TaskState.COMPLETED_VERIFIED


@pytest.mark.asyncio
async def test_the_same_request_replayed_admits_one_card(env):
    owner = env.app.task_owner
    first = owner.open_turn(session_id="s", request_id="r-same", text=REQUEST, strategy="react_loop", owner="o")
    again = owner.open_turn(session_id="s", request_id="r-same", text=REQUEST, strategy="react_loop", owner="o")
    assert first.task_id == again.task_id
    assert len(owner.store.list_tasks()) == 1


@pytest.mark.asyncio
async def test_the_scheduler_never_runs_a_turn_owned_card(env, monkeypatch):
    env.app.task_owner.open_turn(session_id="s", request_id="r-sched", text=REQUEST, strategy="react_loop", owner="o")
    started = []
    monkeypatch.setattr(env.app.task_owner, "_execute", lambda tid: started.append(tid))
    await env.app.task_owner.tick()
    assert started == []


@pytest.mark.asyncio
async def test_settle_cannot_claim_verified_without_evidence(env):
    owner = env.app.task_owner
    task = owner.open_turn(session_id="s", request_id="r-claim", text=REQUEST, strategy="react_loop", owner="o")
    settled = owner.settle_turn_card(task.task_id, TaskState.COMPLETED_VERIFIED, evidence="success")
    assert settled.state == TaskState.FAILED


@pytest.mark.asyncio
async def test_a_stranded_card_is_settled_after_its_request_ended(env, monkeypatch):
    import time as _time
    owner = env.app.task_owner
    task = owner.open_turn(session_id="s", request_id="r-strand", text=REQUEST, strategy="react_loop", owner="o")
    await owner.tick()                                  # too fresh: left alone
    assert owner.store.get_task(task.task_id).state == TaskState.QUEUED
    real = _time.time
    monkeypatch.setattr("jaeger_ai.core.tasks.owner.time.time", lambda: real() + 120)
    await owner.tick()
    assert owner.store.get_task(task.task_id).state == TaskState.FAILED


def test_presence_states_are_validated_and_projected(env):
    bus = env.app.event_bus
    with pytest.raises(ValueError):
        bus.publish_state("s", "dancing")
    for state in ("idle", "listening", "thinking", "planning", "working", "observing", "waiting",
                  "needs_owner", "blocked", "verifying", "done", "failed", "stopped", "offline"):
        bus.publish_state("s", state, task_id="t1")
    events = bus.get_replay_events("s", since_event_id=0)
    assert [e.data["state"] for e in events if e.event == "jaeger.state"][-1] == "offline"
    bus.publish_state("s", "needs_owner", task_id="t1", approval_required=True)
    view = project_presence(bus.get_replay_events("s", since_event_id=0), session_id="s")
    assert view["state"] == "needs_owner" and view["owner_needed"] is True and view["task_id"] == "t1"
    assert project_presence([], session_id="x")["state"] == "idle"


@pytest.mark.asyncio
async def test_world_claims_keep_planned_observed_and_verified_apart(env):
    report = env.workspace / "report.md"

    def worker(prompt, **kw):
        report.write_text("# report\nfiles: 3\n")
        return _evidence_for(report)

    await _run(env, REQUEST, "r-claims", worker=worker)

    [task] = env.app.task_owner.store.list_tasks()
    assert [(c[0], c[1], c[3]) for c in env.runtime.claims] == [
        (task.task_id, "planned_strategy", "planned"),
        (task.task_id, "worker_evidence", "observed"),
        (task.task_id, "completed_verified", "verified"),
    ]


@pytest.mark.asyncio
async def test_an_unverified_turn_records_a_plan_but_never_a_verified_claim(env):
    await _run(env, REQUEST, "r-noclaim", worker=lambda prompt, **kw: {"text": "done"})
    assert [c[3] for c in env.runtime.claims] == ["planned"]


@pytest.mark.asyncio
async def test_a_conversation_records_no_world_claims(env):
    await _run(env, "hello", "r-chat", worker=lambda prompt, **kw: {"text": "Hello."})
    assert env.runtime.claims == []


def test_the_resident_entity_persists_claims_with_the_four_epistemic_kinds(tmp_path):
    from jaeger_ai.core.entity.ownership import EntityRuntimeMode

    entity = EntityRuntime(state_root=tmp_path, mode=EntityRuntimeMode.TEST)
    for kind in ("observed", "inferred", "planned", "verified"):
        entity.record_world_claim("task-1", f"is_{kind}", "yes", provenance=kind)
    stored = {c["predicate"]: c["provenance"] for c in entity.memory_subsystem.semantic.query_claims("task-1")}
    assert stored == {"is_observed": "observed", "is_inferred": "inferred",
                      "is_planned": "planned", "is_verified": "verified"}


# ── the worker and the verifier agree on evidence ───────────────────────────

COUNT_ONLY = {"ok": True, "verification_receipts": [{"kind": "ledger_count", "done": 4, "total": 4, "remaining": 0}]}
FILE_RECEIPT = {"ok": True, "verification_receipts": [
    {"kind": "ledger_count", "done": 1, "total": 1, "remaining": 0},
    {"kind": "file_sha256", "path": "report.md", "sha256": "ab" * 32}]}


def test_only_a_file_receipt_counts_as_evidence_a_count_does_not():
    from jaeger_ai.core.tasks.owner import has_file_receipt
    assert not has_file_receipt(None)
    assert not has_file_receipt({})
    assert not has_file_receipt(COUNT_ONLY)
    assert not has_file_receipt({**FILE_RECEIPT, "ok": False})
    assert has_file_receipt(FILE_RECEIPT)


def _scripted_worker(env, monkeypatch, completions, *, decline_in_step=None):
    """Calls the real continuation loop; the model's tool results are scripted per step."""
    calls: list[str] = []

    def owner_react(prompt, **kwargs):
        calls.append(prompt)
        if decline_in_step == len(calls):
            env.app._owner_declined.add("r")           # the owner answers an approval card mid-step
        return {"text": f"step {len(calls)}", "status": "completed"}

    def last_completion():
        return completions[min(len(calls), len(completions) - 1)]

    monkeypatch.setattr(env.app, "_owner_react_turn", owner_react)
    monkeypatch.setattr("jaeger_ai.core.runtime.work_ledger.last_completion", last_completion)
    monkeypatch.setattr("jaeger_ai.core.runtime.autonomous_runner.last_completion", last_completion)
    return calls


def _turn_owned(env):
    return {**_execution(env), "options": {"task_id": "turn:r", "turn_owned": True}}


def test_a_count_only_completion_gets_one_correction_that_names_the_evidence_contract(env, monkeypatch):
    calls = _scripted_worker(env, monkeypatch, [None, COUNT_ONLY, FILE_RECEIPT])

    result = env.app._continued_owner_react("write the report", session_key="s", request_id="r",
                                           execution=_turn_owned(env), objective="write the report")

    assert len(calls) == 2
    assert "Owner verification requires correction" in calls[1] and "paths_exist" in calls[1]
    assert result["task_completion"] == FILE_RECEIPT


def test_a_completion_that_already_has_a_file_receipt_is_not_asked_again(env, monkeypatch):
    calls = _scripted_worker(env, monkeypatch, [None, FILE_RECEIPT])
    result = env.app._continued_owner_react("write the report", session_key="s", request_id="r",
                                           execution=_turn_owned(env), objective="write the report")
    assert len(calls) == 1 and result["task_completion"] == FILE_RECEIPT


def test_a_declined_approval_gets_no_correction_and_no_further_push(env, monkeypatch):
    calls = _scripted_worker(env, monkeypatch, [None, None, None], decline_in_step=1)
    result = env.app._continued_owner_react("write the report", session_key="s", request_id="r",
                                           execution=_turn_owned(env), objective="write the report")
    assert len(calls) == 1 and result["halt_reason"] == "blocked"


@pytest.mark.asyncio
async def test_an_unanswered_approval_settles_needs_owner_not_blocked(env):
    def worker(prompt, **kw):
        env.app._owner_unanswered.add("r-unans")          # the approval card expired unanswered
        return {"text": "I need your approval to run that.", "halt_reason": "needs_owner",
                "evidence": {"approval_unanswered": True}}

    await _run(env, REQUEST, "r-unans", worker=worker)

    [task] = env.app.task_owner.store.list_tasks()
    assert task.state == TaskState.NEEDS_OWNER
    assert _states(env)[-1] == "needs_owner"


def test_expiry_and_decline_are_recorded_apart(env, monkeypatch):
    from jaeger_ai.core.gateway.server import _GatewayToolConfirmationProvider

    provider = _GatewayToolConfirmationProvider(env.app, "s", "r-expiry")
    assert provider._decided(False) is False
    assert "r-expiry" in env.app._owner_declined
    env.app._owner_unanswered.add("r-late")
    late = _GatewayToolConfirmationProvider(env.app, "s", "r-late")
    assert late._decided(False) is False
    assert "r-late" not in env.app._owner_declined and "r-late" in env.app._owner_unanswered
    assert provider._decided(True) is True


def test_the_verifier_rechecks_the_file_the_ledger_hashed_not_the_name_the_model_gave(env):
    import hashlib

    owner = env.app.task_owner
    task = owner.open_turn(session_id="s", request_id="r-resolved", text=REQUEST, strategy="react_loop", owner="o",
                           workspace=str(env.workspace))
    report = env.workspace / "report.md"
    report.write_text("# real report\n")
    receipt = {"kind": "file_sha256", "path": "workspace/report.md",          # the model's own convention
               "resolved": str(report), "sha256": hashlib.sha256(report.read_bytes()).hexdigest()}
    verified, evidence = owner.verify(owner.store.get_task(task.task_id), {"task_completion": {"ok": True, "verification_receipts": [receipt]}})
    assert verified, evidence

    outside = env.workspace.parent / "elsewhere.txt"
    outside.write_text("not in the workspace")
    forged = {**receipt, "resolved": str(outside), "sha256": hashlib.sha256(outside.read_bytes()).hexdigest()}
    verified, evidence = owner.verify(owner.store.get_task(task.task_id), {"task_completion": {"ok": True, "verification_receipts": [forged]}})
    assert not verified and "outside" in evidence
