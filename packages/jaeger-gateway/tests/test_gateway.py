"""Standalone tests for jaeger-gateway (auth, WAL store, single-fiber coordinator, fenced SSE, HTTP)."""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from aiohttp.test_utils import TestClient, TestServer

from jaeger_gateway import (
    GatewayAuthPolicy,
    GatewayStore,
    RequestConflictError,
    RunCoordinator,
    SessionEventHub,
    StaleWriterError,
    format_sse,
)
from jaeger_gateway.server import create_gateway_app


def test_boot_reconcile_claimed_jobs(tmp_path: Path) -> None:
    """Crash recovery: claimed jobs reconcile from persisted request outcomes;
    unresolved ones become interrupted for review without replaying tools."""
    import json

    db = tmp_path / "gw.sqlite"
    store = GatewayStore(db)
    sess = store.create_session(title="s")
    # Job A: its run request completed with a complete verdict -> done.
    job_a = store.create_scheduled_job(session_id=sess["session_id"], prompt="a", due_at=1.0)
    claim_a = store.claim_due_job(now=2.0)
    assert claim_a is not None and claim_a["job_id"] == job_a["job_id"]
    store.admit_request(sess["session_id"], "a", request_id=claim_a["run_id"])
    store.settle_request(claim_a["run_id"], "completed", {"ok": True, "verdict": "complete", "content": "A done"})
    # Job B: claimed but its request is still running (crash mid-run) -> interrupted.
    job_b = store.create_scheduled_job(session_id=sess["session_id"], prompt="b", due_at=1.0)
    claim_b = store.claim_due_job(now=2.0)
    assert claim_b is not None and claim_b["job_id"] == job_b["job_id"]
    store.admit_request(sess["session_id"], "b", request_id=claim_b["run_id"])
    # Job C: claimed, request row missing entirely -> interrupted.
    job_c = store.create_scheduled_job(session_id=sess["session_id"], prompt="c", due_at=1.0)
    claim_c = store.claim_due_job(now=2.0)
    assert claim_c is not None and claim_c["job_id"] == job_c["job_id"]
    # Job D: request completed but verdict was budget_exhausted -> failed, not done.
    job_d = store.create_scheduled_job(session_id=sess["session_id"], prompt="d", due_at=1.0)
    claim_d = store.claim_due_job(now=2.0)
    assert claim_d is not None and claim_d["job_id"] == job_d["job_id"]
    store.admit_request(sess["session_id"], "d", request_id=claim_d["run_id"])
    store.settle_request(claim_d["run_id"], "completed", {"ok": False, "verdict": "budget_exhausted"})

    reconciled = store.reconcile_claimed_jobs()
    assert sorted(reconciled) == sorted(
        [job_a["job_id"], job_b["job_id"], job_c["job_id"], job_d["job_id"]]
    )
    a = store.get_scheduled_job(job_a["job_id"])
    b = store.get_scheduled_job(job_b["job_id"])
    c = store.get_scheduled_job(job_c["job_id"])
    d = store.get_scheduled_job(job_d["job_id"])
    # Store contract: result is the raw result_json column; decode it.
    assert a["status"] == "done" and json.loads(a["result_json"])["verdict"] == "complete"
    assert b["status"] == "interrupted" and "restarted" in json.loads(b["result_json"])["error"]
    assert c["status"] == "interrupted"
    assert d["status"] == "failed" and json.loads(d["result_json"])["verdict"] == "budget_exhausted"
    # Stable IDs: job IDs unchanged, run IDs persist across reads.
    assert a["run_id"] == claim_a["run_id"] and b["run_id"] == claim_b["run_id"]
    assert c["run_id"] == claim_c["run_id"] and d["run_id"] == claim_d["run_id"]
    # Idempotent: nothing left claimed.
    assert store.reconcile_claimed_jobs() == []


def test_scheduled_job_atomic_claim_and_reopen(tmp_path: Path) -> None:
    db = tmp_path / "gw.sqlite"
    store = GatewayStore(db)
    sess = store.main_chat_session()
    now = time.time()
    job = store.create_scheduled_job(
        session_id=sess["session_id"], prompt="one-shot task", due_at=now - 1, job_id="job_test1"
    )
    assert job["status"] == "pending" and job["job_id"] == "job_test1"

    # Two competing claims: exactly one wins, the other gets None.
    first = store.claim_due_job(now=now)
    second = store.claim_due_job(now=now)
    assert first is not None and first["job_id"] == "job_test1"
    assert first["status"] == "claimed" and first["run_id"]
    assert second is None

    # Not-yet-due job is not claimable.
    store.create_scheduled_job(
        session_id=sess["session_id"], prompt="future", due_at=now + 3600, job_id="job_future"
    )
    assert store.claim_due_job(now=now) is None

    # Settle, then reopen the store: result readable by stable job ID.
    settled = store.settle_scheduled_job("job_test1", status="done", result={"verdict": "complete"})
    assert settled["status"] == "done" and settled["run_id"] == first["run_id"]
    assert '"verdict": "complete"' in settled["result_json"]

    reopened = GatewayStore(db)
    again = reopened.get_scheduled_job("job_test1")
    assert again is not None and again["status"] == "done"
    assert again["run_id"] == first["run_id"]
    assert '"verdict": "complete"' in again["result_json"]
    # Claimed job can never be re-claimed after reopen.
    assert reopened.claim_due_job(now=now + 10) is None


