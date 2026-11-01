"""ARES's headless Codex runs may post results without an owner card; nothing else is pre-approved."""
from jaeger_ai.features.agent_bridge import ares_worker


def test_only_report_tools_are_preapproved(monkeypatch, tmp_path):
    seen = {}

    def fake_run(cmd, **kw):
        seen["cmd"] = cmd
        class P: returncode = 0
        return P()

    monkeypatch.setattr(ares_worker, "WORKSPACE", tmp_path)
    monkeypatch.setattr(ares_worker.subprocess, "run", fake_run)
    ares_worker.run_job({"id": "t1", "from": "grokbot", "thread": "th", "body": "x"})
    cmd = seen["cmd"]
    overrides = [cmd[i + 1] for i, a in enumerate(cmd) if a == "-c"]
    assert overrides == ['mcp_servers.jaeger-ares.tools.post_result.approval_mode="approve"']
    assert not any("default_tools_approval_mode" in a for a in cmd)
    for gated in ("send_message", "handoff_task", "start_goal", "jaeger.app_action", "jaeger.backlog_update"):
        assert not any(f".tools.{gated}." in a for a in cmd)
    assert cmd[-1].startswith("") and "--dangerously-bypass-approvals-and-sandbox" not in cmd
