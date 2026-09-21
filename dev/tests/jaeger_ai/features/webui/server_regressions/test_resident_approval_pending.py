"""Stock /api/approval/pending and respond see runner-local and Gateway approvals."""

from __future__ import annotations

from types import SimpleNamespace


def test_runner_local_pending_maps_stock_card(monkeypatch):
    import api.routes as routes

    monkeypatch.setattr("api.runtime_adapter.runtime_adapter_runner_enabled", lambda: True)
    monkeypatch.setattr(routes, "get_session", lambda _sid: SimpleNamespace(active_stream_id="run-1"))

    class _Adapter:
        def get_run(self, run_id):
            assert run_id == "run-1"
            return SimpleNamespace(pending_approval_id="perm9")

        def observe_run(self, run_id, cursor=None):
            return SimpleNamespace(events=[{
                "event": "approval",
                "payload": {
                    "approval_id": "perm9",
                    "description": "Allow filesystem.write_file? mobile-verification.txt [WRITE_LOCAL]",
                    "command": "filesystem.write_file",
                    "tool": "filesystem.write_file",
                },
            }])

    monkeypatch.setattr(
        "api.runtime_adapter.build_runtime_adapter",
        lambda **_k: _Adapter(),
    )
    pending = routes._runner_local_pending("sess-phone")
    assert pending["approval_id"] == "perm9"
    assert "write_file" in pending["description"]
    assert pending["command"]
    assert pending["_runner_local"] is True


def test_gateway_store_pending_maps_tool_target_reason(monkeypatch):
    import api.routes as routes
    import json

    payload = {
        "approvals": [{
            "approval_id": "approval_abc",
            "session_id": "gw-sess",
            "status": "pending",
            "prompt": "Allow filesystem.write_file? workspace/x.txt",
            "options": ["once", "deny"],
            "metadata": {
                "tool": "filesystem.write_file",
                "target": "workspace/x.txt",
                "reason": "WRITE_LOCAL",
            },
        }]
    }

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps(payload).encode()

    monkeypatch.setattr("api.jaeger_sessions.gateway_base", lambda: "http://127.0.0.1:8810")
    monkeypatch.setattr("urllib.request.urlopen", lambda *_a, **_k: _Resp())
    pending = routes._gateway_store_pending("gw-sess")
    assert pending["approval_id"] == "approval_abc"
    assert pending["tool"] == "filesystem.write_file"
    assert "WRITE_LOCAL" in pending["description"]
    assert pending["_jaeger_gateway_store"] is True


def test_gateway_store_pending_ignores_other_sessions(monkeypatch):
    import api.routes as routes
    import json

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps({
                "approvals": [{
                    "approval_id": "approval_other",
                    "session_id": "someone-else",
                    "status": "pending",
                    "prompt": "Allow?",
                    "metadata": {},
                }]
            }).encode()

    monkeypatch.setattr("api.jaeger_sessions.gateway_base", lambda: "http://127.0.0.1:8810")
    monkeypatch.setattr("urllib.request.urlopen", lambda *_a, **_k: _Resp())
    assert routes._gateway_store_pending("gw-sess") is None


def test_resident_resolve_prefers_runner(monkeypatch):
    import api.routes as routes

    monkeypatch.setattr(routes, "_runner_local_resolve", lambda *_a, **_k: True)
    monkeypatch.setattr(routes, "_gateway_store_resolve", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("gateway")))
    assert routes._resident_resolve_approval("sid", "perm9", "once") is True


def test_resident_resolve_falls_through_to_gateway(monkeypatch):
    import api.routes as routes

    monkeypatch.setattr(routes, "_runner_local_resolve", lambda *_a, **_k: None)
    monkeypatch.setattr(routes, "_gateway_store_resolve", lambda *_a, **_k: True)
    assert routes._resident_resolve_approval("sid", "approval_abc", "deny") is True
