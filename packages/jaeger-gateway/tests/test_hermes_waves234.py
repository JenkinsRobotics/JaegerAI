"""Waves 2–4 Hermes-Superset integration tests:
- Wave 2: 5-field cron expressions, schedule management tools, MEMORY.md/USER.md sync, cognitive heartbeat.
- Wave 3: Interactive PTY sessions, allowlisted SSH backend & routes, auto-managed browser manager.
- Wave 4: Telegram/Discord/Slack adapters, TelegramPoller ingress, channel_send fail-closed gating.
"""

from __future__ import annotations

import http.server
import json
import socketserver
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from aiohttp.test_utils import TestClient, TestServer

from jaeger_channels import (
    ChannelConfigError,
    ChannelIngressSupervisor,
    DiscordChannelPoller,
    SlackChannelPoller,
    TelegramPoller,
    build_discord_adapter,
    build_slack_adapter,
    build_telegram_adapter,
)
from jaeger_gateway.runtime import ModularGatewayRuntime
from jaeger_gateway.store import MAIN_CHAT_SESSION_ID
from jaeger_gateway.supervised_browser import GrantDenied, SupervisedBrowser
from jaeger_loop import LearningNudgeTracker
from jaeger_memory import import_memory_markdown, sync_memory_markdown
from jaeger_orchestration import CronExpressionError, next_cron_time, parse_cron
from jaeger_tools import RemoteExecError, RemoteHostConfig, RemoteHostRegistry, SSHBackend
from jaeger_tools.web_search import _parse_ddg_html


def test_wave2_cron_expression_engine() -> None:
    sched = parse_cron("*/15 9-17 * * MON-FRI")
    assert 0 in sched.minutes and 45 in sched.minutes and 10 not in sched.minutes
    assert 9 in sched.hours and 17 in sched.hours and 18 not in sched.hours
    assert sched.days_of_week == frozenset({1, 2, 3, 4, 5})

    # 2025-01-03 17:50 UTC is a Friday -> next fire should be Monday 2025-01-06 09:00 UTC.
    base = datetime(2025, 1, 3, 17, 50, tzinfo=timezone.utc).timestamp()
    nxt = datetime.fromtimestamp(next_cron_time("*/15 9-17 * * MON-FRI", after=base, utc=True), tz=timezone.utc)
    assert (nxt.year, nxt.month, nxt.day, nxt.hour, nxt.minute) == (2025, 1, 6, 9, 0)

    # Aliases work
    daily = parse_cron("@daily")
    assert daily.minutes == frozenset({0}) and daily.hours == frozenset({0})

    # Invalid expressions fail closed
    for bad in ("", "* * *", "60 * * * *", "*/0 * * * *", "0 0 31 2 *"):
        with pytest.raises(CronExpressionError):
            next_cron_time(bad, after=base, utc=True)


@pytest.mark.asyncio
async def test_wave2_cron_schedule_lifecycle_and_http_routes(tmp_path: Path) -> None:
    runtime = ModularGatewayRuntime(state_dir=tmp_path / "state", workspace=tmp_path / "ws")
    try:
        runtime.store.main_chat_session()
        app = runtime.build_app(serve_ui=False)
        async with TestClient(TestServer(app)) as client:
            # Create cron job directly via owner-local API (no explicit due_at needed!)
            r_create = await client.post(
                f"/v1/sessions/{MAIN_CHAT_SESSION_ID}/jobs",
                json={"prompt": "Daily digest", "cron_expr": "0 8 * * *"},
            )
            assert r_create.status == 201
            job = (await r_create.json())["job"]
            assert job["cron_expr"] == "0 8 * * *"
            assert job["series_id"] is not None
            assert job["due_at"] > time.time()

            # List via GET /v1/sessions/{sid}/jobs
            r_list = await client.get(f"/v1/sessions/{MAIN_CHAT_SESSION_ID}/jobs")
            assert r_list.status == 200
            data_l = await r_list.json()
            assert data_l["count"] == 1 and data_l["jobs"][0]["job_id"] == job["job_id"]

            # Agent list_scheduled_jobs & manage_scheduled_job tools
            tl = runtime.tools.execute("list_scheduled_jobs", {})
            assert tl.ok and json.loads(tl.output)["count"] == 1
            tp = runtime.tools.execute("manage_scheduled_job", {"action": "pause_series", "series_id": job["series_id"]})
            assert tp.ok and json.loads(tp.output)["status"] == "paused"
            tr = runtime.tools.execute("manage_scheduled_job", {"action": "resume_series", "series_id": job["series_id"]})
            assert tr.ok and json.loads(tr.output)["status"] == "active"
            tc = runtime.tools.execute("manage_scheduled_job", {"action": "cancel_series", "series_id": job["series_id"]})
            assert tc.ok and json.loads(tc.output)["status"] == "cancelled"

        # CognitiveLifeLoop heartbeat runs cleanly without preempting owner work
        st = await runtime.cognition.step_once(trigger="test_tick")
        assert st.tick_count >= 1
        snap = runtime.world.snapshot()
        assert "scheduler_heartbeat" in snap.get("domains", {}).get("system", {})
    finally:
        runtime.close()