def test_recurring_job_spawns_exactly_one_successor_on_complete(tmp_path: Path) -> None:
    """Fixed-delay recurrence: settling a claimed recurring fire as done with a
    complete verdict inserts exactly one pending successor at completion+interval
    in the same transaction, under the same stable series ID."""
    import json

    db = tmp_path / "gw_recur.sqlite"
    store = GatewayStore(db)
    sess = store.main_chat_session()
    job = store.create_scheduled_job(
        session_id=sess["session_id"], prompt="tick", due_at=100.0, job_id="job_r0",
        recurrence={"interval_s": 60.0, "series_id": "series_test"},
    )
    assert job["status"] == "pending"
    assert job["series_id"] == "series_test" and job["interval_s"] == 60.0
    assert job["fire_seq"] == 0 and job["predecessor_job_id"] is None
    meta = json.loads(job["metadata_json"])
    assert meta["series_id"] == "series_test" and meta["fire_seq"] == 0

    claim = store.claim_due_job(now=200.0)
    assert claim is not None and claim["job_id"] == "job_r0" and claim["run_id"]
    settled = store.settle_scheduled_job("job_r0", status="done", result={"ok": True, "verdict": "complete"})
    assert settled["status"] == "done" and settled["run_id"] == claim["run_id"]
    # Completed fire record is immutable: stable job/run IDs, original due_at.
    assert settled["job_id"] == "job_r0" and settled["due_at"] == 100.0
    assert settled["completed_at"] is not None

    fires = store.list_series_jobs("series_test")
    assert len(fires) == 2
    succ = fires[1]
    assert succ["status"] == "pending" and succ["job_id"] != "job_r0"
    assert succ["series_id"] == "series_test" and succ["interval_s"] == 60.0
    assert succ["predecessor_job_id"] == "job_r0" and succ["fire_seq"] == 1
    # Fixed delay measured from completion, not from the original due time.
    assert succ["due_at"] == pytest.approx(settled["completed_at"] + 60.0)
    assert succ["prompt"] == "tick" and succ["session_id"] == sess["session_id"]
    succ_meta = json.loads(succ["metadata_json"])
    assert succ_meta["fire_seq"] == 1 and succ_meta["predecessor_job_id"] == "job_r0"

    # The successor is claimable once due, and chains the next fire.
    claim2 = store.claim_due_job(now=succ["due_at"] + 1.0)
    assert claim2 is not None and claim2["job_id"] == succ["job_id"]
    settled2 = store.settle_scheduled_job(succ["job_id"], status="done", result={"verdict": "complete"})
    fires = store.list_series_jobs("series_test")
    assert len(fires) == 3
    assert fires[2]["predecessor_job_id"] == succ["job_id"] and fires[2]["fire_seq"] == 2
    assert fires[2]["due_at"] == pytest.approx(settled2["completed_at"] + 60.0)
    # Re-settling an already-settled fire is a no-op and spawns nothing new.
    again = store.settle_scheduled_job("job_r0", status="done", result={"verdict": "complete"})
    assert again["status"] == "done"
    assert len(store.list_series_jobs("series_test")) == 3


def test_recurring_job_non_complete_outcomes_spawn_no_successor(tmp_path: Path) -> None:
    """Failed, cancelled, interrupted, E-Stop and uncertain runs must never
    spawn a successor; one-shot jobs never spawn anything."""
    store = GatewayStore(tmp_path / "gw_norecur.sqlite")
    sess = store.main_chat_session()
    cases = [
        ("job_f", "failed", {"ok": False, "verdict": "failed"}),
        ("job_c", "cancelled", {"ok": False, "verdict": "cancelled"}),
        ("job_i", "failed", {"ok": False, "verdict": "interrupted"}),
        ("job_e", "failed", {"ok": False, "verdict": "estop", "estop": True}),
        ("job_u", "done", {"ok": True}),  # uncertain: no verdict
        ("job_b", "done", {"ok": False, "verdict": "budget_exhausted"}),
    ]
    for jid, status, result in cases:
        store.create_scheduled_job(
            session_id=sess["session_id"], prompt="p", due_at=1.0, job_id=jid,
            recurrence={"interval_s": 30.0, "series_id": f"series_{jid}"},
        )
        claim = store.claim_due_job(now=2.0)
        assert claim is not None and claim["job_id"] == jid
        settled = store.settle_scheduled_job(jid, status=status, result=result)
        assert settled["status"] == status
        assert store.list_series_jobs(f"series_{jid}") == [
            store.get_scheduled_job(jid)
        ], f"{jid} must not spawn a successor"

    # One-shot job settled done/complete spawns nothing (existing behavior kept).
    store.create_scheduled_job(session_id=sess["session_id"], prompt="one", due_at=1.0, job_id="job_oneshot")
    claim = store.claim_due_job(now=2.0)
    assert claim is not None and claim["job_id"] == "job_oneshot"
    store.settle_scheduled_job("job_oneshot", status="done", result={"verdict": "complete"})
    oneshot = store.get_scheduled_job("job_oneshot")
    assert oneshot["status"] == "done" and oneshot["series_id"] is None
    assert store.list_scheduled_jobs(sess["session_id"], status="pending") == []
    # Invalid recurrence parameters are rejected up front.
    for bad in ({"interval_s": 0}, {"interval_s": -5}, {"interval_s": "60"}, {"interval_s": float("inf")}):
        with pytest.raises(ValueError):
            store.create_scheduled_job(
                session_id=sess["session_id"], prompt="x", due_at=1.0,
                recurrence=bad,
            )


