"""Phase 1B control-plane proofs against the audit-branch caller model.

These do not open the embodiment gate.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from jaeger_ai.core.embodiment.gate import EmbodimentDisabled, minecraft_action
from jaeger_ai.core.gateway import caller_auth
from jaeger_ai.core.gateway.caller_auth import CALLERS
from jaeger_ai.core.gateway.global_stop import GlobalStop, GlobalStopError, release_allowed
from jaeger_ai.core.models.ollama_bridge import (
    bridge_authorized,
    bridge_request_allowed,
    daemon_listen,
    proxy_bind_hosts,
)
from jaeger_ai.core.runtime.lifecycle_lease import LifecycleLease, repairs_allowed
from jaeger_ai.core.runtime.webui_bind import webui_bind_host
from jaeger_ai.core.tasks.completion import CompletionError, authoritative_transition
from jaeger_ai.core.tasks.models import DurableTask, TaskState


def test_webui_bind_stays_on_loopback_even_if_host_is_wildcard():
    assert webui_bind_host({"JAEGER_WEBUI_HOST": "0.0.0.0"}) == "127.0.0.1"
    assert webui_bind_host({"JAEGER_WEBUI_ALLOW_LAN": "1", "JAEGER_WEBUI_HOST": "0.0.0.0"}) == "0.0.0.0"


def test_callers_cannot_self_declare_owner():
    assert "admin" not in CALLERS["mcp"].scopes
    assert "admin" not in CALLERS["a2a"].scopes
    assert "admin" not in CALLERS["jaegerd"].scopes
    assert release_allowed(CALLERS["mcp"]) is False
    assert release_allowed(CALLERS["a2a"]) is False
    assert release_allowed(CALLERS["cli"]) is True


def test_global_stop_survives_reload_and_rejects_non_owner_release(tmp_path: Path):
    latch = GlobalStop(tmp_path / "global-stop.json")
    latch.engage("menubar", reason="operator pressed stop", unconfirmed=["helper-7"])
    reloaded = GlobalStop(tmp_path / "global-stop.json")
    assert reloaded.engaged() is True
    assert reloaded.read().unconfirmed == ("helper-7",)
    with pytest.raises(GlobalStopError):
        reloaded.release(CALLERS["mcp"])
    with pytest.raises(GlobalStopError):
        reloaded.release(CALLERS["a2a"])
    assert reloaded.release(CALLERS["cli"]).engaged is False


def test_corrupt_stop_latch_fails_engaged(tmp_path: Path):
    path = tmp_path / "global-stop.json"
    path.write_text("nope", encoding="utf-8")
    assert GlobalStop(path).engaged() is True


def test_ollama_daemon_is_loopback_and_proxy_rejects_lan():
    assert daemon_listen() == "127.0.0.1:11434"
    assert "0.0.0.0" not in proxy_bind_hosts("192.168.64.1")
    assert "0.0.0.0" not in proxy_bind_hosts("0.0.0.0")
    assert bridge_request_allowed(method="POST", path="/api/chat", peer_host="192.168.1.50") is False
    assert bridge_request_allowed(method="DELETE", path="/api/delete", peer_host="127.0.0.1") is False
    assert bridge_request_allowed(method="POST", path="/api/chat", peer_host="192.168.64.2") is True
    assert bridge_authorized("192.168.64.2", None) is False
    token = caller_auth.client_token("mcp")
    assert token
    assert bridge_authorized("192.168.64.2", f"Bearer {token}") is True
    assert bridge_authorized("192.168.64.2", "Bearer not-the-token") is False
    assert bridge_authorized("127.0.0.1", None) is True


def test_completed_verified_requires_evidence():
    task = DurableTask(task_id="t", owning_agent="jaeger", goal="make the file")
    with pytest.raises(CompletionError):
        authoritative_transition(task, TaskState.COMPLETED_VERIFIED, evidence=None)
    with pytest.raises(CompletionError):
        authoritative_transition(task, TaskState.COMPLETED_VERIFIED, evidence="success")
    with pytest.raises(CompletionError):
        authoritative_transition(task, TaskState.COMPLETED, evidence={"path": "x"})
    authoritative_transition(
        task, TaskState.COMPLETED_VERIFIED,
        evidence=[{"path": "/tmp/house.txt", "sha256": "abc"}],
    )
    assert task.state == TaskState.COMPLETED_VERIFIED
    authoritative_transition(task, TaskState.NEEDS_OWNER, evidence=None, error="ask")
    assert task.state == TaskState.NEEDS_OWNER
    authoritative_transition(task, TaskState.BLOCKED, error="waiting")
    assert task.state == TaskState.BLOCKED


def test_stale_lifecycle_lease_suspends_privileged_work(tmp_path: Path):
    lease = LifecycleLease(tmp_path / "lease.json", grace_seconds=10)
    assert lease.decide(now=100).privileged_work_allowed is True
    lease.beat("menubar", now=100)
    assert lease.decide(now=105).privileged_work_allowed is True
    assert lease.decide(now=111).reason == "lifecycle owner disappeared"
    assert lease.decide(now=111).shutdown is True
    lease.path.write_text("{", encoding="utf-8")
    assert lease.decide().privileged_work_allowed is False
    assert lease.decide().shutdown is True


def test_missed_heartbeat_suspends_before_shutdown(tmp_path: Path):
    lease = LifecycleLease(tmp_path / "lease.json", grace_seconds=15, suspend_after=5)
    lease.beat("menubar", now=100)
    missed = lease.decide(now=106)
    assert missed.privileged_work_allowed is False
    assert missed.shutdown is False
    assert lease.decide(now=116).shutdown is True


def test_workers_do_not_resurrect_jaeger_without_the_owner(tmp_path: Path, monkeypatch):
    lease = tmp_path / "lease.json"
    monkeypatch.setenv("JAEGER_LIFECYCLE_LEASE", str(lease))
    monkeypatch.setenv("JAEGER_GLOBAL_STOP_PATH", str(tmp_path / "stop.json"))
    assert repairs_allowed() is True
    LifecycleLease(lease, grace_seconds=10).beat("menubar", now=1)
    assert repairs_allowed() is False


def test_embodiment_actions_are_refused():
    with pytest.raises(EmbodimentDisabled):
        minecraft_action("build_house")
    from jaeger_agent.tools.minecraft import mc_status
    refused = mc_status()
    assert refused["ok"] is False and refused["disabled"] is True


def test_policy_kernel_reads_stop_without_the_gateway_server(tmp_path: Path):
    """The agent suite does not install aiohttp. Stop must still be readable."""
    import os
    import subprocess
    import sys
    import textwrap

    env = os.environ.copy()
    root = Path(__file__).resolve().parents[4]
    env["PYTHONPATH"] = os.pathsep.join([
        str(root),
        str(root / "packages" / "jaeger-os"),
        str(root / "packages" / "jaeger-agent"),
        str(root / "packages" / "jaeger-kokoro-tts"),
        str(root / "packages" / "jaeger-whisper-stt"),
    ])
    env["JAEGER_STATE_DIR"] = str(tmp_path)
    env["JAEGER_NO_ATTACH"] = "1"
    env.pop("JAEGER_GLOBAL_STOP_PATH", None)
    env.pop("JAEGER_LIFECYCLE_LEASE", None)
    env.pop("JAEGER_HOME", None)
    script = textwrap.dedent(
        """
        import sys
        class _Block:
            def find_spec(self, name, path, target=None):
                if name == "aiohttp" or name.startswith("aiohttp."):
                    raise ModuleNotFoundError(name)
                return None
        sys.meta_path.insert(0, _Block())
        from jaeger_ai.core.authority.kernel import PolicyKernel, ProposedAction
        decision = PolicyKernel()._check_control_plane(ProposedAction(
            tool_name="get_time", arguments={}, tier="read_only",
        ))
        assert decision is None, (
            getattr(decision, "policy_name", None),
            getattr(decision, "reason", None),
        )
        assert "jaeger_ai.core.gateway.server" not in sys.modules
        engaged = PolicyKernel()._check_control_plane(ProposedAction(
            tool_name="mc_status", arguments={}, tier="read_only",
        ))
        assert engaged.policy_name == "embodiment_gate"
        """
    )
    completed = subprocess.run(
        [sys.executable, "-c", script], env=env, capture_output=True, text=True,
    )
    assert completed.returncode == 0, completed.stderr + completed.stdout


def test_policy_kernel_denies_stop_and_minecraft(tmp_path: Path, monkeypatch):
    from jaeger_ai.core.authority.kernel import AuthorityDecisionType, PolicyKernel, ProposedAction

    stop = tmp_path / "stop.json"
    monkeypatch.setenv("JAEGER_GLOBAL_STOP_PATH", str(stop))
    monkeypatch.setenv("JAEGER_LIFECYCLE_LEASE", str(tmp_path / "lease.json"))
    denied = PolicyKernel().evaluate(ProposedAction(
        tool_name="mc_chat", arguments={"message": "hi"}, tier="read_only",
    ))
    assert denied.decision == AuthorityDecisionType.DENY
    assert denied.policy_name == "embodiment_gate"
    GlobalStop(stop).engage("menubar", reason="stop")
    stopped = PolicyKernel().evaluate(ProposedAction(
        tool_name="read_file", arguments={}, tier="read_only",
    ))
    assert stopped.decision == AuthorityDecisionType.DENY
    assert stopped.policy_name == "global_stop"


def test_live_gateway_stop_is_owner_only(tmp_path: Path, monkeypatch):
    import aiohttp.test_utils as aio_test

    from jaeger_ai.core.gateway.server import JaegerGatewayApp
    from jaeger_ai.core.gateway.session_store import GatewaySessionStore

    monkeypatch.setenv("JAEGER_GLOBAL_STOP_PATH", str(tmp_path / "stop.json"))
    monkeypatch.setenv("JAEGER_LIFECYCLE_LEASE", str(tmp_path / "missing-lease.json"))

    async def scenario():
        gateway = JaegerGatewayApp(store=GatewaySessionStore(tmp_path / "gw.sqlite3"))
        gateway.app.on_startup.clear()
        async with aio_test.TestClient(aio_test.TestServer(gateway.app)) as client:
            health = await client.get("/health")
            assert health.status != 401
            missing = await client.post("/v1/stop", json={"reason": "no"})
            assert missing.status == 401
            forged = await client.post("/v1/stop/release", headers={
                **caller_auth.client_headers("mcp"),
                "X-Jaeger-Role": "owner",
            })
            assert forged.status == 403
            engaged = await client.post("/v1/stop", json={"reason": "operator"}, headers=caller_auth.client_headers("menubar"))
            assert engaged.status == 200
            assert (await engaged.json())["engaged"] is True
            blocked = await client.post("/v1/sessions", json={"session_id": "x"}, headers=caller_auth.client_headers("cli"))
            assert blocked.status == 423
            outsider = await client.post("/v1/stop/release", headers=caller_auth.client_headers("mcp"))
            assert outsider.status == 403
            still = await client.get("/v1/stop", headers=caller_auth.client_headers("cli"))
            assert (await still.json())["engaged"] is True
            released = await client.post("/v1/stop/release", headers=caller_auth.client_headers("cli"))
            assert released.status == 200
            assert (await released.json())["engaged"] is False
            again = await client.get("/v1/sessions", headers=caller_auth.client_headers("cli"))
            assert again.status != 423
            invalid = await client.post("/v1/stop", headers={"Authorization": "Bearer not-a-jaeger-token"})
            assert invalid.status == 401
            a2a = await client.post("/v1/stop/release", headers={
                **caller_auth.client_headers("a2a"),
                "X-Jaeger-Role": "admin",
                "X-Jaeger-Actor": "owner:menubar",
            })
            assert a2a.status == 403

    asyncio.run(scenario())


def _swift_lease(path: Path, beat_at: float) -> None:
    """The exact bytes LifecycleLeaseBeat.write() emits."""
    path.write_text('{"beat_at": %.6f, "owner": "menubar"}\n' % beat_at, encoding="utf-8")


def test_menu_bar_quit_stops_the_lease_before_stack_down():
    source = Path("jaeger_ai/interfaces/swift/Sources/JaegerAI/AppDelegate.swift").read_text(encoding="utf-8")
    body = source.split("func applicationShouldTerminate(", 1)[1].split("private var shutdownStarted", 1)[0]
    assert body.index("LifecycleLeaseBeat.retire()") < body.index("StackManager.shared.down()")
    writer = Path("jaeger_ai/interfaces/swift/Sources/JaegerAI/Bridge/StackManager.swift").read_text(encoding="utf-8")
    assert r'{\"beat_at\": %.6f, \"owner\": \"menubar\"}' in writer
    assert "write(beatAt: 0)" in writer


def test_quit_retirement_lease_blocks_resurrection(tmp_path: Path, monkeypatch):
    """The bytes retire() writes are already past grace, so a relaunch cannot work."""
    from jaeger_ai.core.runtime.lifecycle_lease import LifecycleLease

    lease = tmp_path / "lifecycle-lease.json"
    monkeypatch.setenv("JAEGER_LIFECYCLE_LEASE", str(lease))
    monkeypatch.setenv("JAEGER_GLOBAL_STOP_PATH", str(tmp_path / "stop.json"))
    _swift_lease(lease, 0)
    decision = LifecycleLease.load().decide()
    assert decision.privileged_work_allowed is False
    assert decision.shutdown is True
    assert decision.reason == "lifecycle owner disappeared"
    assert repairs_allowed() is False


def test_lifecycle_shutdown_bootouts_so_launchd_cannot_resurrect(tmp_path: Path, monkeypatch):
    import jaeger_ai.core.gateway.server as gateway_server
    from jaeger_ai.core.gateway.server import JaegerGatewayApp
    from jaeger_ai.core.gateway.session_store import GatewaySessionStore

    calls: list[object] = []
    monkeypatch.setattr(
        "jaeger_ai.core.runtime.stack.stack_down",
        lambda wait_timeout=5.0: calls.append(("bootout", wait_timeout)) or {"ok": True},
    )
    monkeypatch.setenv("XPC_SERVICE_NAME", "com.jenkinsrobotics.jaeger-gateway")
    monkeypatch.setattr(gateway_server.os, "getppid", lambda: 1)

    async def scenario():
        gateway = JaegerGatewayApp(store=GatewaySessionStore(tmp_path / "gw.sqlite3"))
        gateway.app.on_startup.clear()

        async def bounded(_app):
            calls.append("bounded")

        gateway._bounded_shutdown = bounded
        await gateway_server.leave_after_lifecycle_shutdown(gateway)

    asyncio.run(scenario())
    assert calls == [("bootout", 2.0), "bounded"]


def test_webui_launcher_stays_on_loopback_unless_lan_is_explicit():
    import subprocess
    text = Path("scripts/run-jaeger-webui.sh").read_text(encoding="utf-8")
    start = text.index('if [[ "${JAEGER_WEBUI_ALLOW_LAN:-0}"')
    snippet = text[start:text.index("\nfi", start) + len("\nfi")]
    blocked = subprocess.check_output(
        ["bash", "-c", snippet + '\nprintf %s "$HERMES_WEBUI_HOST"'],
        env={"JAEGER_WEBUI_HOST": "0.0.0.0", "PATH": "/usr/bin:/bin"},
        text=True,
    )
    opened = subprocess.check_output(
        ["bash", "-c", snippet + '\nprintf %s "$HERMES_WEBUI_HOST"'],
        env={"JAEGER_WEBUI_HOST": "0.0.0.0", "JAEGER_WEBUI_ALLOW_LAN": "1", "PATH": "/usr/bin:/bin"},
        text=True,
    )
    assert blocked == "127.0.0.1"
    assert opened == "0.0.0.0"


def test_webui_launcher_never_touches_legacy_hermes_homes():
    text = Path("scripts/run-jaeger-webui.sh").read_text(encoding="utf-8")
    for legacy in ("hermes-webui-agent", "~/.hermes", "$HOME/.hermes", "${HOME}/.hermes",
                   "prepare_webui_home", "link_shared_profiles", "JAEGER_HERMES_AGENT_SRC"):
        assert legacy not in text, legacy
    assert "/webui-agent}" in text


def test_ollama_bridge_refuses_unrestricted_paths():
    import threading
    from http.server import ThreadingHTTPServer
    from urllib.error import HTTPError
    from urllib.request import Request, urlopen

    from jaeger_ai.core.models import ollama_bridge as bridge

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), bridge._Handler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        request = Request(f"http://127.0.0.1:{port}/api/delete", data=b"{}", method="POST")
        try:
            urlopen(request, timeout=2)
            raise AssertionError("unrestricted model path was forwarded")
        except HTTPError as exc:
            assert exc.code == 403
        deleted = Request(f"http://127.0.0.1:{port}/api/delete", method="DELETE")
        try:
            urlopen(deleted, timeout=2)
            raise AssertionError("DELETE was not refused")
        except HTTPError as exc:
            assert exc.code == 403
        assert "0.0.0.0" not in bridge.proxy_bind_hosts("192.168.64.1")
        assert bridge.daemon_listen() == "127.0.0.1:11434"
    finally:
        httpd.shutdown()


def test_stale_lease_suspends_and_expired_lease_shuts_the_gateway_down(tmp_path: Path, monkeypatch):
    import time
    import aiohttp.test_utils as aio_test

    from jaeger_ai.core.gateway.server import JaegerGatewayApp
    from jaeger_ai.core.gateway.session_store import GatewaySessionStore
    from jaeger_ai.core.runtime.fabric_supervisor import _repair_jaeger

    lease = tmp_path / "lease.json"
    monkeypatch.setenv("JAEGER_LIFECYCLE_LEASE", str(lease))
    monkeypatch.setenv("JAEGER_GLOBAL_STOP_PATH", str(tmp_path / "stop.json"))

    async def scenario():
        gateway = JaegerGatewayApp(store=GatewaySessionStore(tmp_path / "gw.sqlite3"))
        gateway.app.on_startup.clear()
        async with aio_test.TestClient(aio_test.TestServer(gateway.app)) as client:
            _swift_lease(lease, time.time())
            gateway._lifecycle_shutdown.clear()
            gateway._note_lifecycle()
            assert gateway._lifecycle_shutdown.is_set() is False
            alive = await client.post(
                "/v1/sessions", json={"session_id": "alive"}, headers=caller_auth.client_headers("cli"),
            )
            assert alive.status not in {401, 423}

            _swift_lease(lease, time.time() - 8)
            gateway._note_lifecycle()
            assert gateway._lifecycle_shutdown.is_set() is False
            stale = await client.post(
                "/v1/sessions", json={"session_id": "stale"}, headers=caller_auth.client_headers("cli"),
            )
            assert stale.status == 423

            _swift_lease(lease, time.time() - 30)
            gateway._note_lifecycle()
            assert gateway._lifecycle_shutdown.is_set() is True
            expired = await client.post(
                "/v1/sessions", json={"session_id": "expired"}, headers=caller_auth.client_headers("cli"),
            )
            assert expired.status == 423

    asyncio.run(scenario())
    assert repairs_allowed() is False
    kicked = []
    monkeypatch.setattr(
        "jaeger_ai.core.runtime.fabric_supervisor._kickstart",
        lambda label: kicked.append(label) or True,
    )
    assert _repair_jaeger() is False
    assert kicked == []


def test_attached_slash_is_a_command_not_a_model_turn(monkeypatch):
    import io

    from jaeger_ai.interfaces import bridge

    calls = []

    def boom(*_args, **_kwargs):
        calls.append("model")
        raise AssertionError("slash command entered the model loop")

    monkeypatch.setattr(bridge, "_run_slash", lambda text, ctx: f"ran {text}")
    monkeypatch.setattr(bridge, "_windowed_control_slash", lambda text: None)
    monkeypatch.setattr(bridge, "_goal_turn_text", lambda text: None)
    out = io.StringIO()

    class Ctx:
        session_pending: dict = {}
        busy = False
        outputs: set = set()

    bridge._execute_attached_turn(out, Ctx(), {"text": "/help", "session": "desktop-app", "id": "s1"})
    assert calls == []
    assert "ran /help" in out.getvalue()
    assert "noqa: F821" not in Path("jaeger_ai/interfaces/bridge.py").read_text(encoding="utf-8")


def test_state_dir_isolates_webui_profile_writes(tmp_path: Path, monkeypatch):
    live = tmp_path / "live-home"
    state = tmp_path / "state"
    monkeypatch.setattr(Path, "home", lambda: live)
    monkeypatch.setenv("JAEGER_STATE_DIR", str(state))
    monkeypatch.delenv("HERMES_HOME", raising=False)
    monkeypatch.delenv("JAEGER_WEBUI_AGENT_STATE", raising=False)
    monkeypatch.delenv("JAEGER_HOME", raising=False)

    from jaeger_ai.core.runtime.profile_paths import webui_agent_home
    from jaeger_ai.features.webui.service.profile_layout import ensure_agent_state_schema

    agent = webui_agent_home()
    assert agent.name == "webui-agent"
    result = ensure_agent_state_schema(agent)
    assert Path(result["path"]).resolve().is_relative_to(state.resolve())
    assert not (live / ".jaeger").exists()
    assert not (live / ".hermes").exists()



def test_corrupt_stop_latch_stays_engaged_on_the_live_gateway(tmp_path: Path, monkeypatch):
    import aiohttp.test_utils as aio_test

    from jaeger_ai.core.gateway.server import JaegerGatewayApp
    from jaeger_ai.core.gateway.session_store import GatewaySessionStore

    latch = tmp_path / "stop.json"
    latch.write_text("{", encoding="utf-8")
    monkeypatch.setenv("JAEGER_GLOBAL_STOP_PATH", str(latch))
    monkeypatch.setenv("JAEGER_LIFECYCLE_LEASE", str(tmp_path / "missing-lease.json"))

    async def scenario():
        gateway = JaegerGatewayApp(store=GatewaySessionStore(tmp_path / "gw.sqlite3"))
        gateway.app.on_startup.clear()
        async with aio_test.TestClient(aio_test.TestServer(gateway.app)) as client:
            status = await client.get("/v1/stop", headers=caller_auth.client_headers("cli"))
            assert status.status == 200
            assert (await status.json())["engaged"] is True
            blocked = await client.post(
                "/v1/sessions", json={"session_id": "x"}, headers=caller_auth.client_headers("cli"),
            )
            assert blocked.status == 423
            released = await client.post("/v1/stop/release", headers=caller_auth.client_headers("cli"))
            assert released.status == 200
            assert (await released.json())["engaged"] is False

    asyncio.run(scenario())


@pytest.mark.parametrize("xpc,ppid", [
    (None, 1),                                         # shell/foreground gateway
    ("com.jenkinsrobotics.jaeger-gateway", 4242),      # inherited label, not launchd's child
    ("application.com.apple.Terminal.123", 1),         # some other launchd job
])
def test_scratch_gateway_lease_shutdown_never_boots_out_the_stack(tmp_path: Path, monkeypatch, xpc, ppid):
    import jaeger_ai.core.gateway.server as gateway_server
    from jaeger_ai.core.gateway.server import JaegerGatewayApp
    from jaeger_ai.core.gateway.session_store import GatewaySessionStore

    calls: list[object] = []
    monkeypatch.setattr(
        "jaeger_ai.core.runtime.stack.stack_down",
        lambda wait_timeout=5.0: calls.append("bootout") or {"ok": True},
    )
    if xpc is None:
        monkeypatch.delenv("XPC_SERVICE_NAME", raising=False)
    else:
        monkeypatch.setenv("XPC_SERVICE_NAME", xpc)
    monkeypatch.setattr(gateway_server.os, "getppid", lambda: ppid)

    async def scenario():
        gateway = JaegerGatewayApp(store=GatewaySessionStore(tmp_path / "gw.sqlite3"))
        gateway.app.on_startup.clear()

        async def bounded(_app):
            calls.append("bounded")

        gateway._bounded_shutdown = bounded
        await gateway_server.leave_after_lifecycle_shutdown(gateway)

    asyncio.run(scenario())
    assert calls == ["bounded"]


def test_owner_changes_task_state_only_through_the_completion_step():
    import ast
    source = Path("jaeger_ai/core/tasks/owner.py").read_text(encoding="utf-8")
    direct = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(isinstance(t, ast.Attribute) and t.attr == "state" for t in targets):
                direct.append(node.lineno)
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "setattr" and len(node.args) > 1
                and isinstance(node.args[1], ast.Constant) and node.args[1].value == "state"):
            direct.append(node.lineno)
    assert direct == [], f"owner.py writes task.state directly at lines {direct}"


def test_plain_state_moves_keep_recorded_verification():
    task = DurableTask(task_id="t", owning_agent="jaeger", goal="g")
    task.payload = {"verification": [{"path": "/tmp/a", "sha256": "abc"}]}
    task.error = "earlier"
    authoritative_transition(task, TaskState.PAUSED)
    assert task.payload["verification"] == [{"path": "/tmp/a", "sha256": "abc"}]
    assert task.error == "earlier"
    authoritative_transition(task, TaskState.QUEUED, error=None)
    assert task.error is None
    with pytest.raises(CompletionError):
        authoritative_transition(task, TaskState.COMPLETED_VERIFIED)  # no evidence given
    assert task.state == TaskState.QUEUED
