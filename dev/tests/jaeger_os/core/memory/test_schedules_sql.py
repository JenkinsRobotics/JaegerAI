"""DB-5 — schedules table SQL backend."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from jaeger_os.core.memory import memory as mem
from jaeger_os.core.memory import sqlite_store


@pytest.fixture(autouse=True)
def _isolate_store():
    sqlite_store.close()
    yield
    sqlite_store.close()


@pytest.fixture
def bound(tmp_path):
    mem.bind(SimpleNamespace(memory_dir=tmp_path / "memory"))
    yield


# ── add ───────────────────────────────────────────────────────────


def test_add_schedule_returns_legacy_shape(bound):
    out = mem.add_schedule("* * * * *", "ping", name="every_minute")
    assert out["name"] == "every_minute"
    assert out["cron"] == "* * * * *"
    assert out["prompt"] == "ping"
    assert out["cancelled"] is False
    assert out["last_run_at"] is None
    assert out["next_run_at"]


def test_add_schedule_generates_default_name(bound):
    out = mem.add_schedule("*/5 * * * *", "ping")
    assert out["name"].startswith("sched_")


def test_add_schedule_rejects_invalid_cron(bound):
    with pytest.raises(ValueError, match="invalid cron"):
        mem.add_schedule("not-a-cron", "ping")


def test_add_schedule_rejects_empty_prompt(bound):
    with pytest.raises(ValueError):
        mem.add_schedule("* * * * *", "", name="x")


def test_add_schedule_with_existing_name_overwrites(bound):
    """Re-using a name treats it as resurrect-and-replace (matches
    the JSONL semantics where the latest row shadowed the earlier
    one). Status flips back to active even if it was cancelled."""
    mem.add_schedule("* * * * *", "first", name="dup")
    mem.cancel_schedule("dup")
    mem.add_schedule("0 * * * *", "second", name="dup")
    listed = mem.list_schedules()
    assert len(listed) == 1
    assert listed[0]["prompt"] == "second"
    assert listed[0]["cancelled"] is False


# ── list ──────────────────────────────────────────────────────────


def test_list_returns_only_active(bound):
    mem.add_schedule("* * * * *", "active1", name="a")
    mem.add_schedule("* * * * *", "active2", name="b")
    mem.add_schedule("* * * * *", "to_cancel", name="c")
    mem.cancel_schedule("c")
    listed = mem.list_schedules()
    names = {s["name"] for s in listed}
    assert names == {"a", "b"}


def test_list_empty_when_no_schedules(bound):
    assert mem.list_schedules() == []


# ── cancel ────────────────────────────────────────────────────────


def test_cancel_active_returns_true(bound):
    mem.add_schedule("* * * * *", "x", name="kill_me")
    assert mem.cancel_schedule("kill_me") is True
    assert mem.list_schedules() == []


def test_cancel_already_cancelled_returns_false(bound):
    mem.add_schedule("* * * * *", "x", name="kill_me")
    mem.cancel_schedule("kill_me")
    assert mem.cancel_schedule("kill_me") is False


def test_cancel_nonexistent_returns_false(bound):
    assert mem.cancel_schedule("never_existed") is False


def test_cancel_empty_name_returns_false(bound):
    assert mem.cancel_schedule("") is False
    assert mem.cancel_schedule("   ") is False


# ── claim_due_schedules ──────────────────────────────────────────


def test_claim_due_returns_overdue(bound):
    """A schedule whose next_fire_at is BEFORE ``now`` is due."""
    mem.add_schedule("* * * * *", "due_now", name="due")
    # Hack the next_fire_at to a long time ago.
    conn = sqlite_store.connection()
    with sqlite_store.writer() as wconn:
        wconn.execute(
            "UPDATE schedules SET next_fire_at = '2020-01-01T00:00:00+00:00' "
            "WHERE schedule_id = 'due'"
        )
    claimed = mem.claim_due_schedules()
    assert len(claimed) == 1
    assert claimed[0]["name"] == "due"


def test_claim_due_bumps_next_fire_at(bound):
    mem.add_schedule("* * * * *", "x", name="t")
    with sqlite_store.writer() as wconn:
        wconn.execute(
            "UPDATE schedules SET next_fire_at = '2020-01-01T00:00:00+00:00' "
            "WHERE schedule_id = 't'"
        )
    before = sqlite_store.connection().execute(
        "SELECT next_fire_at FROM schedules WHERE schedule_id='t'"
    ).fetchone()["next_fire_at"]
    mem.claim_due_schedules()
    after = sqlite_store.connection().execute(
        "SELECT next_fire_at FROM schedules WHERE schedule_id='t'"
    ).fetchone()["next_fire_at"]
    assert after != before  # bumped forward


def test_claim_due_records_last_fired_at(bound):
    mem.add_schedule("* * * * *", "x", name="t")
    with sqlite_store.writer() as wconn:
        wconn.execute(
            "UPDATE schedules SET next_fire_at = '2020-01-01T00:00:00+00:00' "
            "WHERE schedule_id = 't'"
        )
    mem.claim_due_schedules()
    row = sqlite_store.connection().execute(
        "SELECT last_fired_at FROM schedules WHERE schedule_id='t'"
    ).fetchone()
    assert row["last_fired_at"]  # set


def test_claim_due_skips_cancelled(bound):
    mem.add_schedule("* * * * *", "active", name="a")
    mem.add_schedule("* * * * *", "cancelled", name="b")
    with sqlite_store.writer() as wconn:
        wconn.execute(
            "UPDATE schedules SET next_fire_at = '2020-01-01T00:00:00+00:00'"
        )
    mem.cancel_schedule("b")
    claimed = mem.claim_due_schedules()
    assert [c["name"] for c in claimed] == ["a"]


def test_claim_due_skips_future(bound):
    """A schedule whose next_fire_at is in the future is NOT claimed."""
    future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(timespec="seconds")
    mem.add_schedule("0 0 * * *", "x", name="t")
    with sqlite_store.writer() as wconn:
        wconn.execute(
            "UPDATE schedules SET next_fire_at = ? WHERE schedule_id='t'",
            (future,),
        )
    assert mem.claim_due_schedules() == []


# ── local wall-clock anchoring (scheduler tz bug) ────────────────


def test_near_future_cron_fires_soon_not_a_day_late(bound):
    """Regression: the agent authors cron from LOCAL wall-clock (``get_time``
    returns local time). ``add_schedule`` used to anchor croniter to UTC, so
    a "remind me in 1 minute" style one-shot fired hours late (off by the UTC
    offset). Build a one-shot ~1 minute out and assert next_run_at lands
    ~60s ahead — not most of a day away."""
    from datetime import datetime, timezone, timedelta

    now_local = datetime.now().astimezone()
    tgt = now_local + timedelta(minutes=1)
    cron = f"{tgt.minute} {tgt.hour} {tgt.day} {tgt.month} *"
    out = mem.add_schedule(cron, "check logs", name="soon")

    nxt = datetime.fromisoformat(out["next_run_at"])
    delta = (nxt - now_local).total_seconds()
    assert 0 < delta <= 120, f"expected ~1 min, got {delta}s (tz bug)"


def test_claim_reissues_next_fire_in_local_wallclock(bound):
    """After a fire, the recomputed next_fire_at must also honour local
    wall-clock — a daily 'M H * * *' schedule fires at the local hour."""
    from datetime import datetime, timezone, timedelta

    now_local = datetime.now().astimezone()
    tgt = now_local + timedelta(minutes=1)
    # Daily at the local minute/hour one minute from now.
    cron = f"{tgt.minute} {tgt.hour} * * *"
    mem.add_schedule(cron, "daily ping", name="daily")
    # Force it due, then claim.
    with sqlite_store.writer() as wconn:
        wconn.execute(
            "UPDATE schedules SET next_fire_at = '2020-01-01T00:00:00+00:00' "
            "WHERE schedule_id = 'daily'"
        )
    mem.claim_due_schedules()
    row = sqlite_store.connection().execute(
        "SELECT next_fire_at FROM schedules WHERE schedule_id='daily'"
    ).fetchone()
    nxt = datetime.fromisoformat(row["next_fire_at"])
    # Next fire is within the next 24h and matches the local target minute.
    assert nxt.astimezone().hour == tgt.hour
    assert nxt.astimezone().minute == tgt.minute


def test_cron_runner_fires_persisted_schedule_via_callback(bound):
    """End-to-end at the runner level: a persisted, overdue schedule gets
    claimed and the CronRunner invokes the callback with the prompt and a
    ``cron:<name>`` session key (the shape the bridge relies on)."""
    import threading
    from jaeger_os.agent.background.cron_runner import CronRunner

    mem.add_schedule("* * * * *", "fire me", name="rm")
    with sqlite_store.writer() as wconn:
        wconn.execute(
            "UPDATE schedules SET next_fire_at = '2020-01-01T00:00:00+00:00' "
            "WHERE schedule_id = 'rm'"
        )

    fired: list[tuple[str, str | None]] = []
    done = threading.Event()

    def _cb(prompt, session_key=None):
        fired.append((prompt, session_key))
        done.set()

    runner = CronRunner(_cb, poll_s=1.0)
    runner.start()
    try:
        assert done.wait(timeout=5.0), "cron callback never fired"
    finally:
        runner.shutdown(wait=True)

    assert fired[0][0] == "fire me"
    assert fired[0][1] == "cron:rm"


# ── lazy import from schedules.jsonl ─────────────────────────────


def test_lazy_import_brings_jsonl_into_sql(tmp_path):
    mem_dir = tmp_path / "memory"
    mem_dir.mkdir()
    legacy_rows = [
        {"name": "a", "cron": "* * * * *", "prompt": "p1",
         "created_at": "2026-01-01T00:00:00+00:00",
         "next_run_at": "2026-01-01T00:01:00+00:00",
         "last_run_at": None, "cancelled": False},
        {"name": "b", "cron": "0 * * * *", "prompt": "p2",
         "created_at": "2026-01-01T00:00:00+00:00",
         "next_run_at": "2026-01-01T01:00:00+00:00",
         "last_run_at": None, "cancelled": False},
        # Cancel row for "a" — should drop it.
        {"name": "a", "cancelled": True,
         "cancelled_at": "2026-01-01T00:30:00+00:00"},
    ]
    with (mem_dir / "schedules.jsonl").open("w", encoding="utf-8") as fh:
        for r in legacy_rows:
            fh.write(json.dumps(r) + "\n")

    mem.bind(SimpleNamespace(memory_dir=mem_dir))
    listed = mem.list_schedules()
    names = {s["name"] for s in listed}
    # 'a' was cancelled mid-replay; only 'b' survives.
    assert names == {"b"}


def test_lazy_import_skipped_when_sql_has_rows(tmp_path):
    """Idempotent on re-bind. Pin the no-clobber behaviour."""
    mem_dir = tmp_path / "memory"
    mem_dir.mkdir()

    mem.bind(SimpleNamespace(memory_dir=mem_dir))
    mem.add_schedule("* * * * *", "from_sql", name="real")
    sqlite_store.close()

    # Stale JSONL trying to add a different schedule.
    with (mem_dir / "schedules.jsonl").open("w", encoding="utf-8") as fh:
        fh.write(json.dumps({
            "name": "stale", "cron": "0 0 * * *", "prompt": "x",
            "created_at": "2020", "next_run_at": "2020",
            "last_run_at": None, "cancelled": False,
        }) + "\n")

    mem.bind(SimpleNamespace(memory_dir=mem_dir))
    names = {s["name"] for s in mem.list_schedules()}
    assert names == {"real"}