def test_reconcile_recovered_complete_recurring_fire_spawns_successor_once(tmp_path: Path) -> None:
    """Restart reconciliation: a claimed recurring fire whose persisted request
    completed with verdict complete is recovered as done and spawns exactly one
    successor; repeating recovery must not duplicate the fire. Interrupted and
    failed recoveries spawn nothing."""
    import json

    db = tmp_path / "gw_recon_recur.sqlite"
    store = GatewayStore(db)
    sess = store.create_session(title="s")
    # Recurring job whose run completed with a complete verdict before the crash.
    store.create_scheduled_job(
        session_id=sess["session_id"], prompt="ok", due_at=1.0, job_id="job_rec_ok",
        recurrence={"interval_s": 120.0, "series_id": "series_rec"},
    )
    claim_ok = store.claim_due_job(now=2.0)
    assert claim_ok is not None and claim_ok["job_id"] == "job_rec_ok"
    store.admit_request(sess["session_id"], "ok", request_id=claim_ok["run_id"])
    store.settle_request(claim_ok["run_id"], "completed", {"ok": True, "verdict": "complete"})
    # Recurring job whose run was still running at crash time -> interrupted.
    store.create_scheduled_job(
        session_id=sess["session_id"], prompt="int", due_at=1.0, job_id="job_rec_int",
        recurrence={"interval_s": 120.0, "series_id": "series_rec"},
    )
    claim_int = store.claim_due_job(now=2.0)
    assert claim_int is not None and claim_int["job_id"] == "job_rec_int"
    store.admit_request(sess["session_id"], "int", request_id=claim_int["run_id"])
    # Recurring job whose request completed but verdict was not complete -> failed.
    store.create_scheduled_job(
        session_id=sess["session_id"], prompt="fail", due_at=1.0, job_id="job_rec_fail",
        recurrence={"interval_s": 120.0, "series_id": "series_rec"},
    )
    claim_fail = store.claim_due_job(now=2.0)
    assert claim_fail is not None and claim_fail["job_id"] == "job_rec_fail"
    store.admit_request(sess["session_id"], "fail", request_id=claim_fail["run_id"])
    store.settle_request(claim_fail["run_id"], "completed", {"ok": False, "verdict": "budget_exhausted"})

    reconciled = store.reconcile_claimed_jobs()
    assert sorted(reconciled) == ["job_rec_fail", "job_rec_int", "job_rec_ok"]
    ok = store.get_scheduled_job("job_rec_ok")
    assert ok["status"] == "done" and ok["run_id"] == claim_ok["run_id"]
    assert json.loads(ok["result_json"])["verdict"] == "complete"
    assert store.get_scheduled_job("job_rec_int")["status"] == "interrupted"
    assert store.get_scheduled_job("job_rec_fail")["status"] == "failed"

    fires = store.list_series_jobs("series_rec")
    assert len(fires) == 4  # three originals + exactly one successor
    succ = [f for f in fires if f["predecessor_job_id"] == "job_rec_ok"]
    assert len(succ) == 1
    succ = succ[0]
    assert succ["status"] == "pending" and succ["series_id"] == "series_rec"
    assert succ["fire_seq"] == 1 and succ["interval_s"] == 120.0
    assert succ["due_at"] == pytest.approx(ok["completed_at"] + 120.0)

    # Repeating recovery is a no-op and never duplicates the successor fire.
    assert store.reconcile_claimed_jobs() == []
    assert len(store.list_series_jobs("series_rec")) == 4
    # Reopening the store and reconciling again still does not duplicate.
    reopened = GatewayStore(db)
    assert reopened.reconcile_claimed_jobs() == []
    assert len(reopened.list_series_jobs("series_rec")) == 4


def test_recurring_schema_migration_on_preexisting_database(tmp_path: Path) -> None:
    """Backward-compatible migration: a database created with the pre-recurrence
    schema gains the new columns in place and keeps existing one-shot rows."""
    import sqlite3

    db = tmp_path / "gw_legacy.sqlite"
    conn = sqlite3.connect(str(db))
    conn.executescript(
        """
        CREATE TABLE sessions (
            session_id TEXT PRIMARY KEY, title TEXT NOT NULL, workspace TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'idle', metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at REAL NOT NULL, updated_at REAL NOT NULL
        );
        CREATE TABLE scheduled_jobs (
            job_id TEXT PRIMARY KEY, session_id TEXT NOT NULL, prompt TEXT NOT NULL,
            due_at REAL NOT NULL, status TEXT NOT NULL DEFAULT 'pending', run_id TEXT,
            result_json TEXT NOT NULL DEFAULT '{}', metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at REAL NOT NULL, claimed_at REAL, completed_at REAL,
            FOREIGN KEY(session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
        );
        INSERT INTO sessions(session_id, title, created_at, updated_at) VALUES ('sess_legacy', 'L', 1.0, 1.0);
        INSERT INTO scheduled_jobs(job_id, session_id, prompt, due_at, status, created_at)
            VALUES ('job_legacy', 'sess_legacy', 'old one-shot', 1.0, 'pending', 1.0);
        """
    )
    conn.commit()
    conn.close()

    store = GatewayStore(db)  # migration runs here
    legacy = store.get_scheduled_job("job_legacy")
    assert legacy is not None and legacy["status"] == "pending"
    assert legacy["series_id"] is None and legacy["interval_s"] is None
    assert legacy["predecessor_job_id"] is None and legacy["fire_seq"] == 0
    # Legacy one-shot still claims and settles without spawning a successor.
    claim = store.claim_due_job(now=2.0)
    assert claim is not None and claim["job_id"] == "job_legacy"
    settled = store.settle_scheduled_job("job_legacy", status="done", result={"verdict": "complete"})
    assert settled["status"] == "done"
    assert store.list_scheduled_jobs("sess_legacy") == [settled]
    # New recurring jobs work on the migrated database.
    sess = store.get_session("sess_legacy")
    job = store.create_scheduled_job(
        session_id=sess["session_id"], prompt="new", due_at=3.0, job_id="job_new",
        recurrence={"interval_s": 10.0, "series_id": "series_migrated"},
    )
    assert job["series_id"] == "series_migrated" and job["fire_seq"] == 0
    claim = store.claim_due_job(now=4.0)
    assert claim is not None and claim["job_id"] == "job_new"
    settled = store.settle_scheduled_job("job_new", status="done", result={"verdict": "complete"})
    fires = store.list_series_jobs("series_migrated")
    assert len(fires) == 2 and fires[1]["due_at"] == pytest.approx(settled["completed_at"] + 10.0)