def test_wave2_memory_markdown_bidirectional_sync_and_forget(tmp_path: Path) -> None:
    runtime = ModularGatewayRuntime(state_dir=tmp_path / "state", workspace=tmp_path / "ws")
    try:
        runtime.memory.remember("editor", "neovim", subject="user", category="prefs")
        res_sync = runtime.tools.execute("memory_sync_markdown", {})
        assert res_sync.ok, res_sync.error
        mem_path = runtime.state_dir / "MEMORY.md"
        user_path = runtime.state_dir / "USER.md"
        assert mem_path.is_file() and user_path.is_file()
        assert "neovim" in mem_path.read_text(encoding="utf-8")

        # Manual edit in MEMORY.md imports cleanly back into SQLite
        mem_path.write_text(
            mem_path.read_text(encoding="utf-8") + "\n## infra\n- **rack_pc**: ubuntu-24.04\n",
            encoding="utf-8",
        )
        imp = import_memory_markdown(runtime.memory, mem_path)
        assert imp["imported"] == 1
        assert runtime.memory.recall("rack_pc", subject="infra") == "ubuntu-24.04"

        # memory_forget deletes from SQLite and refreshes MEMORY.md
        fg = runtime.tools.execute("memory_forget", {"key": "editor", "subject": "user"})
        assert fg.ok
        assert runtime.memory.recall("editor", subject="user") is None
        assert "neovim" not in mem_path.read_text(encoding="utf-8")
        assert "ubuntu-24.04" in mem_path.read_text(encoding="utf-8")
    finally:
        runtime.close()


def test_wave3_interactive_pty_tools(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "interactive.py").write_text(
        "a = input('First: ').strip()\n"
        "b = input('Second: ').strip()\n"
        "open('result.txt', 'w').write(f'{a}+{b}')\n"
        "print(f'RESULT={a}+{b}')\n",
        encoding="utf-8",
    )
    runtime = ModularGatewayRuntime(state_dir=tmp_path / "state", workspace=ws)
    try:
        r0 = runtime.tools.execute("pty_start", {"command": "python3 -u interactive.py", "initial_wait_s": 0.35})
        assert r0.ok, r0.error
        pid = json.loads(r0.output)["pty_id"]
        r1 = runtime.tools.execute("pty_send", {"pty_id": pid, "data": "alpha", "wait_s": 0.25})
        assert r1.ok, r1.error
        r2 = runtime.tools.execute("pty_send", {"pty_id": pid, "data": "beta", "wait_s": 0.35})
        assert r2.ok, r2.error
        r3 = runtime.tools.execute("pty_read", {"pty_id": pid, "wait_s": 0.1})
        assert r3.ok, r3.error
        r4 = runtime.tools.execute("pty_stop", {"pty_id": pid})
        assert r4.ok, r4.error
        assert (ws / "result.txt").read_text(encoding="utf-8") == "alpha+beta"
    finally:
        runtime.close()


