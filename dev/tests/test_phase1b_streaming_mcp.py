"""Phase 1B tests: live token-by-token streaming providers, cache collapse health, MCP live manager, Host guard."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest
from aiohttp.test_utils import TestClient, TestServer

from jaeger_gateway import ModularGatewayRuntime
from jaeger_mcp import LiveMCPManager, load_mcp_server_configs
from jaeger_models import (
    AnthropicModel,
    ConversationCacheMarkStore,
    OllamaModel,
    OpenAICompatModel,
    bind_stream_sink,
)


def _start_mock_server(handler_cls: type[BaseHTTPRequestHandler]) -> tuple[ThreadingHTTPServer, str]:
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler_cls)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    host, port = srv.server_address
    return srv, f"http://{host}:{port}"


def test_ollama_openai_anthropic_incremental_streaming() -> None:
    class _Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args: Any) -> None:
            return

        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length).decode("utf-8"))
            assert body.get("stream") is True
            self.send_response(200)
            if self.path == "/api/chat":
                self.send_header("Content-Type", "application/x-ndjson")
                self.end_headers()
                lines = [
                    {"message": {"role": "assistant", "thinking": "step1 "}, "done": False},
                    {"message": {"role": "assistant", "content": "Hel"}, "done": False},
                    {"message": {"role": "assistant", "content": "lo!"}, "done": True, "prompt_eval_count": 12, "eval_count": 4},
                ]
                for ln in lines:
                    self.wfile.write((json.dumps(ln) + "\n").encode("utf-8"))
            elif self.path == "/v1/chat/completions":
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                events = [
                    {"choices": [{"delta": {"reasoning_content": "plan "}}]},
                    {"choices": [{"delta": {"content": "Hi "}}]},
                    {"choices": [{"delta": {"content": "there"}}]},
                    {"choices": [], "usage": {"prompt_tokens": 10, "completion_tokens": 5, "prompt_tokens_details": {"cached_tokens": 6}}},
                ]
                for ev in events:
                    self.wfile.write(f"data: {json.dumps(ev)}\n\n".encode("utf-8"))
                self.wfile.write(b"data: [DONE]\n\n")
            elif self.path == "/v1/messages":
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                events = [
                    {"type": "message_start", "message": {"usage": {"input_tokens": 20, "cache_read_input_tokens": 15}}},
                    {"type": "content_block_delta", "index": 0, "delta": {"type": "thinking_delta", "thinking": "hmm "}},
                    {"type": "content_block_delta", "index": 1, "delta": {"type": "text_delta", "text": "Done"}},
                    {"type": "message_delta", "usage": {"output_tokens": 7}},
                ]
                for ev in events:
                    self.wfile.write(f"data: {json.dumps(ev)}\n\n".encode("utf-8"))

    srv, base_url = _start_mock_server(_Handler)
    try:
        # 1. Ollama NDJSON streaming
        ollama_deltas: list[tuple[str, str]] = []
        with bind_stream_sink(lambda k, d: ollama_deltas.append((k, d))):
            res = OllamaModel("test-model", base_url=base_url).complete([{"role": "user", "content": "hi"}])
        assert res["streamed"] is True
        assert res["content"] == "Hello!"
        assert res["thinking"] == "step1 "
        assert ollama_deltas == [("thinking", "step1 "), ("text", "Hel"), ("text", "lo!")]

        # 2. OpenAI SSE streaming
        oai_deltas: list[tuple[str, str]] = []
        with bind_stream_sink(lambda k, d: oai_deltas.append((k, d))):
            res2 = OpenAICompatModel("gpt-test", base_url=f"{base_url}/v1", api_key="k").complete([{"role": "user", "content": "hi"}])
        assert res2["streamed"] is True
        assert res2["content"] == "Hi there"
        assert res2["usage"]["cache_read_tokens"] == 6
        assert oai_deltas == [("thinking", "plan "), ("text", "Hi "), ("text", "there")]

        # 3. Anthropic SSE streaming
        anth_deltas: list[tuple[str, str]] = []
        with bind_stream_sink(lambda k, d: anth_deltas.append((k, d))):
            res3 = AnthropicModel("claude-test", base_url=base_url, api_key="k").complete([{"role": "user", "content": "hi"}])
        assert res3["streamed"] is True
        assert res3["content"] == "Done"
        assert res3["thinking"] == "hmm "
        assert res3["usage"]["cache_read_tokens"] == 15
        assert anth_deltas == [("thinking", "hmm "), ("text", "Done")]
    finally:
        srv.shutdown()
        srv.server_close()


def test_prompt_cache_collapse_classifier() -> None:
    store = ConversationCacheMarkStore(ttl_s=60.0)
    assert store.record(conversation_id="c1", provider="anthropic", model="sonnet", cache_read_tokens=10000, now=10.0) is None
    ev = store.record(conversation_id="c1", provider="anthropic", model="sonnet", cache_read_tokens=2000, now=20.0)
    assert ev is not None and ev.reason == "unexpected" and ev.missed_tokens == 8000

    store.record(conversation_id="c2", provider="anthropic", model="sonnet", cache_read_tokens=10000, now=10.0)
    ev2 = store.record(conversation_id="c2", provider="anthropic", model="sonnet", cache_read_tokens=1000, now=120.0)
    assert ev2 is not None and ev2.reason == "ttl_expired"

    store.record(conversation_id="c3", provider="anthropic", model="sonnet", cache_read_tokens=10000, now=10.0)
    ev3 = store.record(conversation_id="c3", provider="anthropic", model="sonnet", cache_read_tokens=1000, compacted=True, now=15.0)
    assert ev3 is not None and ev3.reason == "compacted"


def test_mcp_server_config_loader(tmp_path: Path) -> None:
    cfg = tmp_path / "mcp_servers.json"
    cfg.write_text(
        json.dumps({
            "mcpServers": {
                "local_fs": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem", str(tmp_path)]},
                "remote_http": {"url": "http://127.0.0.1:8792/mcp"},
                "disabled_one": {"command": "echo", "enabled": False},
            }
        }),
        encoding="utf-8",
    )
    loaded = load_mcp_server_configs(cfg)
    assert [c.name for c in loaded] == ["local_fs", "remote_http"]
    assert loaded[0].transport == "stdio"
    assert loaded[1].transport == "streamable_http"
    mgr = LiveMCPManager([])
    assert mgr.list_servers_health() == []
    mgr.close()


@pytest.mark.asyncio
async def test_gateway_mcp_endpoint_and_dns_rebinding_guard(tmp_path: Path) -> None:
    rt = ModularGatewayRuntime(state_dir=tmp_path / "state", workspace=tmp_path)
    try:
        app = rt.build_app(serve_ui=False)
        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/v1/mcp/servers")
            assert resp.status == 200
            data = await resp.json()
            assert data["ok"] is True
            assert isinstance(data["servers"], list)

            evil = await client.get("/health", headers={"Host": "evil.attacker.com:33418"})
            assert evil.status == 403
    finally:
        rt.close()