def test_fail_closed_http_and_websocket_auth() -> None:
    policy = GatewayAuthPolicy(tokens={"secret-tok": "owner:matt"})
    assert not policy.verify_http({}, remote_addr="127.0.0.1").allowed
    assert not policy.verify_http({"Authorization": "Bearer wrong"}, remote_addr="127.0.0.1").allowed
    ok = policy.verify_http({"Authorization": "Bearer secret-tok"}, remote_addr="10.0.0.5")
    assert ok.allowed and ok.actor == "owner:matt"

    # Cross-site WebSocket origin rejected even with valid token
    bad_origin = policy.verify_websocket(
        {"Authorization": "Bearer secret-tok", "Origin": "https://evil.example"},
        remote_addr="127.0.0.1",
    )
    assert not bad_origin.allowed and "origin" in bad_origin.reason
    good_ws = policy.verify_websocket(
        {"Authorization": "Bearer secret-tok", "Origin": "http://127.0.0.1:8790"},
        remote_addr="127.0.0.1",
    )
    assert good_ws.allowed


def test_coordinator_single_fiber_idempotency_and_fenced_sse(tmp_path: Path) -> None:
    store = GatewayStore(tmp_path / "gw.sqlite3")
    hub = SessionEventHub()
    sess = store.create_session(title="Build", workspace=str(tmp_path))
    sid = sess["session_id"]

    active = [0]
    max_concurrent = [0]

    def executor(session_id: str, prompt: str, gen: int, event_hub: SessionEventHub):
        active[0] += 1
        max_concurrent[0] = max(max_concurrent[0], active[0])
        event_hub.publish(session_id, "text.delta", {"delta": f"reply:{prompt}"}, generation=gen)
        time.sleep(0.03)
        active[0] -= 1
        return {"verdict": "complete", "content": f"done:{prompt}"}

    coord = RunCoordinator(store=store, hub=hub, executor=executor)
    try:
        rid1, f1 = coord.submit(sid, "first", request_id="req-1")
        rid2, f2 = coord.submit(sid, "second", request_id="req-2")
        assert f1.result(timeout=5.0)["content"] == "done:first"
        assert f2.result(timeout=5.0)["content"] == "done:second"
        # Single-fiber guarantee: same session never ran concurrently
        assert max_concurrent[0] == 1

        # Idempotent replay with same request_id + payload succeeds without re-running
        rid_replay, f_replay = coord.submit(sid, "first", request_id="req-1")
        assert rid_replay == rid1 and f_replay.result(timeout=2.0)["content"] == "done:first"

        # Conflict on same request_id + different payload raises RequestConflictError
        with pytest.raises(RequestConflictError):
            coord.submit(sid, "TAMPERED", request_id="req-1")

        # Zombie writer from generation 1 is fenced out after generation 2 opened
        with pytest.raises(StaleWriterError):
            hub.publish(sid, "zombie.delta", {"x": 1}, generation=1)

        events = hub.replay_after(sid, after_seq=0)
        assert len(events) >= 4
        sse = format_sse(event=events[0]["event"], data=events[0]["payload"], seq=events[0]["seq"])
        assert f"id: {events[0]['seq']}" in sse and f"event: {events[0]['event']}" in sse
    finally:
        coord.close()


@pytest.mark.asyncio
async def test_gateway_http_and_sse_endpoints(tmp_path: Path) -> None:
    store = GatewayStore(tmp_path / "http_gw.sqlite3")
    hub = SessionEventHub()
    coord = RunCoordinator(
        store=store,
        hub=hub,
        executor=lambda sid, prompt, gen, h: {"verdict": "complete", "content": f"echo:{prompt}"},
    )
    app = create_gateway_app(
        store=store,
        coordinator=coord,
        hub=hub,
        auth=GatewayAuthPolicy(tokens={"tok-1": "owner:test"}),
    )
    try:
        async with TestClient(TestServer(app)) as client:
            assert (await client.get("/health")).status == 200
            assert (await client.get("/v1/sessions")).status == 401

            headers = {"Authorization": "Bearer tok-1"}
            created = await client.post("/v1/sessions", json={"title": "Demo"}, headers=headers)
            assert created.status == 201
            sid = (await created.json())["session"]["session_id"]

            run_resp = await client.post(
                f"/v1/sessions/{sid}/runs",
                json={"prompt": "hello", "wait": True},
                headers=headers,
            )
            assert run_resp.status == 200
            assert (await run_resp.json())["result"]["content"] == "echo:hello"

            sse_resp = await client.get(f"/v1/sessions/{sid}/events?once=1", headers=headers)
            assert sse_resp.status == 200
            body = await sse_resp.text()
            assert "event: run.started" in body and "event: run.completed" in body

            apr = store.create_approval(sid, "shell", "Run deploy?")
            res = await client.post(
                f"/v1/approvals/{apr['approval_id']}/resolve",
                json={"decision": "approve", "note": "lgtm"},
                headers=headers,
            )
            assert res.status == 200
            assert (await res.json())["approval"]["status"] == "approved"
    finally:
        coord.close()


def test_abandoned_run_retains_tool_receipts_without_replay(tmp_path: Path) -> None:
    store = GatewayStore(tmp_path / "recovery.sqlite3")
    session = store.create_session(title="Recovery", workspace=str(tmp_path))
    sid = session["session_id"]
    store.admit_request(sid, "Continue the work", request_id="recovery")
    store.settle_request("recovery", "running", {})
    hub = SessionEventHub(save_tool_receipt=store.save_tool_receipt)
    generation = hub.open_generation(sid, request_id="recovery")
    hub.publish(sid, "tool.completed", {"call_id": "verified", "tool": "read_file", "output": "ok"}, generation=generation)

    reopened = GatewayStore(tmp_path / "recovery.sqlite3")
    reopened.recover_interrupted_runs()
    reopened.recover_interrupted_runs()
    messages = reopened.list_messages(sid)
    assert len(messages) == 1
    assert messages[0]["content"].startswith("The Gateway restarted")
    assert messages[0]["metadata"]["presentation"][0]["output"] == "ok"
    record, replay = reopened.admit_request(sid, "Continue the work", request_id="recovery")
    assert replay and record["status"] == "failed"