@pytest.mark.asyncio
async def test_wave3_remote_ssh_allowlist_and_routes(tmp_path: Path) -> None:
    runtime = ModularGatewayRuntime(state_dir=tmp_path / "state", workspace=tmp_path / "ws")
    try:
        # Unlisted host must fail closed
        denied = runtime.tools.execute("remote_exec", {"host": "rack-pc", "command": "uptime"})
        assert not denied.ok
        assert "allowlist" in (denied.error or "").lower()

        app = runtime.build_app(serve_ui=False)
        async with TestClient(TestServer(app)) as client:
            r_put = await client.put(
                "/v1/remote/hosts/rack-pc",
                json={"hostname": "10.0.0.42", "user": "ops", "port": 2222, "allowed_prefixes": ["uptime", "df "]},
            )
            assert r_put.status == 200
            r_get = await client.get("/v1/remote/hosts")
            assert r_get.status == 200
            hosts = (await r_get.json())["hosts"]
            assert len(hosts) == 1 and hosts[0]["alias"] == "rack-pc" and hosts[0]["port"] == 2222

            # Disallowed command prefix fails closed
            cfg = runtime.remote_hosts.load()["rack-pc"]
            assert "BatchMode=yes" in runtime.ssh_backend.build_argv(cfg, "uptime")
            with pytest.raises(RemoteExecError):
                runtime.ssh_backend.build_argv(cfg, "reboot")

            # E-Stop blocks remote_exec
            runtime.governor.trigger_estop("test")
            r_estop = runtime.tools.execute("remote_exec", {"host": "rack-pc", "command": "uptime"})
            assert not r_estop.ok
            runtime.governor.release_estop()

            r_del = await client.delete("/v1/remote/hosts/rack-pc")
            assert r_del.status == 200
            assert runtime.remote_hosts.list_public() == []
    finally:
        runtime.close()


