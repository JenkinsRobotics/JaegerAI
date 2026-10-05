"""Turn cards settle from evidence the owner checks itself; unverifiable answers go to the owner."""
from __future__ import annotations

import hashlib
import time
from types import SimpleNamespace

import pytest

from jaeger_ai.core.gateway.session_store import GatewaySessionStore
from jaeger_ai.core.tasks.models import TaskState
from jaeger_ai.core.tasks.owner import UNVERIFIABLE, GatewayTaskOwner


@pytest.fixture
def owner(tmp_path):
    store = GatewaySessionStore(tmp_path / "gw.db")
    store.ensure_session("s1", title="t", profile="jaeger")
    gw = SimpleNamespace(store=store, event_bus=SimpleNamespace(publish=lambda *a, **k: None))
    return GatewayTaskOwner(gw)


def _card(owner, tmp_path, text, rid):
    ws = tmp_path / "instance" / "workspace"
    ws.mkdir(parents=True, exist_ok=True)
    return owner.open_turn(session_id="s1", request_id=rid, text=text, strategy="react_loop",
                           owner="owner", workspace=str(ws)), ws


def test_answer_only_turn_is_needs_owner_not_failed(owner, tmp_path):
    task, _ = _card(owner, tmp_path, "What is 17 * 23?", "r1")
    task, receipt = owner.close_turn(task.task_id, {"text": "391"}, status="completed")
    assert task.state == TaskState.NEEDS_OWNER
    assert task.payload["verification"] == {"unverified_answer": "391"}
    assert receipt.verification == "unverified"


def test_named_output_written_during_task_is_verified_by_owner_hash(owner, tmp_path):
    task, ws = _card(owner, tmp_path, "Write the result to workspace/out/result.json", "r2")
    out = ws / "out" / "result.json"
    out.parent.mkdir()
    out.write_text('{"n": 391}')
    task, receipt = owner.close_turn(task.task_id, {"text": "done"}, status="completed")
    assert task.state == TaskState.COMPLETED_VERIFIED
    ev = task.payload["verification"]
    assert ev[0]["kind"] == "owner_file_sha256"
    assert ev[0]["sha256"] == hashlib.sha256(out.read_bytes()).hexdigest()
    assert receipt.verification == "verified"


def test_claimed_but_missing_file_fails(owner, tmp_path):
    task, _ = _card(owner, tmp_path, "Write the result to workspace/out/missing.json", "r3")
    task, _ = owner.close_turn(task.task_id, {"text": "Written to workspace/out/missing.json"}, status="completed")
    assert task.state == TaskState.FAILED
    assert "missing" in task.error


def test_only_preexisting_inputs_is_an_unverified_answer(owner, tmp_path):
    ws = tmp_path / "instance" / "workspace"
    ws.mkdir(parents=True)
    old = ws / "notes.txt"
    old.write_text("x")
    past = time.time() - 3600
    import os
    os.utime(old, (past, past))
    task, _ = _card(owner, tmp_path, "Summarise workspace/notes.txt", "r4")
    task, _ = owner.close_turn(task.task_id, {"text": "a summary"}, status="completed")
    assert task.state == TaskState.NEEDS_OWNER


def test_path_outside_workspace_is_unverifiable(owner, tmp_path):
    task, _ = _card(owner, tmp_path, "Write /etc/elsewhere/x.json", "r5")
    task, _ = owner.close_turn(task.task_id, {"text": "done"}, status="completed")
    assert task.state == TaskState.NEEDS_OWNER


def test_verify_message_is_stable():
    t = SimpleNamespace(goal="hello", payload={"execution": {"workspace": ""}, "artifacts": []}, created_at=0)
    assert GatewayTaskOwner.verify(t, {}) == (False, UNVERIFIABLE)


def test_turn_card_guidance_matches_the_checks_the_owner_runs():
    from jaeger_ai.core.tasks.owner import EVIDENCE_CONTRACT, TURN_CARD_GUIDANCE
    assert "hashed" in TURN_CARD_GUIDANCE and "unverified" in TURN_CARD_GUIDANCE
    assert "rather than guess" in TURN_CARD_GUIDANCE
    assert EVIDENCE_CONTRACT in TURN_CARD_GUIDANCE  # the ledger route still counts