def test_detect_voice_intent_sleep_positive_and_negative() -> None:
    from jaeger_gateway.droid_voice import detect_voice_intent

    positives = [
        "Jaeger, go to sleep",
        "Truth, go to sleep",
        "Hey Jaeger go to sleep",
        "please go to sleep",
        "go to sleep",
        "turn off droid",
        "droid go to sleep",
        "droid sleep",
        "park camera",
        "park the camera",
        "shut down droid",
        "power down droid",
        "Jaeger, go to sleep.",
        "Hey Truth, please park the camera!",
        "turn off the droid mode",
        "shut down the droid",
        "power down the droid",
        "turn off droid mode",
        "turn droid mode off",
        "exit droid mode",
        "leave droid mode",
        "disable droid mode",
        "stop droid mode",
        "shut off droid mode",
        "droid mode off",
        "jaeger turn off droid mode",
        "truth turn off droid mode",
        "Jaeger, turn off droid mode",
        "Truth, turn droid mode off please",
        "Hey Jaeger, exit droid mode now",
    ]
    for phrase in positives:
        assert detect_voice_intent(phrase) == "sleep", f"expected sleep intent for {phrase!r}"

    negatives = [
        "",
        "   ",
        "sleep",
        "why do humans go to sleep?",
        "what happens when you go to sleep?",
        "why do people go to sleep?",
        "why do humans go to sleep",
        "Jaeger, why do humans go to sleep?",
        "Truth, what happens when you go to sleep?",
        "I need to go to sleep later",
        "don't go to sleep",
        "do not go to sleep",
        "where do we park the camera?",
        "how do you turn off droid?",
        "how do I turn off droid mode?",
        "how do I turn off droid mode",
        "why would I exit droid mode?",
        "don't turn off droid mode",
        "do not disable droid mode",
        "tell me about droid sleep mode",
    ]
    for phrase in negatives:
        assert detect_voice_intent(phrase) is None, f"unexpected intent for {phrase!r}"


@pytest.mark.asyncio
async def test_droid_status_sleep_wake_estop_and_transcribe_routes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import subprocess

    from jaeger_droid import HostDroidEmbodiment
    from jaeger_orchestration import ResourceGovernor

    # Isolate from real ~/.jaeger/droid/bin/droid-ptz so tests never move physical hardware
    monkeypatch.setenv("JAEGER_STATE_DIR", str(tmp_path))
    ptz = tmp_path / "droid" / "bin" / "droid-ptz"
    ptz.parent.mkdir(parents=True, exist_ok=True)
    ptz.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    ptz.chmod(0o755)
    ptz_calls: list[list[str]] = []
    monkeypatch.setattr(
        "jaeger_droid.host_droid.subprocess.run",
        lambda cmd, **_kw: (ptz_calls.append(list(cmd)), subprocess.CompletedProcess(cmd, 0, stdout='{"ok": true}', stderr=""))[1],
    )

    store = GatewayStore(tmp_path / "droid_gw.sqlite3")
    hub = SessionEventHub()
    coord = RunCoordinator(
        store=store,
        hub=hub,
        executor=lambda sid, prompt, gen, h: {"verdict": "complete", "content": prompt},
    )
    governor = ResourceGovernor()
    droid = HostDroidEmbodiment(probe_on_init=False)
    app = create_gateway_app(
        store=store,
        coordinator=coord,
        hub=hub,
        governor=governor,
        droid_embodiment=droid,
    )
    try:
        async with TestClient(TestServer(app)) as client:
            st = await client.get("/v1/droid/status")
            assert st.status == 200
            st_json = await st.json()
            assert st_json["ok"] is True
            assert st_json["awake"] is True
            assert st_json["sleeping"] is False
            assert st_json["camera"] == "ready"
            assert st_json["estop_active"] is False

            # Sleep parks camera and refuses camera stream + look_at
            sl = await client.post("/v1/droid/sleep", json={"reason": "voice_command"})
            assert sl.status == 200
            sl_json = await sl.json()
            assert sl_json["ok"] is True
            assert sl_json["action"] == "sleep"
            assert sl_json["awake"] is False
            assert sl_json["sleeping"] is True
            assert sl_json["camera"] == "parked"
            assert sl_json["pose"]["tilt_deg"] == -85.0
            assert sl_json["hardware_dispatched"] is True
            assert ptz_calls[-1] == [str(ptz), "abs", "0", "-306000"]

            st2 = await (await client.get("/v1/droid/status")).json()
            assert st2["awake"] is False and st2["sleeping"] is True and st2["camera"] == "parked"

            cam_resp = await client.get("/v1/droid/camera-stream")
            assert cam_resp.status == 503

            act_refused = await client.post(
                "/v1/embodiment/droid/act",
                json={"action": "look_at", "params": {"pan_deg": 20}},
            )
            assert act_refused.status == 409
            assert (await act_refused.json())["error"] == "droid_sleeping"

            # Latch E-Stop: wake MUST fail with 409, sleep MUST STILL succeed with 200
            estop_on = await client.post("/v1/system/estop", json={"active": True, "reason": "safety_check"})
            assert estop_on.status == 200

            st_estop = await (await client.get("/v1/droid/status")).json()
            assert st_estop["estop_active"] is True

            wake_blocked = await client.post("/v1/droid/wake")
            assert wake_blocked.status == 409
            wb_json = await wake_blocked.json()
            assert wb_json["ok"] is False
            assert wb_json["error"] == "estop_active"
            assert wb_json["awake"] is False
            assert wb_json["sleeping"] is True

            act_wake_blocked = await client.post("/v1/embodiment/droid/act", json={"action": "wake"})
            assert act_wake_blocked.status == 409

            sleep_under_estop = await client.post("/v1/droid/sleep")
            assert sleep_under_estop.status == 200
            sue_json = await sleep_under_estop.json()
            assert sue_json["ok"] is True and sue_json["sleeping"] is True and sue_json["camera"] == "parked"

            act_park_under_estop = await client.post("/v1/embodiment/droid/act", json={"action": "park"})
            assert act_park_under_estop.status == 200

            # Release E-Stop: wake succeeds and centers gimbal
            estop_off = await client.post("/v1/system/estop", json={"active": False})
            assert estop_off.status == 200

            woke = await client.post("/v1/droid/wake", json={"reason": "deck_key"})
            assert woke.status == 200
            wk_json = await woke.json()
            assert wk_json["ok"] is True
            assert wk_json["action"] == "wake"
            assert wk_json["awake"] is True
            assert wk_json["sleeping"] is False
            assert wk_json["camera"] == "ready"
            assert wk_json["pose"]["pan_deg"] == 0.0 and wk_json["pose"]["tilt_deg"] == 0.0
            assert ptz_calls[-2:] == [[str(ptz), "abs", "0", "0"], [str(ptz), "zoom", "100"]]

            # /v1/droid/transcribe surfaces sleep intent only for real sleep commands
            monkeypatch.setattr(
                "jaeger_gateway.server.transcribe_clip",
                lambda _audio, enroll=False: {"transcript": "Jaeger, go to sleep"},
            )
            tr_sleep = await client.post("/v1/droid/transcribe", data=b"fake-audio")
            assert tr_sleep.status == 200
            assert await tr_sleep.json() == {"transcript": "Jaeger, go to sleep", "intent": "sleep"}

            monkeypatch.setattr(
                "jaeger_gateway.server.transcribe_clip",
                lambda _audio, enroll=False: {"transcript": "why do humans go to sleep?"},
            )
            tr_q = await client.post("/v1/droid/transcribe", data=b"fake-audio")
            assert tr_q.status == 200
            assert await tr_q.json() == {"transcript": "why do humans go to sleep?"}
    finally:
        coord.close()


