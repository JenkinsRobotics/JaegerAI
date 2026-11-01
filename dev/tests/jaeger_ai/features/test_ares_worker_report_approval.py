"""ARES's headless Codex runs may post results without an owner card; nothing else is pre-approved."""
from jaeger_ai.features.agent_bridge import ares_worker
from jaeger_ai.features.agent_bridge.service import AgentMessages, BridgeError
from jaeger_ai.core.gateway.session_store import GatewaySessionStore
import pytest


def test_only_report_tools_are_preapproved(monkeypatch, tmp_path):
    seen = {}

    def fake_run(cmd, **kw):
        seen["cmd"] = cmd
        class P: returncode = 0
        return P()

    monkeypatch.setattr(ares_worker, "WORKSPACE", tmp_path)
    monkeypatch.setattr(ares_worker, "_token", lambda: "fixture-ares-credential")
    monkeypatch.setattr(ares_worker.subprocess, "run", fake_run)
    ares_worker.run_job({"id": "t1", "from": "grokbot", "thread": "th", "body": "x"})
    cmd = seen["cmd"]
    overrides = [cmd[i + 1] for i, a in enumerate(cmd) if a == "-c"]
    for server in ares_worker.HUB_MCP:
        assert f'mcp_servers.{server}.url="{ares_worker.HUB_URL}"' in overrides
        assert f'mcp_servers.{server}.bearer_token_env_var="ARES_HUB_TOKEN"' in overrides
        assert f'mcp_servers.{server}.tools.post_result.approval_mode="approve"' in overrides
    assert not any("default_tools_approval_mode" in a for a in cmd)
    for gated in ("send_message", "handoff_task", "start_goal", "jaeger.app_action", "jaeger.backlog_update"):
        assert not any(f".tools.{gated}." in a for a in cmd)
    assert cmd[-1].startswith("") and "--dangerously-bypass-approvals-and-sandbox" not in cmd


def test_codex_hub_identity_matches_worker_thread(monkeypatch, tmp_path):
    bridge = AgentMessages(GatewaySessionStore(tmp_path / "hub.sqlite3"))
    task = {"id": "handoff-1", "thread": "thread-1", "to": "ares", "kind": "task",
            "title": "Work", "body": "Work"}
    bridge.send("grokbot", task)
    result = {"id": "result-1", "thread": "thread-1", "to": "grokbot",
              "kind": "result", "title": "Result", "body": "Done", "reply_to": "handoff-1"}
    with pytest.raises(BridgeError, match="Thread unavailable") as error:
        bridge.send("mcp", result)
    assert error.value.status == 404
    assert bridge.send("ares", result)["from"] == "ares"

    seen = {}
    def fake_run(cmd, **kw):
        seen.update(cmd=cmd, env=kw["env"])
        class P: returncode = 0
        return P()
    monkeypatch.setattr(ares_worker, "WORKSPACE", tmp_path)
    monkeypatch.setattr(ares_worker, "_token", lambda: "fixture-ares-credential")
    monkeypatch.setattr(ares_worker.subprocess, "run", fake_run)
    ares_worker.run_job({"id": "handoff-1", "from": "grokbot", "thread": "thread-1", "body": "Work"})
    overrides = [seen["cmd"][i + 1] for i, arg in enumerate(seen["cmd"]) if arg == "-c"]
    for server in ares_worker.HUB_MCP:
        assert f'mcp_servers.{server}.bearer_token_env_var="ARES_HUB_TOKEN"' in overrides
    assert seen["env"]["ARES_HUB_TOKEN"] == "fixture-ares-credential"
    assert all("fixture-ares-credential" not in arg for arg in seen["cmd"])
