"""Scoped native permission checks; SQLite fixtures only, never real approvals."""
from jaeger_ai.core.gateway.session_store import GatewaySessionStore


def fixture(tmp_path):
    store = GatewaySessionStore(tmp_path / "gateway.sqlite3")
    store.admit_request("s", "question", request_id="r")
    store.create_approval(kind="tool_confirm", prompt="Allow fixture?", options=["once", "deny"], session_id="s", request_id="r", approval_id="a")
    profile = store.get_session("s")["profile"]
    return store, dict(expected_session_id="s", expected_request_id="r", expected_profile=profile)


def test_native_decision_cannot_change_session_request_profile_or_options(tmp_path):
    store, context = fixture(tmp_path)
    for field in context:
        wrong = {**context, field:"wrong"}
        assert store.resolve_approval("a", approved=True, decision="once", **wrong) is None
    assert store.resolve_approval("a", approved=True, decision="always", **context) is None
    assert store.get_approval("a")["status"] == "pending"
    assert store.resolve_approval("a", approved=True, decision="once", **context)["decision"] == "once"
    assert store.resolve_approval("a", approved=False, decision="deny", **context) is None


def test_stopped_or_expired_request_cannot_release_a_native_approval(tmp_path):
    store, context = fixture(tmp_path)
    store.mark_request_status("r", "cancelling")
    assert store.resolve_approval("a", approved=True, decision="once", **context) is None
    assert store.get_approval("a")["status"] == "pending"
    store.resolve_approval("a", approved=False, decision="expired")
    assert store.resolve_approval("a", approved=True, decision="once", **context) is None
    assert store.get_approval("a")["decision"] == "expired"


def test_expired_api_decision_does_not_release_live_waiter(tmp_path):
    import asyncio
    from types import SimpleNamespace
    from jaeger_ai.core.gateway.server import JaegerGatewayApp
    store, context = fixture(tmp_path)
    store.resolve_approval("a", approved=False, decision="expired")

    async def check():
        future = asyncio.get_running_loop().create_future()
        app = SimpleNamespace(store=store, pending_approvals={"a":future})
        async def body():
            return {"decision":"once", **context}
        request = SimpleNamespace(match_info={"id":"a"},can_read_body=True,json=body)
        response = await JaegerGatewayApp.handle_resolve_approval(app, request)
        assert response.status == 409
        assert app.pending_approvals["a"] is future
        assert not future.done()
    asyncio.run(check())


def test_guarded_route_requires_context_and_existing_approve_scope(tmp_path):
    import asyncio
    from types import SimpleNamespace
    from jaeger_ai.core.gateway.caller_auth import required_scope
    from jaeger_ai.core.gateway.server import JaegerGatewayApp
    assert required_scope("POST", "/v1/approvals/{id}/decision") == "approve"
    store, _ = fixture(tmp_path)
    async def check():
        async def body(): return {"decision":"once"}
        request = SimpleNamespace(path="/v1/approvals/a/decision",match_info={"id":"a"},can_read_body=True,json=body)
        response = await JaegerGatewayApp.handle_resolve_approval(SimpleNamespace(store=store),request)
        assert response.status == 400
        assert store.get_approval("a")["status"] == "pending"
    asyncio.run(check())