@pytest.mark.asyncio
async def test_droid_routes_return_501_when_unavailable(tmp_path: Path) -> None:
    store = GatewayStore(tmp_path / "no_droid.sqlite3")
    hub = SessionEventHub()
    coord = RunCoordinator(
        store=store,
        hub=hub,
        executor=lambda sid, prompt, gen, h: {"verdict": "complete", "content": prompt},
    )
    app = create_gateway_app(store=store, coordinator=coord, hub=hub, droid_embodiment=None)
    try:
        async with TestClient(TestServer(app)) as client:
            assert (await client.get("/v1/droid/status")).status == 501
            assert (await client.post("/v1/droid/sleep")).status == 501
            assert (await client.post("/v1/droid/wake")).status == 501
    finally:
        coord.close()


def test_auth_policy_private_lan_tailscale_and_ws_origins() -> None:
    # Default policy keeps private LAN unauthenticated access disabled (fail-closed)
    strict = GatewayAuthPolicy(allow_loopback_unauthenticated=True)
    assert strict.allow_private_network_unauthenticated is False
    assert strict.verify_http({}, remote_addr="127.0.0.1").actor == "owner:loopback"
    ts_loop = strict.verify_http(
        {"Tailscale-User-Login": "owner@example.com"},
        remote_addr="127.0.0.1",
    )
    assert ts_loop.allowed and ts_loop.actor == "owner:tailscale:owner@example.com"
    assert not strict.verify_http({}, remote_addr="10.0.0.9").allowed
    assert not strict.verify_http({}, remote_addr="100.64.0.42").allowed
    assert not strict.verify_http({}, remote_addr="::ffff:10.0.0.9").allowed
    assert not strict.verify_http({}, remote_addr="8.8.8.8").allowed

    # https://*.ts.net origins are always allowed; http://*.ts.net & public origins rejected
    assert strict.verify_websocket(
        {"Origin": "https://example-studio.tail1234.ts.net"},
        remote_addr="127.0.0.1",
    ).allowed
    assert strict.verify_websocket(
        {"Origin": "https://example-studio.tail1234.ts.net:8443"},
        remote_addr="127.0.0.1",
    ).allowed
    assert not strict.verify_websocket(
        {"Origin": "http://example-studio.tail1234.ts.net"},
        remote_addr="127.0.0.1",
    ).allowed
    assert not strict.verify_websocket(
        {"Origin": "https://evil.com"},
        remote_addr="127.0.0.1",
    ).allowed
    assert not strict.verify_websocket(
        {"Origin": "https://example-studio.tail1234.ts.net.evil.com"},
        remote_addr="127.0.0.1",
    ).allowed
    assert not strict.verify_websocket(
        {"Origin": "http://10.0.0.9:8790"},
        remote_addr="127.0.0.1",
    ).allowed

    # Private LAN + Tailscale CGNAT opt-in allows private ranges while rejecting public IPs
    lan_policy = GatewayAuthPolicy(
        allow_loopback_unauthenticated=True,
        allow_private_network_unauthenticated=True,
    )
    for addr in (
        "10.0.0.9",
        "172.16.0.5",
        "192.168.1.42",
        "169.254.10.2",
        "100.64.0.42",
        "100.64.0.20",
        "::ffff:10.0.0.9",
        "::ffff:100.64.0.42",
        "fd7a:115c:a1e0::42",
        "fe80::1",
        "fc00::1234",
    ):
        dec = lan_policy.verify_http({}, remote_addr=addr)
        assert dec.allowed and dec.actor == "owner:lan", f"expected private allow for {addr!r}"

    for public_or_bad in ("8.8.8.8", "1.1.1.1", "::ffff:8.8.8.8", "2606:4700:4700::1111", "0.0.0.0", "not-an-ip", ""):
        assert not lan_policy.verify_http({}, remote_addr=public_or_bad).allowed, f"must reject {public_or_bad!r}"

    assert lan_policy.verify_websocket(
        {"Origin": "https://example-studio.tail1234.ts.net"},
        remote_addr="100.64.0.42",
    ).allowed
    assert lan_policy.verify_websocket(
        {"Origin": "http://10.0.0.9:8790"},
        remote_addr="10.0.0.9",
    ).allowed
    assert lan_policy.verify_websocket(
        {"Origin": "http://example-studio.local:8790"},
        remote_addr="10.0.0.9",
    ).allowed
    assert lan_policy.verify_websocket(
        {"Origin": "http://[fd7a:115c:a1e0::1]:8790"},
        remote_addr="fd7a:115c:a1e0::42",
    ).allowed
    assert not lan_policy.verify_websocket(
        {"Origin": "https://evil.com"},
        remote_addr="10.0.0.9",
    ).allowed
    assert not lan_policy.verify_websocket(
        {"Origin": "http://8.8.8.8:8790"},
        remote_addr="10.0.0.9",
    ).allowed