@pytest.mark.asyncio
async def test_wave4_multi_channel_adapters_poller_and_gating(tmp_path: Path) -> None:
    received: list[tuple[str, dict[str, Any]]] = []

    class _FakeChannelServer(http.server.BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            n = int(self.headers.get("Content-Length") or "0")
            body = json.loads(self.rfile.read(n).decode("utf-8") or "{}")
            received.append((self.path, body))
            if self.path.endswith("/getUpdates"):
                payload = {
                    "ok": True,
                    "result": [
                        {
                            "update_id": 101,
                            "message": {
                                "message_id": 55,
                                "chat": {"id": 99999},
                                "from": {"username": "owner_user"},
                                "text": "Hey Jaeger, status check",
                            },
                        },
                        {
                            "update_id": 102,
                            "message": {
                                "message_id": 56,
                                "chat": {"id": 11111},
                                "from": {"username": "stranger"},
                                "text": "Unauthorized message",
                            },
                        },
                    ],
                }
            else:
                payload = {"ok": True, "result": {"message_id": 777}, "id": "dc_888"}
            raw = json.dumps(payload).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
            return

    httpd = socketserver.TCPServer(("127.0.0.1", 0), _FakeChannelServer)
    port = httpd.server_address[1]
    base = f"http://127.0.0.1:{port}"
    th = threading.Thread(target=httpd.serve_forever, daemon=True)
    th.start()
    runtime = ModularGatewayRuntime(state_dir=tmp_path / "state", workspace=tmp_path / "ws")
    try:
        # 1. Outbound Telegram, Discord, Slack adapters deliver cleanly & validate config
        tg_token = "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdef"
        tg = build_telegram_adapter(tg_token, api_base=base)
        assert tg("99999", "Hello Telegram")["delivered"] is True

        dc = build_discord_adapter(f"{base}/discord/hook", mode="webhook")
        assert dc("owner", "Hello Discord")["delivered"] is True

        sl = build_slack_adapter(f"{base}/slack/hook", mode="webhook")
        assert sl("general", "Hello Slack")["delivered"] is True

        with pytest.raises(ChannelConfigError):
            build_telegram_adapter("not-a-valid-token")

        # 2. Agent channel_send tool is ALWAYS fail-closed (queued_for_approval + secret redacted)
        runtime.channels.register_adapter("discord", dc)
        cs = runtime.tools.execute(
            "channel_send",
            {"channel": "discord", "recipient": "owner", "body": "Leaked sk-live-1234567890abcdef123456"},
        )
        assert cs.ok, cs.error
        msg = json.loads(cs.output)
        assert msg["status"] == "queued_for_approval"
        assert "1234567890abcdef" not in msg["body"]

        # 3. TelegramPoller ingests allowlisted chat only and drops strangers
        ingested: list[tuple[str, str, str, str, str]] = []

        async def _on_in(ch: str, tid: str, mid: str, sender: str, text: str, _auto: bool) -> None:
            ingested.append((ch, tid, mid, sender, text))
            await runtime._handle_channel_inbound(ch, tid, mid, sender, text, False)  # noqa: SLF001

        poller = TelegramPoller(tg_token, on_message=_on_in, allowed_chat_ids={"99999"}, api_base=base)
        count = await poller.poll_once(timeout_s=0)
        assert count == 1
        assert len(ingested) == 1
        assert ingested[0][1] == "99999" and "status check" in ingested[0][4]

        # 4. ChannelIngressSupervisor lifecycle starts/stops cleanly
        sup = ChannelIngressSupervisor()
        assert sup.status() == {"pollers": {}}
        await sup.stop()
    finally:
        runtime.close()
        httpd.shutdown()
        httpd.server_close()


@pytest.mark.asyncio
async def test_wave5_web_search_execute_code_interactive_browser_pollers_and_nudges(tmp_path: Path) -> None:
    # 1. DuckDuckGo HTML parser & execute_code tool
    sample_html = (
        '<a class="result__a" href="https://duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fdocs">Example Docs</a>'
        '<a class="result__snippet">Fast modular guide.</a>'
    )
    parsed = _parse_ddg_html(sample_html, 5)
    assert len(parsed) == 1 and parsed[0]["url"] == "https://example.com/docs" and "modular" in parsed[0]["snippet"]

    runtime = ModularGatewayRuntime(state_dir=tmp_path / "state", workspace=tmp_path / "ws")
    try:
        ex = runtime.tools.execute("execute_code", {"code": "print(sum(range(1, 11)))"})
        assert ex.ok, ex.error
        assert ex.output.strip() == "55"

        # 2. Interactive browser actions fail closed on read-only grant, succeed on interactive=True grant
        class _InteractiveDouble:
            def __init__(self) -> None:
                self.clicks = 0
                self.typed = ""

            def action(self, body: dict[str, Any]) -> dict[str, Any]:
                act = body["action"]
                if act == "supervised-capabilities":
                    return {"supervised_origin_guard": 1}
                if act == "new-tab":
                    return {"active": "t1", "pages": [{"id": "t1", "url": "about:blank", "title": ""}]}
                if act == "navigate":
                    return {"active": "t1", "pages": [{"id": "t1", "url": body["url"], "title": "Form"}]}
                if act == "click":
                    self.clicks += 1
                    return {"active": "t1", "pages": [{"id": "t1", "url": "https://example.com/form", "title": "Form"}]}
                if act == "type":
                    self.typed = body["text"]
                    return {"active": "t1", "pages": [{"id": "t1", "url": "https://example.com/form", "title": "Form"}]}
                if act == "screenshot":
                    return {"url": "https://example.com/form", "mime": "image/png", "bytes": 4, "png_base64": "AAAA"}
                if act == "snapshot":
                    return {"url": "https://example.com/form", "title": "Form", "text": f"typed={self.typed}", "headings": []}
                return {"closed": "t1"}

        dbl = _InteractiveDouble()
        sb = SupervisedBrowser(dbl)
        sb.grant("ro_sess", "https://example.com/form", interactive=False)
        sb.execute("ro_sess", "open")
        shot = sb.execute("ro_sess", "screenshot")
        assert shot["ok"] is True and shot["bytes"] == 4
        with pytest.raises(GrantDenied):
            sb.execute("ro_sess", "click", selector="#go")

        sb.grant("rw_sess", "https://example.com/form", interactive=True)
        sb.execute("rw_sess", "open")
        sb.execute("rw_sess", "type", selector="#q", text="jaeger")
        snap = sb.execute("rw_sess", "click", selector="#go")
        assert dbl.clicks == 1 and dbl.typed == "jaeger" and "typed=jaeger" in snap["text"]

        # 3. LearningNudgeTracker triggers skill nudge after heavy tool turn & memory nudge periodically
        nudge = LearningNudgeTracker(enabled=True, tool_threshold=3, turn_interval=2)
        nudge.record_turn("s1", tool_calls=4, verdict="complete")
        h1 = nudge.consume_hint("s1")
        assert "save_workspace_skill" in h1
        assert nudge.consume_hint("s1") == ""
        nudge.record_turn("s1", tool_calls=0, verdict="complete")
        h2 = nudge.consume_hint("s1")
        assert "memory_remember" in h2

        # 4. Discord & Slack inbound pollers against local loopback HTTP mock
        class _InboundMock(http.server.BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                if "/channels/123456/messages" in self.path:
                    payload: Any = [
                        {"id": "20", "content": "bot echo", "author": {"id": "999", "username": "bot", "bot": True}},
                        {"id": "21", "content": "hello discord", "author": {"id": "777", "username": "owner", "bot": False}},
                    ]
                elif "/conversations.history" in self.path:
                    payload = {
                        "ok": True,
                        "messages": [
                            {"ts": "1700.1", "user": "U1", "text": "hello slack"},
                            {"ts": "1700.2", "bot_id": "B1", "text": "ignore bot"},
                        ],
                    }
                else:
                    payload = {}
                raw = json.dumps(payload).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
                return

        srv = socketserver.TCPServer(("127.0.0.1", 0), _InboundMock)
        p = srv.server_address[1]
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            seen: list[tuple[str, str, str]] = []

            async def _cb(ch: str, tid: str, _mid: str, _sender: str, text: str, _auto: bool) -> None:
                seen.append((ch, tid, text))

            d_poll = DiscordChannelPoller("bot-token-123456", ["123456"], on_message=_cb, allowed_user_ids={"777"}, api_base=f"http://127.0.0.1:{p}")
            s_poll = SlackChannelPoller("xoxb-token-123456", ["C123"], on_message=_cb, allowed_user_ids={"U1"}, api_base=f"http://127.0.0.1:{p}")
            assert await d_poll.poll_once() == 1
            assert await s_poll.poll_once() == 1
            assert ("discord", "123456", "hello discord") in seen
            assert ("slack", "C123", "hello slack") in seen
        finally:
            srv.shutdown()
            srv.server_close()
    finally:
        runtime.close()


@pytest.mark.asyncio
async def test_autonomous_initiative_engine_routes_and_journal(tmp_path: Path) -> None:
    runtime = ModularGatewayRuntime(state_dir=tmp_path / "state", workspace=tmp_path / "ws")
    try:
        app = runtime.build_app(serve_ui=False)
        async with TestClient(TestServer(app)) as client:
            r0 = await client.get("/v1/cognition/actions")
            assert r0.status == 200
            data0 = await r0.json()
            assert data0["status"]["config"]["enabled"] is True

            # Trigger an immediate safe autonomous step (maintenance sync when no active goals / MC offline)
            r1 = await client.post("/v1/cognition/autonomy", json={"trigger_now": True, "cooldown_s": 600})
            assert r1.status == 200
            body1 = await r1.json()
            assert body1["triggered"]["acted"] is True
            assert body1["status"]["config"]["cooldown_s"] == 600.0
            assert len(body1["status"]["recent_actions"]) >= 1

            # Pause autonomy cleanly
            r2 = await client.post("/v1/cognition/autonomy", json={"enabled": False})
            assert r2.status == 200
            assert (await r2.json())["status"]["config"]["enabled"] is False
    finally:
        runtime.close()
