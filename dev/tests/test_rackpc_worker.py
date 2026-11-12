from jaeger_ai.core.gateway import caller_auth as ca




def task(i, **kw):
    return {"id": i, "thread": "t1", "to": "rackpc", "kind": "task", "from": "grokbot",
            "body": "say PONG", "created_at": 9e12, **kw}










def test_rackpc_caller_is_confined():
    spec = ca.CALLERS["rackpc"]
    assert spec.session_prefix == "rackpc:" and "admin" not in spec.scopes and "approve" not in spec.scopes
    ok = ca.prefixed_route_allowed
    assert ok("GET", "/v1/agent-messages", "rackpc") and ok("POST", "/v1/agent-messages", "rackpc")
    assert ok("GET", "/v1/agent-threads/{thread}", "rackpc")
    assert not ok("POST", "/v1/agent-goals", "rackpc")
    assert not ok("POST", "/v1/sessions/{id}/turns", "rackpc")
    assert not ok("GET", "/v1/sessions/{id}", "rackpc")
    assert not ok("GET", "/v1/activity", "rackpc")
    assert ok("POST", "/v1/agent-goals", "ares")  # other callers unchanged