@pytest.mark.asyncio
async def test_host_header_tailscale_lan_and_dns_rebinding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = GatewayStore(tmp_path / "host_gw.sqlite3")
    hub = SessionEventHub()
    coord = RunCoordinator(
        store=store,
        hub=hub,
        executor=lambda sid, prompt, gen, h: {"verdict": "complete", "content": prompt},
    )
    strict_app = create_gateway_app(
        store=store,
        coordinator=coord,
        hub=hub,
        auth=GatewayAuthPolicy(allow_loopback_unauthenticated=True),
    )
    monkeypatch.setenv("JAEGER_ALLOWED_HOSTS", "studio.internal, custom.box")
    lan_app = create_gateway_app(
        store=store,
        coordinator=coord,
        hub=hub,
        auth=GatewayAuthPolicy(
            allow_loopback_unauthenticated=True,
            allow_private_network_unauthenticated=True,
        ),
    )
    try:
        async with TestClient(TestServer(strict_app)) as client:
            ok_ts = await client.get("/health", headers={"Host": "example-studio.tail1234.ts.net"})
            assert ok_ts.status == 200
            ok_ts_port = await client.get("/health", headers={"Host": "example-studio.tail1234.ts.net:8443"})
            assert ok_ts_port.status == 200
            ok_v1 = await client.get(
                "/v1/sessions",
                headers={
                    "Host": "example-studio.tail1234.ts.net",
                    "Tailscale-User-Login": "owner@example.com",
                },
            )
            assert ok_v1.status == 200

            for bad_host in (
                "evil.com",
                "evil.com:8790",
                "evil.ts.net.evil.com",
                "ts.net",
                ".ts.net",
                "bad..host.ts.net",
                "10.0.0.9:8790",
                "example-studio.local:8790",
                "8.8.8.8:8790",
            ):
                resp = await client.get("/health", headers={"Host": bad_host})
                assert resp.status == 403, f"expected 403 for Host={bad_host!r}, got {resp.status}"
                assert "invalid Host header" in (await resp.json())["error"]

        async with TestClient(TestServer(lan_app)) as lan_client:
            for ok_host in (
                "example-studio.tail1234.ts.net",
                "10.0.0.9:8790",
                "100.64.0.20:8790",
                "example-studio.local:8790",
                "[fd7a:115c:a1e0::1]:8790",
                "studio.internal:8790",
                "custom.box",
            ):
                resp = await lan_client.get("/health", headers={"Host": ok_host})
                assert resp.status == 200, f"expected 200 for LAN Host={ok_host!r}, got {resp.status}"

            for bad_lan_host in ("evil.com", "8.8.8.8:8790", "evil.local.com", "local"):
                resp = await lan_client.get("/health", headers={"Host": bad_lan_host})
                assert resp.status == 403, f"expected 403 for LAN Host={bad_lan_host!r}, got {resp.status}"
    finally:
        coord.close()


