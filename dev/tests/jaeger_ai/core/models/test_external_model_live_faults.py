"""Live-socket fault coverage for the external model transport.

These tests intentionally use the real OpenAI SDK against a loopback HTTP
server.  No provider client is mocked: malformed payloads and slow responses
cross an actual TCP boundary, then a later request proves the client path can
be used again after the failure.
"""

from __future__ import annotations

import json
import threading
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from jaeger_ai.core.instance.schemas import ExternalModelConfig
from jaeger_ai.core.models.external_model import ExternalModelClient


@contextmanager
def _fault_server(actions):
    pending = list(actions)

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_POST(self):  # noqa: N802 - stdlib handler contract
            length = int(self.headers.get("Content-Length", "0"))
            self.rfile.read(length)
            action = pending.pop(0) if pending else ("ok", "recovered")
            if action[0] == "sleep":
                time.sleep(action[1])
            body = action[1] if action[0] == "malformed" else json.dumps({
                "id": "live-fault-test",
                "object": "chat.completion",
                "created": 1,
                "model": "fault-model",
                "choices": [{"index": 0, "message": {"role": "assistant", "content": action[1]}, "finish_reason": "stop"}],
            })
            encoded = body.encode()
            try:
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/v1", pending
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _client(base_url: str, timeout_s: float = 1.0) -> ExternalModelClient:
    return ExternalModelClient(ExternalModelConfig(
        enabled=True, provider="lmstudio", base_url=base_url,
        model="fault-model", timeout_s=timeout_s,
    ))


def test_malformed_provider_response_is_visible_and_next_request_recovers():
    with _fault_server([("malformed", "{not-json"), ("ok", "recovered")]) as (url, pending):
        client = _client(url)
        with pytest.raises(Exception, match="Expecting|JSON|json|decode"):
            client.chat([{"role": "user", "content": "first"}])
        assert client.chat([{"role": "user", "content": "second"}]).text == "recovered"
        assert pending == []


def test_provider_timeout_is_bounded_retried_and_next_request_recovers():
    # The production OpenAI SDK performs three bounded transport attempts.
    # Calling the production shim directly isolates that transport contract
    # from Jaeger's outer cloud retry policy, then a fourth request succeeds.
    actions = [("sleep", 0.2), ("sleep", 0.2), ("sleep", 0.2), ("ok", "reconnected")]
    with _fault_server(actions) as (url, pending):
        client = _client(url, timeout_s=0.05)
        started = time.monotonic()
        messages = [{"role": "user", "content": "slow"}]
        with pytest.raises(Exception, match="timed out|timeout"):
            client._chat_openai(messages, 32, 0.0, 0.95)
        assert time.monotonic() - started < 5.0
        recovered = client._chat_openai(
            [{"role": "user", "content": "retry cleanly"}], 32, 0.0, 0.95,
        )
        assert recovered == "reconnected"
        assert pending == []
