"""Tests for POST /v1/widgets/generate (AI dashboard widget specs).

Covers: auth/scope enforcement, body validation, schema validation of model
output (the security-critical part — model output is never trusted), the
503 path when no external model is configured, and a happy path with a fake
model client. Real LLM calls are never made in tests.
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from aiohttp.test_utils import TestClient, TestServer

from jaeger_ai.core.gateway import caller_auth
from jaeger_ai.core.gateway import widget_routes
from jaeger_ai.core.gateway.server import JaegerGatewayApp
from jaeger_ai.core.gateway.session_store import GatewaySessionStore


def H(caller: str) -> dict[str, str]:
    headers = caller_auth.client_headers(caller)
    assert headers, f"test token for {caller} missing"
    return headers


@pytest_asyncio.fixture
async def gw(tmp_path, monkeypatch):
    monkeypatch.setenv("JAEGER_STATE_DIR", str(tmp_path / "state"))
    gateway = JaegerGatewayApp(store=GatewaySessionStore(tmp_path / "gw.sqlite3"))
    gateway.app.on_startup.clear()
    async with TestClient(TestServer(gateway.app)) as client:
        yield client


# ── schema validation (pure, no HTTP) ──────────────────────────────────────

GOOD_SPEC = {
    "v": 1,
    "source": "diagnostics",
    "title": "Pending approvals",
    "about": "Shows how many approvals are waiting on you",
    "metrics": [{"key": "approvals.pending", "label": "Pending"}],
    "chart": "stat",
    "size": "sm",
    "hosts": ["page"],
}


def test_validate_spec_accepts_good_spec():
    out = widget_routes.validate_spec(dict(GOOD_SPEC))
    assert out["source"] == "diagnostics"
    assert out["metrics"][0]["key"] == "approvals.pending"


@pytest.mark.parametrize("mutate", [
    lambda s: s.update(v=2),                                  # bad version
    lambda s: s.update(source="eval"),                        # unknown source
    lambda s: s["metrics"].__setitem__(0, {"key": "requests.; DROP", "label": "x"}),  # injection-ish key
    lambda s: s["metrics"].__setitem__(0, {"key": "made_up_field", "label": "x"}),    # unknown field
    lambda s: s.update(chart="3d-pie"),                       # unknown chart
    lambda s: s.update(size="xxl"),                           # unknown size
    lambda s: s.update(title="<script>alert(1)</script>"),    # HTML in title
    lambda s: s["metrics"].clear(),                           # empty metrics
    lambda s: s.update(hosts=["menubar"]),                    # host not allowed
])
def test_validate_spec_rejects_bad_specs(mutate):
    spec = {k: (v.copy() if isinstance(v, (list, dict)) else v) for k, v in GOOD_SPEC.items()}
    # deep-ish copy for metrics list of dicts
    spec["metrics"] = [dict(m) for m in GOOD_SPEC["metrics"]]
    spec["hosts"] = list(GOOD_SPEC["hosts"])
    mutate(spec)
    with pytest.raises(ValueError):
        widget_routes.validate_spec(spec)


def test_validate_spec_rejects_non_dict():
    with pytest.raises(ValueError):
        widget_routes.validate_spec(["not", "a", "dict"])


# ── HTTP surface ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_generate_requires_auth(gw):
    resp = await gw.post("/v1/widgets/generate", json={"prompt": "x"})
    assert resp.status == 401


@pytest.mark.asyncio
async def test_generate_rejects_bad_body(gw):
    resp = await gw.post("/v1/widgets/generate", headers=H("webui"), json={"prompt": ""})
    assert resp.status == 400
    resp = await gw.post("/v1/widgets/generate", headers=H("webui"), data="not json")
    assert resp.status == 400
    resp = await gw.post("/v1/widgets/generate", headers=H("webui"),
                         json={"prompt": "x" * 1001})
    assert resp.status == 400


@pytest.mark.asyncio
async def test_generate_503_without_external_model(gw, monkeypatch):
    # No instance config.yaml under the isolated JAEGER_STATE_DIR → 503.
    resp = await gw.post("/v1/widgets/generate", headers=H("webui"),
                         json={"prompt": "show pending approvals"})
    assert resp.status == 503
    body = await resp.json()
    assert "error" in body


@pytest.mark.asyncio
async def test_generate_happy_path_with_fake_model(gw, monkeypatch):
    import json as _json
    fake_text = _json.dumps(GOOD_SPEC)

    class _Result:
        text = fake_text
        latency_s = 0.01

    class _FakeClient:
        provider = "anthropic"
        model_name = "fake"

        def chat(self, messages, **kwargs):
            assert messages[0]["role"] == "system"
            assert "metrics" in messages[0]["content"]
            return _Result()

    monkeypatch.setattr(
        widget_routes, "_load_external_client",
        lambda: (_FakeClient(), type("Ext", (), {"max_tokens": 1024})()),
    )
    resp = await gw.post("/v1/widgets/generate", headers=H("webui"),
                         json={"prompt": "show pending approvals"})
    assert resp.status == 201
    body = await resp.json()
    assert body["spec"]["title"] == "Pending approvals"
    assert body["spec"]["v"] == 1
    assert "latency_s" in body


@pytest.mark.asyncio
async def test_generate_422_when_model_returns_invalid_spec(gw, monkeypatch):
    import json as _json

    class _Result:
        text = _json.dumps({"v": 1, "source": "eval", "title": "x"})
        latency_s = 0.01

    class _FakeClient:
        def chat(self, messages, **kwargs):
            return _Result()

    monkeypatch.setattr(
        widget_routes, "_load_external_client",
        lambda: (_FakeClient(), type("Ext", (), {"max_tokens": 1024})()),
    )
    resp = await gw.post("/v1/widgets/generate", headers=H("webui"),
                         json={"prompt": "do something bad"})
    assert resp.status == 422
    body = await resp.json()
    assert "error" in body


@pytest.mark.asyncio
async def test_generate_422_when_model_returns_non_json(gw, monkeypatch):
    class _Result:
        text = "I cannot help with that."
        latency_s = 0.01

    class _FakeClient:
        def chat(self, messages, **kwargs):
            return _Result()

    monkeypatch.setattr(
        widget_routes, "_load_external_client",
        lambda: (_FakeClient(), type("Ext", (), {"max_tokens": 1024})()),
    )
    resp = await gw.post("/v1/widgets/generate", headers=H("webui"),
                         json={"prompt": "hello"})
    assert resp.status == 422


@pytest.mark.asyncio
async def test_generate_502_on_model_exception(gw, monkeypatch):
    class _FakeClient:
        def chat(self, messages, **kwargs):
            raise RuntimeError("boom")

    monkeypatch.setattr(
        widget_routes, "_load_external_client",
        lambda: (_FakeClient(), type("Ext", (), {"max_tokens": 1024})()),
    )
    resp = await gw.post("/v1/widgets/generate", headers=H("webui"),
                         json={"prompt": "anything"})
    assert resp.status == 502
    body = await resp.json()
    assert "boom" not in body["error"]  # internals never leak