def test_runtime_droid_act_wake_sleep_camera_off_estop_and_env_auth(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import subprocess

    from jaeger_gateway import ModularGatewayRuntime

    state_dir = tmp_path / "state"
    ptz = state_dir / "droid" / "bin" / "droid-ptz"
    ptz.parent.mkdir(parents=True, exist_ok=True)
    ptz.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    ptz.chmod(0o755)

    ptz_calls: list[list[str]] = []
    orig_run = subprocess.run

    def _fake_run(cmd, **kw):
        if cmd and str(cmd[0]) == str(ptz):
            ptz_calls.append(list(cmd))
            return subprocess.CompletedProcess(cmd, 0, stdout='{"ok": true}', stderr="")
        return orig_run(cmd, **kw)

    monkeypatch.setenv("JAEGER_STATE_DIR", str(state_dir))
    monkeypatch.setenv("JAEGER_GATEWAY_TOKEN", "env-secret-token")
    monkeypatch.setenv("JAEGER_ALLOW_LAN_ACCESS", "true")
    monkeypatch.setattr("jaeger_droid.host_droid.subprocess.run", _fake_run)

    rt = ModularGatewayRuntime(state_dir=state_dir, workspace=tmp_path)
    try:
        # Env-configured token + LAN access
        assert rt.auth.allow_private_network_unauthenticated is True
        assert rt.auth.verify_http({"Authorization": "Bearer env-secret-token"}, remote_addr="8.8.8.8").actor == "owner:token"
        assert rt.auth.verify_http({}, remote_addr="10.0.0.9").actor == "owner:lan"
        assert not rt.auth.verify_http({}, remote_addr="8.8.8.8").allowed

        # Tool schema exposes wake, sleep, park
        tool_map = {t["name"]: t for t in rt.tools.list_tools(limit=200)}
        action_enum = tool_map["droid_act"]["schema"]["properties"]["action"]["enum"]
        assert {"wake", "sleep", "park", "camera_off", "camera_on"}.issubset(set(action_enum))

        # camera_off parks camera downward via sleep()
        off_res = rt._droid_act("camera_off", {})
        assert off_res["ok"] is True
        assert off_res["action"] == "sleep"
        assert off_res["sleeping"] is True
        assert off_res["awake"] is False
        assert off_res["camera"] == "parked"
        assert off_res["reason"] == "privacy_shutter"
        assert off_res["pose"]["tilt_deg"] == -85.0
        assert ptz_calls[-1] == [str(ptz), "abs", "0", "-306000"]

        # _look_at_droid refuses while sleeping
        with pytest.raises(RuntimeError, match="Droid is asleep \\(camera parked\\)\\. Wake Droid first\\."):
            rt._look_at_droid("what is on the desk?")

        # wake centers camera and resumes ready state
        wake_res = rt._droid_act("wake", {})
        assert wake_res["ok"] is True
        assert wake_res["awake"] is True
        assert wake_res["sleeping"] is False
        assert wake_res["camera"] == "ready"
        assert wake_res["pose"]["tilt_deg"] == 0.0

        # sleep parks camera with agent_tool reason
        sleep_res = rt._droid_act("sleep", {})
        assert sleep_res["ok"] is True and sleep_res["sleeping"] is True and sleep_res["reason"] == "agent_tool"

        # Governor E-Stop blocks wake and camera_on fail-closed while park/sleep still work
        rt.governor.trigger_estop("safety_test")
        calls_before = len(ptz_calls)
        assert rt._droid_act("wake", {}) == {"ok": False, "error": "estop_active"}
        assert rt._droid_act("camera_on", {}) == {"ok": False, "error": "estop_active"}
        assert len(ptz_calls) == calls_before
        park_res = rt._droid_act("park", {})
        assert park_res["ok"] is True and park_res["sleeping"] is True

        # Releasing governor E-Stop allows camera_on to clear a local privacy_shutter estop and wake
        rt.governor.release_estop()
        rt.droid.estop("privacy_shutter")
        on_res = rt._droid_act("camera_on", {})
        assert on_res["ok"] is True and on_res["awake"] is True and on_res["sleeping"] is False
    finally:
        rt.close()


@pytest.mark.asyncio
async def test_serve_modular_gateway_splits_webui_host_and_private_policy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import asyncio

    import jaeger_gateway.runtime as gw_runtime

    started_sites: list[tuple[str, int, bool]] = []

    class _FakeSite:
        def __init__(self, runner, host: str, port: int) -> None:
            self._runner = runner
            self._host = host
            self._port = port

        async def start(self) -> None:
            # Inspect the app's auth policy indirectly via a fake middleware check
            started_sites.append((self._host, self._port, self._runner.app is not None))

    captured_auths: list[tuple[bool, bool]] = []
    orig_build_app = gw_runtime.ModularGatewayRuntime.build_app

    def _spy_build_app(self, *, serve_ui: bool = False, auth: GatewayAuthPolicy | None = None):
        effective = auth or self.auth
        captured_auths.append((serve_ui, effective.allow_private_network_unauthenticated))
        return orig_build_app(self, serve_ui=serve_ui, auth=auth)

    class _ImmediateEvent(asyncio.Event):
        def __init__(self) -> None:
            super().__init__()
            self.set()

    monkeypatch.setenv("JAEGER_GATEWAY_HOST", "127.0.0.1")
    monkeypatch.setenv("JAEGER_WEBUI_HOST", "0.0.0.0")
    monkeypatch.delenv("JAEGER_ALLOW_LAN_ACCESS", raising=False)
    monkeypatch.setattr(gw_runtime.web, "TCPSite", _FakeSite)
    monkeypatch.setattr(gw_runtime.ModularGatewayRuntime, "build_app", _spy_build_app)
    monkeypatch.setattr(gw_runtime.asyncio, "Event", _ImmediateEvent)

    await gw_runtime.serve_modular_gateway(
        port=43418,
        webui_port=48790,
        state_dir=tmp_path / "state",
        workspace=tmp_path,
    )

    assert started_sites == [("127.0.0.1", 43418, True), ("0.0.0.0", 48790, True)]
    assert captured_auths == [(False, False), (True, True)]


@pytest.mark.asyncio
async def test_cookbook_roundtable_research_and_apple_tools_gateway(tmp_path: Path) -> None:
    from aiohttp.test_utils import TestClient, TestServer
    from jaeger_gateway.runtime import ModularGatewayRuntime
    from jaeger_models import ReplayModel

    rt = ModularGatewayRuntime(state_dir=tmp_path / "state", workspace=tmp_path)
    rt.model = ReplayModel(
        [
            {"content": "Aluminum 6061 is ideal."},
            {"content": "Consensus: Aluminum 6061."},
        ],
        model_id="local/test-model",
    )
    try:
        names = {t["name"] for t in rt.tools.list_tools(limit=200)}
        for expected in (
            "apple_calendar",
            "apple_reminders",
            "apple_notes",
            "model_cookbook",
            "model_roundtable",
            "deep_research",
        ):
            assert expected in names, f"missing tool {expected}"

        app = rt.build_app(serve_ui=False)
        async with TestClient(TestServer(app)) as client:
            r_cb = await client.get("/v1/models/cookbook?ram_gb=32&modality=llm")
            assert r_cb.status == 200
            cb_data = await r_cb.json()
            assert cb_data["ok"] is True and cb_data["count"] >= 4
            assert cb_data["hardware"]["total_ram_gb"] == 32.0

            r_rt = await client.post(
                "/v1/models/roundtable",
                json={"prompt": "Best chassis alloy?", "blind": True, "consensus": True},
            )
            assert r_rt.status == 200
            rt_data = await r_rt.json()
            assert rt_data["ok"] is True and rt_data["blind"] is True
            assert len(rt_data["responses"]) == 1

            r_rep = await client.get("/v1/research/reports")
            assert r_rep.status == 200
            rep_data = await r_rep.json()
            assert rep_data["ok"] is True and rep_data["reports"] == []
    finally:
        rt.close()
