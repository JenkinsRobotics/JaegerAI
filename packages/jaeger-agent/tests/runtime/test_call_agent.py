"""call_agent must wait for a specialist result, not treat registration as success."""
from jaeger_agent.tools.call_agent import call_agent
import importlib
mod = importlib.import_module("jaeger_agent.tools.call_agent")


def _isolate(monkeypatch, tmp_path):
    monkeypatch.setenv("JAEGER_STATE_DIR", str(tmp_path / "state"))


def test_native_call_submits_once_without_waiting_on_child(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    import sys
    from types import SimpleNamespace
    monkeypatch.setitem(sys.modules, "jaeger_ai.main", SimpleNamespace(_pipeline={"client": object()}))
    calls = []
    def submit(method, path, *args, **kwargs):
        calls.append(method)
        assert method == "POST", "Must not poll while holding the native turn"
        return 200, {"id": "handoff_test", "status": "admitted"}
    monkeypatch.setattr(mod, "_request_json", submit)
    result = call_agent("native:everyday", "bounded work", require_approval=False)
    assert result["status"] == "admitted"
    assert result["completed"] is False
    assert calls == ["POST"]


def test_call_agent_reports_failure_when_specialist_fails(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    monkeypatch.setattr(mod, "_request_json", lambda *a, **k: (200, {
        "id": "handoff_1",
        "status": "failed",
        "result": {"ok": False, "summary": "specialist offline"},
        "child_run_id": "child",
    }))
    out = call_agent("native:everyday", "do a thing", require_approval=False)
    assert out["ok"] is False
    assert out["status"] == "failed"
    assert "offline" in out["error"]


def test_call_agent_does_not_treat_pending_approval_as_done(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    monkeypatch.setattr(mod, "_request_json", lambda *a, **k: (202, {
        "id": "handoff_2",
        "status": "pending_approval",
        "approval_id": "approval_1",
    }))
    out = call_agent("native:surfaces", "align chrome")
    assert out["ok"] is False
    assert out["status"] == "pending_approval"


def test_call_agent_ok_only_after_completed_child_result(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    monkeypatch.setattr(mod, "_request_json", lambda *a, **k: (200, {
        "id": "handoff_3",
        "status": "completed",
        "child_run_id": "run1",
        "result": {"ok": True, "summary": "done", "evidence": [{"backend": "mcp"}]},
    }))
    out = call_agent("native:gateway", "check health", require_approval=False, request_id="aa" * 16)
    assert out["ok"] is True
    assert out["child_run_id"] == "run1"
    assert out["result"]["summary"] == "done"
