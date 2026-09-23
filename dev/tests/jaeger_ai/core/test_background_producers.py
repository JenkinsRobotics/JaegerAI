"""Lease-gated cron / idle / webhook producers (R02/C01 gap C)."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from jaeger_ai.core.instance.instance import InstanceLayout
from jaeger_ai.core.instance.schemas import Config, HeartbeatConfig, ModelConfig, WebhookConfig, dump_yaml, load_yaml
from jaeger_ai.core.runtime.background_producers import (
    BackgroundProducers,
    cron_request_id,
    webhook_request_id,
)
from jaeger_ai.core.runtime.webhooks import interpret


class _Sink:
    def __init__(self):
        self.turns = []
        self.busy = False

    def is_busy(self):
        return self.busy

    def last_user_quiet_s(self):
        return 10_000.0

    def last_user_session(self):
        return "desktop-app"

    def submit_turn(self, prompt, *, session, request_id, source):
        self.turns.append({
            "prompt": prompt, "session": session,
            "request_id": request_id, "source": source,
        })
        return {"text": f"echo:{prompt}", "status": "completed"}


def _cfg(**kwargs) -> Config:
    return Config(instance_name="inst", model=ModelConfig(model_path="/dev/null"), **kwargs)


def _layout(tmp_path: Path) -> InstanceLayout:
    root = tmp_path / "inst"
    lay = InstanceLayout(root=root)
    lay.ensure_dirs()
    return lay


def test_cron_and_webhook_request_ids_are_stable_per_occurrence():
    assert cron_request_id("remind", "2026-09-22T00:00:00+00:00") == (
        "cron:remind:2026-09-22T00:00:00+00:00"
    )
    assert webhook_request_id("abc") == "webhook:abc"
    first = webhook_request_id(None)
    second = webhook_request_id(None)
    assert first.startswith("webhook:") and first != second


def test_webhook_interpret_keeps_turn_action():
    parsed = interpret("/hook", {"action": "turn", "prompt": "Say hi", "title": "t"})
    assert parsed["action"] == "turn" and parsed["prompt"] == "Say hi"


def test_only_one_process_starts_producers(tmp_path, monkeypatch):
    lay = _layout(tmp_path)
    started = []

    class _FakeCron:
        def __init__(self, cb, **kwargs):
            self.cb = cb
        def start(self):
            started.append("cron")
        def shutdown(self, wait=True):
            started.append("stop")

    monkeypatch.setattr("jaeger_agent.background.cron_runner.CronRunner", _FakeCron)
    monkeypatch.setenv("JAEGER_TEST_HEADLESS", "1")
    monkeypatch.setenv("JAEGER_BACKGROUND_PRODUCERS", "1")

    first = BackgroundProducers(lay, _Sink())
    second = BackgroundProducers(lay, _Sink())
    assert first.try_start() is True
    assert second.try_start() is False
    assert started.count("cron") == 1
    first.stop()
    third = BackgroundProducers(lay, _Sink())
    assert third.try_start() is True
    third.stop()


def test_disabled_webhooks_do_not_listen(tmp_path, monkeypatch):
    lay = _layout(tmp_path)
    dump_yaml(lay.config_path, _cfg(webhooks=WebhookConfig(enabled=False)))
    monkeypatch.setenv("JAEGER_BACKGROUND_PRODUCERS", "1")
    monkeypatch.setattr(
        "jaeger_agent.background.cron_runner.CronRunner",
        lambda *a, **k: type("C", (), {"start": lambda self: None, "shutdown": lambda self, wait=True: None})(),
    )
    producers = BackgroundProducers(lay, _Sink())
    assert producers.try_start() is True
    assert producers.webhook_httpd is None
    producers.stop()


def test_partial_start_failure_stops_started_producers_and_releases_lease(tmp_path, monkeypatch):
    lay = _layout(tmp_path)
    lifecycle = []

    class _FakeCron:
        def __init__(self, *_args, **_kwargs):
            pass
        def start(self):
            lifecycle.append("start")
        def shutdown(self, wait=True):
            lifecycle.append(("stop", wait))

    monkeypatch.setenv("JAEGER_BACKGROUND_PRODUCERS", "1")
    monkeypatch.setattr("jaeger_agent.background.cron_runner.CronRunner", _FakeCron)
    producers = BackgroundProducers(lay, _Sink())
    monkeypatch.setattr(producers, "_start_webhooks", lambda _cfg: (_ for _ in ()).throw(OSError("busy")))

    with pytest.raises(OSError, match="busy"):
        producers.try_start()

    assert lifecycle == ["start", ("stop", True)]
    assert producers.held is False
    assert producers._lock_file is None

    successor = BackgroundProducers(lay, _Sink())
    monkeypatch.setattr(successor, "_start_webhooks", lambda _cfg: None)
    assert successor.try_start() is True
    successor.stop()


def test_webhook_delivery_id_replays_instead_of_a_second_turn(tmp_path, monkeypatch):
    lay = _layout(tmp_path)
    monkeypatch.setenv("JAEGER_TEST_HEADLESS", "1")
    monkeypatch.setenv("JAEGER_BACKGROUND_PRODUCERS", "1")
    monkeypatch.setattr(
        "jaeger_agent.background.cron_runner.CronRunner",
        lambda *a, **k: type("C", (), {"start": lambda self: None, "shutdown": lambda self, wait=True: None})(),
    )
    sink = _Sink()
    producers = BackgroundProducers(lay, sink)
    assert producers.try_start()
    port = producers.webhook_port
    body = json.dumps({
        "action": "turn", "prompt": "Say CONTRACT-ANSWER", "delivery_id": "wh-1",
    }).encode()
    for _ in range(2):
        req = Request(
            f"http://127.0.0.1:{port}/hook", data=body,
            headers={"Content-Type": "application/json"}, method="POST",
        )
        with urlopen(req, timeout=5) as resp:
            payload = json.loads(resp.read().decode())
        assert payload["fired"] == "turn"
        assert payload["request_id"] == "webhook:wh-1"
    assert [t["request_id"] for t in sink.turns] == ["webhook:wh-1", "webhook:wh-1"]
    producers.stop()


def test_unauthorized_webhook_is_rejected(tmp_path, monkeypatch):
    lay = _layout(tmp_path)
    dump_yaml(lay.config_path, _cfg(webhooks=WebhookConfig(enabled=True, secret="s3cret")))
    monkeypatch.setenv("JAEGER_WEBHOOK_PORT", "0")
    monkeypatch.setenv("JAEGER_BACKGROUND_PRODUCERS", "1")
    monkeypatch.setattr(
        "jaeger_agent.background.cron_runner.CronRunner",
        lambda *a, **k: type("C", (), {"start": lambda self: None, "shutdown": lambda self, wait=True: None})(),
    )
    producers = BackgroundProducers(lay, _Sink())
    assert producers.try_start()
    port = producers.webhook_port
    req = Request(
        f"http://127.0.0.1:{port}/hook",
        data=b'{"action":"turn","prompt":"no"}',
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with pytest.raises(HTTPError) as caught:
        urlopen(req, timeout=5)
    assert caught.value.code == 401
    producers.stop()


def test_duplicate_board_webhook_does_not_add_a_second_card(tmp_path, monkeypatch):
    lay = _layout(tmp_path)
    monkeypatch.setenv("JAEGER_BACKGROUND_PRODUCERS", "1")
    monkeypatch.setenv("JAEGER_WEBHOOK_PORT", "0")
    monkeypatch.setattr(
        "jaeger_agent.background.cron_runner.CronRunner",
        lambda *a, **k: type("C", (), {"start": lambda self: None, "shutdown": lambda self, wait=True: None})(),
    )
    producers = BackgroundProducers(lay, _Sink())
    assert producers.try_start()
    body = json.dumps({
        "action": "board", "title": "blocker", "prompt": "look", "delivery_id": "board-1",
    }).encode()
    cards = []
    for _ in range(2):
        req = Request(
            f"http://127.0.0.1:{producers.webhook_port}/hook", data=body,
            headers={"Content-Type": "application/json"}, method="POST",
        )
        with urlopen(req, timeout=5) as resp:
            cards.append(json.loads(resp.read().decode()))
    assert cards[0]["fired"] == "board"
    assert cards[1]["replayed"] is True
    assert cards[0]["card_id"] == cards[1]["card_id"]
    producers.stop()
    req = Request(
        f"http://127.0.0.1:{producers.webhook_port}/hook", data=body,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with pytest.raises(Exception):
        urlopen(req, timeout=2)


def test_busy_cron_restores_the_claimed_schedule(tmp_path, monkeypatch):
    from datetime import datetime, timedelta, timezone

    from jaeger_agent.memory import memory as mem
    from jaeger_agent.memory import sqlite_store

    lay = _layout(tmp_path)
    sqlite_store.bind(lay)
    when = (datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat()
    mem.add_schedule("", "do the thing", name="retry-me", at=when)
    claimed = mem.claim_due_schedules()
    assert claimed and claimed[0]["name"] == "retry-me"
    from jaeger_ai.core.runtime.background_producers import _restore_claimed_schedule
    _restore_claimed_schedule("retry-me")
    again = mem.claim_due_schedules()
    assert [row["name"] for row in again] == ["retry-me"]
    sqlite_store.close()


def test_background_conflict_does_not_replay_old_output(tmp_path):
    import asyncio

    from jaeger_ai.core.gateway.server import JaegerGatewayApp
    from jaeger_ai.core.gateway.session_store import GatewaySessionStore

    store = GatewaySessionStore(tmp_path / "gw.sqlite3")
    store.admit_request(
        "s", "original prompt", request_id="r1",
        requested={"options": {"source": "cron", "background": True}},
    )
    with store._immediate() as conn:
        conn.execute("UPDATE client_requests SET status='completed', result_json=? WHERE request_id='r1'",
                     ('{"output":"OLD"}',))
        conn.execute("UPDATE sessions SET status='idle'")
    app = JaegerGatewayApp(store=store)

    async def go():
        return await app._run_background_turn(
            "changed prompt", session_id="s", request_id="r1", source="cron",
        )

    result = asyncio.run(go())
    assert result["replayed"] is False
    assert result["halt_reason"] == "conflict"
    assert result["text"] == ""
    assert "OLD" not in result["error"]


def test_disabled_heartbeat_does_not_submit(tmp_path, monkeypatch):
    lay = _layout(tmp_path)
    dump_yaml(lay.config_path, _cfg(
        heartbeat=HeartbeatConfig(enabled=False),
        webhooks=WebhookConfig(enabled=False),
    ))
    monkeypatch.setenv("JAEGER_IDLE_READY", "1")
    monkeypatch.setenv("JAEGER_BACKGROUND_PRODUCERS", "1")
    monkeypatch.setattr(
        "jaeger_agent.background.cron_runner.CronRunner",
        lambda *a, **k: type("C", (), {"start": lambda self: None, "shutdown": lambda self, wait=True: None})(),
    )
    sink = _Sink()
    producers = BackgroundProducers(lay, sink)
    assert producers.try_start()
    producers._idle_once(load_yaml(lay.config_path, Config))
    assert sink.turns == []
    producers.stop()
