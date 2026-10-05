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

    asyncio.run(scenario())
