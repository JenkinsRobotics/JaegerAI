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
    import json

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
    job_ok = store.create_scheduled_job(
        session_id=sess["session_id"], prompt="ok", due_at=1.0, job_id="job_rec_ok",
        recurrence={"interval_s": 120.0, "series_id": "series_rec"},
    )
    claim_ok = store.claim_due_job(now=2.0)
    assert claim_ok is not None and claim_ok["job_id"] == "job_rec_ok"
    store.admit_request(sess["session_id"], "ok", request_id=claim_ok["run_id"])
    store.settle_request(claim_ok["run_id"], "completed", {"ok": True, "verdict": "complete"})
    # Recurring job whose run was still running at crash time -> interrupted.
    job_int = store.create_scheduled_job(
        session_id=sess["session_id"], prompt="int", due_at=1.0, job_id="job_rec_int",
        recurrence={"interval_s": 120.0, "series_id": "series_rec"},
    )
    claim_int = store.claim_due_job(now=2.0)
    assert claim_int is not None and claim_int["job_id"] == "job_rec_int"
    store.admit_request(sess["session_id"], "int", request_id=claim_int["run_id"])
    # Recurring job whose request completed but verdict was not complete -> failed.
    job_fail = store.create_scheduled_job(
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
