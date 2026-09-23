"""HTTP → real EntityRuntime → real JaegerAgent; scripted provider boundary.

Restarts only this test's child. No operator listener, model, or live database
is used. This is a Gateway contract, not yet WebUI/Swift live acceptance.
"""

import hashlib
import json
import os
import re
import socket
import subprocess
import sys
import time
from http.cookiejar import CookieJar
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import HTTPCookieProcessor, Request, build_opener, urlopen

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.subprocess]
REPO = Path(__file__).resolve().parents[4]


class OwnedGateway:
    def __init__(self, root, *, webui=False):
        self.root = root
        self.process = None
        self.log = None
        self.url = ""
        self.identity = None
        self.webui = webui
        self.webui_url = None

    def start(self):
        ready = self.root / "listener.json"
        ready.unlink(missing_ok=True)
        self.log = (self.root / "gateway.log").open("a", encoding="utf-8")
        environment = {
            **os.environ, "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONPATH": os.pathsep.join([
                str(REPO), str(REPO / "packages/jaeger-agent"), str(REPO / "packages/jaeger-os"),
            ]),
            "JAEGER_STATE_DIR": str(self.root),
            "JAEGER_HOME": str(self.root),
            "JAEGER_INSTANCE_DIR": str(self.root / "instances" / "contract"),
            "JAEGER_CRON_POLL_S": "0.2",
            "JAEGER_IDLE_POLL_S": "0.2",
            "JAEGER_BACKGROUND_PRODUCERS": "1",
            "JAEGER_WEBHOOK_PORT": "0",
        }
        command = [sys.executable, str(REPO / "dev/tests/fixtures/gateway_contract_worker.py"), str(self.root)]
        if self.webui:
            command.append("--webui")
        self.process = subprocess.Popen(
            command,
            cwd=self.root, env=environment, stdout=self.log, stderr=subprocess.STDOUT,
        )
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if ready.exists():
                listener = json.loads(ready.read_text(encoding="utf-8"))
                assert listener["pid"] == self.process.pid
                assert listener["mode"] == "owner"
                assert listener["resident"] is True
                self.identity = listener["entity_id"]
                self.url = f"http://127.0.0.1:{listener['port']}"
                if self.webui:
                    self.webui_url = f"http://127.0.0.1:{listener['webui_port']}"
                return
            if self.process.poll() is not None:
                break
            time.sleep(0.05)
        raise AssertionError((self.root / "gateway.log").read_text(encoding="utf-8"))

    def stop(self):
        if self.process is not None and self.process.poll() is None:
            self.process.kill()
            self.process.wait(timeout=5)
        if self.log is not None:
            self.log.close()

    def request(self, path, body=None):
        request = Request(
            self.url + path, data=None if body is None else json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urlopen(request, timeout=5) as response:
            return response.status, json.load(response)

    def wait_for_terminal(self, session, request_id):
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            _, row = self.request(f"/v1/sessions/{session}/requests/{request_id}")
            if row["status"] in {"completed", "failed", "execution_unknown", "cancelled"}:
                return row
            time.sleep(0.05)
        raise AssertionError((self.root / "gateway.log").read_text())


@pytest.fixture
def gateway(tmp_path):
    owned = OwnedGateway(tmp_path)
    try:
        owned.start()
        yield owned
    finally:
        owned.stop()


_TERMINAL_EVENTS = {"turn.finish", "turn.failed", "turn.cancelled", "turn.unknown"}


def _terminal_events(gateway, session, request_id):
    """Every durable terminal event for ``request_id``, replayed from the
    session stream up to the first terminal event of the *next* request."""
    found = []
    with urlopen(gateway.url + f"/v1/sessions/{session}/stream", timeout=5) as stream:
        for line in stream:
            if not line.startswith(b"data: "):
                continue
            event = json.loads(line[6:])
            if event["event"] not in _TERMINAL_EVENTS:
                continue
            if event["data"].get("request_id") == request_id:
                found.append(event["event"])
            else:
                break
    return found


def _request_events(gateway, session, request_id):
    """Replay the session stream up to this request's terminal event."""
    seen = []
    with urlopen(gateway.url + f"/v1/sessions/{session}/stream", timeout=5) as stream:
        for line in stream:
            if not line.startswith(b"data: "):
                continue
            event = json.loads(line[6:])
            if event["data"].get("request_id") != request_id:
                continue
            seen.append(event)
            if event["event"] in _TERMINAL_EVENTS:
                break
    return seen


def test_owner_turn_streams_answer_text_as_durable_deltas(gateway):
    """Streaming parity (R02/C01 prerequisite): the Gateway owner path emits
    the answer incrementally, as the bridge always did, and replay after a
    restart reproduces exactly the same text before the terminal event."""
    gateway.request("/v1/sessions", {"session_id": "stream", "profile": "jaeger"})
    gateway.request("/v1/sessions/stream/turns", {
        "text": "Say CONTRACT-ANSWER", "request_id": "stream-request",
    })
    assert gateway.wait_for_terminal("stream", "stream-request")["status"] == "completed"

    events = _request_events(gateway, "stream", "stream-request")
    names = [e["event"] for e in events]
    streamed = "".join(e["data"].get("delta", "") for e in events if e["event"] == "turn.delta")
    assert streamed == "CONTRACT-ANSWER", names
    assert names[-1] == "turn.finish"
    assert names.index("turn.finish") > max(i for i, n in enumerate(names) if n == "turn.delta")

    gateway.stop()
    gateway.start()
    replayed = _request_events(gateway, "stream", "stream-request")
    assert [(e["event"], e["data"].get("delta")) for e in replayed] == \
        [(e["event"], e["data"].get("delta")) for e in events]


def test_owner_cancellation_interrupts_inflight_provider(gateway):
    """R03: cancel reaches the running agent while the provider is blocked.

    The scripted provider is never released: the only way this request can
    reach a terminal state is the agent's interrupt waking the provider wait.
    """
    gateway.request("/v1/sessions", {"session_id": "cancel", "profile": "jaeger"})
    gateway.request("/v1/sessions/cancel/turns", {
        "text": "Say CONTRACT-WAIT", "request_id": "cancel-request",
    })
    deadline = time.monotonic() + 10
    while not (gateway.root / "provider-waiting").exists():
        assert time.monotonic() < deadline, (gateway.root / "gateway.log").read_text()
        time.sleep(0.05)
    _, accepted = gateway.request("/v1/sessions/cancel/cancel", {"request_id": "cancel-request"})
    assert accepted["cancel_requested"] is True
    assert accepted["interrupt_delivered"] is True
    assert accepted["native_cancel_requested"] is False  # no legacy MCP detour

    terminal = gateway.wait_for_terminal("cancel", "cancel-request")

    assert not (gateway.root / "provider-release").exists()
    assert terminal["status"] == "cancelled", terminal
    assert terminal["result"]["error"] == "cancelled during execution"
    calls = (gateway.root / "provider-calls.jsonl").read_text().splitlines()
    assert len(calls) == 1, "no provider call may follow the interrupt"
    _, again = gateway.request("/v1/sessions/cancel/cancel", {"request_id": "cancel-request"})
    assert again["already_terminal"] is True
    session = gateway.request("/v1/sessions/cancel")[1]
    assert session["status"] == "idle", session

    gateway.stop()
    gateway.start()
    _, row = gateway.request("/v1/sessions/cancel/requests/cancel-request")
    assert row["status"] == "cancelled"
    assert (gateway.root / "provider-calls.jsonl").read_text().splitlines() == calls
    status, replay = gateway.request("/v1/sessions/cancel/turns", {
        "text": "Say CONTRACT-WAIT", "request_id": "cancel-request",
    })
    assert replay["replayed"] is True and replay["status"] == "cancelled"
    # The session accepts a new turn after the cancelled one.
    gateway.request("/v1/sessions/cancel/turns", {
        "text": "Say CONTRACT-ANSWER", "request_id": "after-cancel",
    })
    assert gateway.wait_for_terminal("cancel", "after-cancel")["status"] == "completed"
    assert _terminal_events(gateway, "cancel", "cancel-request") == ["turn.cancelled"]


def test_cancelling_one_session_leaves_a_concurrent_session_running(gateway):
    for session in ("blocked", "other"):
        gateway.request("/v1/sessions", {"session_id": session, "profile": "jaeger"})
    gateway.request("/v1/sessions/blocked/turns", {
        "text": "Say CONTRACT-WAIT", "request_id": "blocked-request",
    })
    deadline = time.monotonic() + 10
    while not (gateway.root / "provider-waiting").exists():
        assert time.monotonic() < deadline, (gateway.root / "gateway.log").read_text()
        time.sleep(0.05)

    gateway.request("/v1/sessions/other/turns", {
        "text": "Say CONTRACT-ANSWER", "request_id": "other-request",
    })
    other = gateway.wait_for_terminal("other", "other-request")
    assert other["status"] == "completed", other
    _, still = gateway.request("/v1/sessions/blocked/requests/blocked-request")
    assert still["status"] == "running", "the other session's turn must not end this one"

    gateway.request("/v1/sessions/blocked/cancel", {"request_id": "blocked-request"})
    assert gateway.wait_for_terminal("blocked", "blocked-request")["status"] == "cancelled"
    _, other_after = gateway.request("/v1/sessions/other/requests/other-request")
    assert other_after["status"] == "completed"


def test_cancel_during_approval_wait_closes_approval_and_leaves_no_effect(gateway):
    gateway.request("/v1/sessions", {"session_id": "contract", "profile": "jaeger"})
    gateway.request("/v1/sessions/contract/turns", {
        "text": "CONTRACT-WRITE: write the test file", "request_id": "approval-cancel",
    })
    target = gateway.root / "instances/contract/workspace/contract-output.txt"
    deadline = time.monotonic() + 15
    pending = []
    while time.monotonic() < deadline and not pending:
        pending = gateway.request("/v1/approvals")[1]["approvals"]
        time.sleep(0.05)
    assert pending, (gateway.root / "gateway.log").read_text()

    gateway.request("/v1/sessions/contract/cancel", {"request_id": "approval-cancel"})
    terminal = gateway.wait_for_terminal("contract", "approval-cancel")

    assert terminal["status"] == "cancelled", terminal
    assert not target.exists(), "a cancelled request must not perform the pending write"
    assert gateway.request("/v1/approvals")[1]["approvals"] == []
    with pytest.raises(HTTPError) as late:
        gateway.request("/v1/approvals/" + pending[0]["approval_id"],
                        {"approved": True, "decision": "once"})
    assert late.value.code == 409
    assert not target.exists()


def test_real_owner_turn_survives_process_restart_and_sse_replay(gateway):
    status, _ = gateway.request("/v1/sessions", {"session_id": "contract", "profile": "jaeger"})
    assert status == 201
    body = {"text": "Say CONTRACT-ANSWER", "request_id": "contract-request"}
    status, admitted = gateway.request("/v1/sessions/contract/turns", body)
    assert status == 200
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        _, row = gateway.request("/v1/sessions/contract/requests/contract-request")
        if row.get("status") in {"completed", "failed", "execution_unknown"}:
            break
        time.sleep(0.05)
    assert row["status"] == "completed", (row, (gateway.root / "gateway.log").read_text())
    assert row["result"]["output"] == "CONTRACT-ANSWER"
    assert row["result"]["backend"] == "owner-react"
    assert row["native_run_id"]
    before = gateway.request("/v1/sessions/contract")[1]
    provider_calls = (gateway.root / "provider-calls.jsonl").read_text().splitlines()
    assert len(provider_calls) == 1
    identity = gateway.identity
    gateway.stop()
    gateway.start()
    assert gateway.identity == identity
    after = gateway.request("/v1/sessions/contract")[1]
    assert after["messages"] == before["messages"]
    status, replay = gateway.request("/v1/sessions/contract/turns", body)
    assert status == 200
    assert replay["replayed"] is True
    assert replay["turn_id"] == admitted["turn_id"]
    assert replay["output"] == "CONTRACT-ANSWER"
    assert (gateway.root / "provider-calls.jsonl").read_text().splitlines() == provider_calls
    events = []
    with urlopen(gateway.url + "/v1/sessions/contract/stream", timeout=5) as stream:
        assert stream.headers["Content-Type"] == "text/event-stream"
        for line in stream:
            if line.startswith(b"data: "):
                event = json.loads(line[6:])
                events.append(event)
                if event["event"] == "turn.finish":
                    break
    assert events[-1]["data"]["request_id"] == "contract-request"
    assert [event["event_id"] for event in events] == sorted({event["event_id"] for event in events})


@pytest.mark.parametrize("approved", [True, False])
def test_real_tool_write_requires_gateway_approval(gateway, approved):
    gateway.request("/v1/sessions", {"session_id": "contract", "profile": "jaeger"})
    gateway.request("/v1/sessions/contract/turns", {
        "text": "CONTRACT-WRITE: write the test file", "request_id": "tool-request",
    })
    target = gateway.root / "instances/contract/workspace/contract-output.txt"
    deadline = time.monotonic() + 15
    pending = []
    while time.monotonic() < deadline:
        pending = gateway.request("/v1/approvals")[1]["approvals"]
        if pending:
            break
        time.sleep(0.05)
    assert pending, (gateway.root / "gateway.log").read_text()
    assert not target.exists(), "a tool must not write before the operator's approval"
    approval = pending[0]
    gateway.request("/v1/approvals/" + approval["approval_id"], {
        "approved": approved, "decision": "once" if approved else "deny",
    })
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        _, row = gateway.request("/v1/sessions/contract/requests/tool-request")
        if row["status"] in {"completed", "failed", "execution_unknown"}:
            break
        time.sleep(0.05)
    assert row["status"] in {"completed", "failed"}, row
    assert gateway.request("/v1/approvals")[1]["approvals"] == []
    if approved:
        assert row["status"] == "completed", row
        assert target.read_text(encoding="utf-8") == "CONTRACT-CONTENT"
    else:
        assert not target.exists()
    assert not (gateway.root / "instances/contract/.git").exists()


def test_owned_webui_auth_and_session_proxy_use_owned_gateway(tmp_path):
    stack = OwnedGateway(tmp_path, webui=True)
    try:
        stack.start()
        endpoint = stack.webui_url + "/api/jaeger/sessions"
        with pytest.raises(HTTPError) as denied:
            urlopen(endpoint, timeout=5)
        assert denied.value.code == 401
        cookies = CookieJar()
        browser = build_opener(HTTPCookieProcessor(cookies))
        login = Request(
            stack.webui_url + "/api/auth/login",
            data=json.dumps({"password": "synthetic-contract-password"}).encode(),
            headers={"Content-Type": "application/json"},
        )
        with browser.open(login, timeout=5) as response:
            assert json.load(response) == {"ok": True}
        assert any(cookie.name == "hermes_session" for cookie in cookies)
        with browser.open(stack.webui_url + "/", timeout=5) as response:
            html = response.read().decode()
        match = re.search(r'csrfToken:("[^"]*")', html)
        assert match is not None
        csrf = json.loads(match.group(1))
        assert csrf
        body = json.dumps({"session_id": "web-contract", "profile": "jaeger"}).encode()
        with pytest.raises(HTTPError) as rejected:
            browser.open(Request(endpoint, data=body, headers={"Content-Type": "application/json"}), timeout=5)
        assert rejected.value.code == 403
        create = Request(endpoint, data=body, headers={
            "Content-Type": "application/json", "X-Hermes-CSRF-Token": csrf,
        })
        try:
            with browser.open(create, timeout=5) as response:
                assert response.status == 201
                session = json.load(response)
        except HTTPError as error:
            pytest.fail(f"{error.code}: {error.read().decode()}\n" +
                        (stack.root / "gateway.log").read_text())
        assert session["session_id"] == "web-contract"
        with browser.open(endpoint + "/web-contract", timeout=5) as response:
            projected = json.load(response)
        canonical = stack.request("/v1/sessions/web-contract")[1]
        assert projected == canonical
        send = Request(endpoint + "/web-contract/turns", data=json.dumps({
            "text": "Say CONTRACT-ANSWER", "request_id": "web-request",
        }).encode(), headers={
            "Content-Type": "application/json", "X-Hermes-CSRF-Token": csrf,
        })
        with browser.open(send, timeout=5) as response:
            assert json.load(response)["request_id"] == "web-request"
        terminal = None
        with browser.open(endpoint + "/web-contract/stream", timeout=10) as stream:
            assert stream.headers["Content-Type"].startswith("text/event-stream")
            for line in stream:
                if line.startswith(b"data: "):
                    event = json.loads(line[6:])
                    if event["event"] in {"turn.finish", "turn.failed", "turn.unknown"}:
                        terminal = event
                        break
        assert terminal is not None
        assert terminal["event"] == "turn.finish", terminal
        assert terminal["data"]["output"] == "CONTRACT-ANSWER"
        before = stack.request("/v1/sessions/web-contract")[1]
        identity = stack.identity
        stack.stop()
        stack.start()
        assert stack.identity == identity
        # Cookie sessions and the transcript survive restart of both servers.
        with browser.open(stack.webui_url + "/api/jaeger/sessions/web-contract", timeout=5) as response:
            assert json.load(response)["messages"] == before["messages"]
    finally:
        stack.stop()


def test_owned_webui_composer_chat_start_routes_to_jaeger_gateway(tmp_path, monkeypatch):
    """Assert browser composer (/api/chat/start) routes to Jaeger Gateway across 5 distinct turns.

    Covers:
      1. First turn streaming with distinct output (TURN-1-ALPHA)
      2. Second consecutive turn in same session without crash (TURN-2-BETA)
      3. Third turn forwarding options/attachments (TURN-3-GAMMA)
      4. Fourth turn cancellation with verified 'cancel' SSE event on stream
      5. Fifth turn post-cancel execution proving session is not wedged in busy state
      6. History persistence alignment between WebUI and Jaeger Gateway store
    """
    monkeypatch.setenv("JAEGER_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("JAEGER_HOME", str(tmp_path))

    stack = OwnedGateway(tmp_path, webui=True)
    try:
        stack.start()
        cookies = CookieJar()
        browser = build_opener(HTTPCookieProcessor(cookies))
        login = Request(
            stack.webui_url + "/api/auth/login",
            data=json.dumps({"password": "synthetic-contract-password"}).encode(),
            headers={"Content-Type": "application/json"},
        )
        with browser.open(login, timeout=5) as response:
            assert json.load(response) == {"ok": True}
        with browser.open(stack.webui_url + "/", timeout=5) as response:
            html = response.read().decode()
        match = re.search(r'csrfToken:("[^"]*")', html)
        assert match is not None
        csrf = json.loads(match.group(1))

        sid = "composer-gateway-5turn-test"
        chat_start_url = stack.webui_url + "/api/chat/start"
        seen_stream_ids = set()

        def _execute_turn(message_text, attachments=None):
            req_body = {
                "message": message_text,
                "session_id": sid,
                "model": "contract-model",
            }
            if attachments:
                req_body["attachments"] = attachments
            start_req = Request(chat_start_url, data=json.dumps(req_body).encode(), headers={
                "Content-Type": "application/json", "X-Hermes-CSRF-Token": csrf,
            })
            try:
                with browser.open(start_req, timeout=15) as resp:
                    start_payload = json.load(resp)
            except HTTPError as err:
                err_body = err.read().decode("utf-8", errors="replace")
                log_content = (stack.root / "gateway.log").read_text(encoding="utf-8", errors="replace")
                raise AssertionError(f"Turn '{message_text}' HTTPError {err.code}: {err_body}\n--- gateway.log ---\n{log_content}") from err
            assert "stream_id" in start_payload, start_payload
            stream_id = start_payload["stream_id"]
            assert stream_id not in seen_stream_ids, f"Duplicate stream_id {stream_id}"
            seen_stream_ids.add(stream_id)

            stream_url = f"{stack.webui_url}/api/chat/stream?stream_id={stream_id}&session_id={sid}"
            tokens = []
            done_payload = None
            with browser.open(stream_url, timeout=15) as stream:
                current_event = "message"
                for raw_line in stream:
                    line = raw_line.decode("utf-8", errors="replace").strip()
                    if not line:
                        continue
                    if line.startswith("event:"):
                        current_event = line[6:].strip()
                    elif line.startswith("data:"):
                        data = json.loads(line[5:].strip())
                        if current_event == "token":
                            tokens.append(data.get("text", ""))
                        elif current_event == "done":
                            done_payload = data
                            break
                        elif current_event in ("error", "apperror"):
                            pytest.fail(f"Received error event from WebUI stream: {data}")
            assert done_payload is not None, f"Turn '{message_text}' did not receive done event"
            return "".join(tokens), stream_id

        # Turn 1: Say TURN-1-ALPHA
        ans1, sid1 = _execute_turn("Say TURN-1-ALPHA")
        assert "TURN-1-ALPHA" in ans1

        # Turn 2: Follow-up in same session
        ans2, sid2 = _execute_turn("Say TURN-2-BETA-CONTEXT")
        assert "TURN-2-BETA-CONTEXT" in ans2

        # Turn 3: Attachment & options turn
        attachment_workspace = tmp_path / "instances" / "contract" / "workspace"
        attachment_workspace.mkdir(parents=True, exist_ok=True)
        att_file = attachment_workspace / "contract-doc.txt"
        att_file.write_text("sample attachment content", encoding="utf-8")
        ans3, sid3 = _execute_turn(
            "Say TURN-3-GAMMA-ATTACHMENT",
            attachments=[{"name": "contract-doc.txt", "path": str(att_file), "size": 25, "mime": "text/plain"}],
        )
        assert "TURN-3-GAMMA-ATTACHMENT" in ans3
        _, third_request = stack.request(f"/v1/sessions/{sid}/requests/{sid3}")
        third_attachments = third_request["execution"]["attachments"]
        assert len(third_attachments) == 1
        assert third_attachments[0]["attachment_id"]
        assert third_attachments[0]["size_bytes"] == att_file.stat().st_size
        assert third_attachments[0]["sha256"] == hashlib.sha256(att_file.read_bytes()).hexdigest()

        # Turn 4: Cancellation
        cancel_req = Request(chat_start_url, data=json.dumps({
            "message": "CONTRACT-WAIT slow response",
            "session_id": sid,
            "model": "contract-model",
        }).encode(), headers={
            "Content-Type": "application/json", "X-Hermes-CSRF-Token": csrf,
        })
        with browser.open(cancel_req, timeout=15) as response:
            cancel_start = json.load(response)
        cancel_stream_id = cancel_start["stream_id"]
        seen_stream_ids.add(cancel_stream_id)

        # Open stream FIRST (as a real browser does)
        cancel_stream_url = f"{stack.webui_url}/api/chat/stream?stream_id={cancel_stream_id}&session_id={sid}"
        stream = browser.open(cancel_stream_url, timeout=15)

        # Issue cancellation while stream is connected
        cancel_post = Request(f"{stack.webui_url}/api/chat/cancel?stream_id={cancel_stream_id}", data=b"{}", headers={
            "Content-Type": "application/json", "X-Hermes-CSRF-Token": csrf,
        })
        with browser.open(cancel_post, timeout=5) as response:
            assert json.load(response).get("ok") is True

        # Verify stream receives 'cancel' terminal event
        saw_stream_cancel = False
        current_event = "message"
        for raw_line in stream:
            line = raw_line.decode("utf-8", errors="replace").strip()
            if not line:
                continue
            if line.startswith("event:"):
                current_event = line[6:].strip()
            elif line.startswith("data:"):
                if current_event == "cancel":
                    saw_stream_cancel = True
                    break
                elif current_event == "done":
                    break
        stream.close()
        assert saw_stream_cancel is True, "Turn 4 did not receive 'cancel' event on stream"

        # Turn 5: Post-cancellation turn (verifies session is not wedged in busy state)
        ans5, sid5 = _execute_turn("Say TURN-5-EPSILON-POST-CANCEL")
        assert "TURN-5-EPSILON-POST-CANCEL" in ans5
        _, fifth_request = stack.request(f"/v1/sessions/{sid}/requests/{sid5}")
        assert fifth_request["execution"]["attachments"] == []

        # Check session transcript in WebUI
        with browser.open(f"{stack.webui_url}/api/session?session_id={sid}", timeout=5) as response:
            sess = json.load(response)
        messages = (sess.get("session") or sess).get("messages", [])
        # Expect 4 completed turns = 8 messages (Turn 1, Turn 2, Turn 3, Turn 5)
        assert len(messages) >= 8, f"Expected at least 8 messages across 4 completed turns, got {len(messages)}"
        assert any("TURN-1-ALPHA" in m.get("content", "") for m in messages if m.get("role") == "assistant")
        assert any("TURN-2-BETA-CONTEXT" in m.get("content", "") for m in messages if m.get("role") == "assistant")
        assert any("TURN-3-GAMMA-ATTACHMENT" in m.get("content", "") for m in messages if m.get("role") == "assistant")
        assert any("TURN-5-EPSILON-POST-CANCEL" in m.get("content", "") for m in messages if m.get("role") == "assistant")

        # Verify Gateway canonical session store also recorded the completed turns
        _, gw_sess = stack.request(f"/v1/sessions/{sid}")
        gw_messages = gw_sess.get("messages", [])
        assert len(gw_messages) >= 8, f"Gateway messages {len(gw_messages)} < 8"
    finally:
        stack.stop()


@pytest.mark.parametrize("selected_model, provider", [
    ("contract-alternate", "openai"), ("@openai:contract-alternate", None),
])
def test_owner_honors_session_model_without_changing_instance_default(gateway, selected_model, provider):
    config_path = gateway.root / "instances/contract/config.yaml"
    config_before = config_path.read_bytes()
    gateway.request("/v1/sessions", {"session_id": "selected", "profile": "jaeger"})
    gateway.request("/v1/sessions/selected/turns", {
        "text": "Say CONTRACT-ANSWER", "request_id": "selected-model-request",
        "model": selected_model, "provider": provider,
    })
    row = gateway.wait_for_terminal("selected", "selected-model-request")
    assert row["status"] == "completed", row
    calls = [json.loads(line) for line in (gateway.root / "provider-calls.jsonl").read_text().splitlines()]
    assert calls == [{"model": "contract-alternate"}]
    assert row["result"]["model"] == "openai:contract-alternate"
    gateway.request("/v1/sessions/selected/turns", {
        "text": "Say CONTRACT-ANSWER again", "request_id": "retained-model-request",
    })
    retained = gateway.wait_for_terminal("selected", "retained-model-request")
    assert retained["status"] == "completed", retained
    assert retained["result"]["model"] == "openai:contract-alternate"
    gateway.request("/v1/sessions", {"session_id": "other", "profile": "jaeger"})
    gateway.request("/v1/sessions/other/turns", {
        "text": "Say CONTRACT-ANSWER", "request_id": "default-model-request",
    })
    default = gateway.wait_for_terminal("other", "default-model-request")
    assert default["status"] == "completed", default
    assert default["result"]["model"] == "openai:contract-model"
    calls = [json.loads(line) for line in (gateway.root / "provider-calls.jsonl").read_text().splitlines()]
    assert calls == [{"model": name} for name in (
        "contract-alternate", "contract-alternate", "contract-model",
    )]
    assert config_path.read_bytes() == config_before


def test_owned_browser_multiturn_render_cancel_and_reload(tmp_path):
    """Real Chromium composer/DOM against owned servers; only model is scripted."""
    playwright = pytest.importorskip("playwright.sync_api")
    stack = OwnedGateway(tmp_path, webui=True)
    try:
        stack.start()
        with playwright.sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            context = browser.new_context(viewport={"width": 1280, "height": 900})
            # An owned browser must not visit external URLs or operator listeners.
            context.route("**/*", lambda route: route.continue_()
                          if route.request.url.startswith(stack.webui_url + "/") else route.abort())
            login = context.request.post(stack.webui_url + "/api/auth/login", data={
                "password": "synthetic-contract-password",
            })
            assert login.ok
            page = context.new_page()
            page_errors = []
            page.on("pageerror", lambda error: page_errors.append(error.stack or str(error)))
            try:
                page.goto(stack.webui_url + "/", wait_until="domcontentloaded")
                composer = page.locator("#msg")
                playwright.expect(composer).to_be_visible(timeout=20000)
                # Fresh-profile setup is a real modal; dismiss via its visible
                # control, never force clicks through it or alter DOM/state.
                skip_setup = page.locator("#onboardingSkipBtn")
                playwright.expect(skip_setup).to_be_visible(timeout=15000)
                skip_setup.click()
                playwright.expect(page.locator("#onboardingOverlay")).to_be_hidden()
                send = page.locator("#btnSend")

                def submit(text, expected):
                    composer.fill(text)
                    playwright.expect(send).to_have_attribute("data-action", "send", timeout=10000)
                    send.click()
                    answer = page.locator('#messages [data-role="assistant"]').last
                    playwright.expect(answer).to_contain_text(expected, timeout=20000)
                    playwright.expect(send).to_have_attribute("data-action", "disabled", timeout=20000)
                    playwright.expect(page.locator("#ctxIndicator")).to_have_attribute("aria-label", "Usage not measured")

                for number in range(1, 21):
                    marker = f"BROWSER-TURN-{number:02d}"
                    submit(f"Say {marker}", marker)
                submit("CONTRACT-LONG", "End of long-form diagnostic response.")
                playwright.expect(page.locator('#messages [data-role="assistant"]').last.locator("pre")).to_be_visible()
                composer.fill("CONTRACT-WAIT")
                send.click()
                playwright.expect(send).to_have_attribute("data-action", "stop", timeout=20000)
                send.click()
                playwright.expect(send).to_have_attribute("data-action", "disabled", timeout=20000)
                submit("Say BROWSER-AFTER-CANCEL", "BROWSER-AFTER-CANCEL")
                page.reload(wait_until="domcontentloaded")
                playwright.expect(page.locator("#messages")).to_contain_text("BROWSER-AFTER-CANCEL", timeout=20000)
                # Reload may intentionally render a bounded tail; the most
                # recent turns must remain visible without a fake new session.
                playwright.expect(page.locator("#messages")).to_contain_text("BROWSER-TURN-20")
                for extension in ("ares-finance", "ares-creator", "ares-minecraft", "ares-worldview"):
                    dashboard = context.request.get(f"{stack.webui_url}/extensions/{extension}/dashboard/index.html")
                    assert dashboard.ok, extension
                    assert 'src="app.js"' in dashboard.text()
                assert not page_errors, page_errors
                page.screenshot(path=str(tmp_path / "browser-success.png"), full_page=True)
                page.set_viewport_size({"width": 390, "height": 844})
                submit("Say BROWSER-NARROW-WINDOW", "BROWSER-NARROW-WINDOW")
                playwright.expect(page.locator("#ctx-num")).to_have_text("?")
                bounds = composer.bounding_box()
                assert bounds and bounds["x"] >= 0 and bounds["x"] + bounds["width"] <= 391
                assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")
                assert not page_errors, page_errors
                page.screenshot(path=str(tmp_path / "browser-narrow.png"), full_page=True)
            except Exception:
                (tmp_path / "browser-errors.json").write_text(json.dumps(page_errors, indent=2))
                page.screenshot(path=str(tmp_path / "browser-failure.png"), full_page=True)
                raise
            finally:
                browser.close()
    finally:
        stack.stop()


def test_attachment_metadata_persists_and_rejects_workspace_escape(gateway):
    gateway.request("/v1/sessions", {"session_id": "files", "profile": "jaeger"})
    workspace = gateway.root / "instances/contract/workspace"
    payload = workspace / "attachment.txt"
    payload.write_text("ATTACHMENT-TOKEN", encoding="utf-8")
    record = {
        "safe_path": str(payload), "original_filename": payload.name,
        "mime_type": "text/plain", "size_bytes": 9999, "sha256": "untrusted-client-value",
    }
    status, attachment = gateway.request("/v1/sessions/files/attachments", record)
    assert status == 201
    assert attachment["safe_path"] == str(payload)
    assert attachment["size_bytes"] == payload.stat().st_size
    assert attachment["sha256"] == hashlib.sha256(payload.read_bytes()).hexdigest()
    for invalid in (workspace / "missing.txt", workspace):
        with pytest.raises(HTTPError) as rejected:
            gateway.request("/v1/sessions/files/attachments", {**record, "safe_path": str(invalid)})
        assert rejected.value.code == 400
    outside = gateway.root / "outside.txt"
    outside.write_text("must not attach", encoding="utf-8")
    alias = workspace / "escape.txt"
    alias.symlink_to(outside)
    for path in (outside, alias):
        with pytest.raises(HTTPError) as rejected:
            gateway.request("/v1/sessions/files/attachments", {**record, "safe_path": str(path)})
        assert rejected.value.code == 400
        assert json.load(rejected.value) == {"error": "attachment path escapes workspace"}
    before = gateway.request("/v1/sessions/files/attachments")[1]
    assert before["attachments"] == [attachment]
    gateway.stop()
    gateway.start()
    assert gateway.request("/v1/sessions/files/attachments")[1] == before
    assert payload.read_text(encoding="utf-8") == "ATTACHMENT-TOKEN"


# ── R02/C01: the bridge as a translating client of the Gateway ─────────


class OwnedBridge:
    """A real ``jaeger_ai.interfaces.bridge`` process in Gateway execution
    mode, speaking NDJSON to this test over its stdio pipes."""

    def __init__(self, state, gateway_url, extra_args=()):
        self.state = state
        instance = state / "instances" / "contract"
        _complete_instance(instance)
        environment = {
            **os.environ, "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONPATH": os.pathsep.join([
                str(REPO), str(REPO / "packages/jaeger-agent"), str(REPO / "packages/jaeger-os"),
            ]),
            "JAEGER_STATE_DIR": str(state), "JAEGER_HOME": str(state),
            "JAEGER_INSTANCE_DIR": str(instance),
            "JAEGER_BRIDGE_EXECUTION": "gateway", "JAEGER_GATEWAY_URL": gateway_url,
            "JAEGER_NO_ATTACH": "1", "JAEGER_NO_GUI": "1",
        }
        self.process = subprocess.Popen(
            [sys.executable, "-m", "jaeger_ai.interfaces.bridge", "contract", *extra_args],
            cwd=state, env=environment, text=True,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=(state / "bridge.log").open("a", encoding="utf-8"),
        )
        self.frames = []

    def send(self, obj):
        self.process.stdin.write(json.dumps(obj) + "\n")
        self.process.stdin.flush()

    def until(self, predicate, timeout=20):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            line = self.process.stdout.readline()
            if not line:
                break
            frame = json.loads(line)
            self.frames.append(frame)
            if predicate(frame):
                return frame
        raise AssertionError(f"no matching frame; saw {self.frames}\n"
                             + (self.state / "bridge.log").read_text())

    def stop(self):
        if self.process.poll() is None:
            self.process.kill()
            self.process.wait(timeout=5)


def _complete_instance(instance):
    """identity.yaml + manifest.json beside the worker's config.yaml, so the
    bridge treats the instance as set up (it never boots an agent here)."""
    from jaeger_ai.core.instance.schemas import Identity, Manifest, dump_json, dump_yaml

    if not (instance / "identity.yaml").exists():
        dump_yaml(instance / "identity.yaml", Identity(
            name="Contract", role="contract test entity", personality="terse"))
    if not (instance / "manifest.json").exists():
        dump_json(instance / "manifest.json", Manifest(instance_name="contract"))


@pytest.fixture
def bridge(gateway):
    owned = OwnedBridge(gateway.root, gateway.url)
    try:
        yield owned
    finally:
        owned.stop()


def _provider_calls(gateway):
    path = gateway.root / "provider-calls.jsonl"
    return path.read_text().splitlines() if path.exists() else []


def test_bridge_chat_is_executed_by_the_gateway_not_locally(gateway, bridge):
    from jaeger_ai.core.instance.instance import InstanceLayout, InstanceLock

    state = bridge.until(lambda f: f.get("type") == "agent_state")
    assert state["state"] == "ready", state.get("error")
    bridge.send({"op": "send", "text": "Say CONTRACT-ANSWER",
                 "session": "bridge-chat", "turn_id": "bridge-turn-1"})
    reply = bridge.until(lambda f: f.get("type") == "reply")

    assert reply["text"] == "CONTRACT-ANSWER", reply
    assert reply.get("error") is None
    streamed = "".join(f["text"] for f in bridge.frames if f.get("type") == "delta")
    assert streamed == "CONTRACT-ANSWER"
    _, row = gateway.request("/v1/sessions/bridge-chat/requests/bridge-turn-1")
    assert row["status"] == "completed" and row["result"]["backend"] == "owner-react"
    assert len(_provider_calls(gateway)) == 1, "exactly one execution, in the Gateway"
    # The bridge booted no agent, so it holds no instance lock.
    lock = InstanceLock(InstanceLayout(gateway.root / "instances" / "contract"))
    lock.acquire()
    lock.release()

    # Swift's History reads through the bridge; it must show this exchange.
    bridge.send({"op": "query", "id": "h1", "what": "load_session",
                 "args": {"id": "bridge-chat", "resume": False}})
    history = bridge.until(lambda f: f.get("type") == "result" and f.get("id") == "h1")
    texts = [(m.get("role"), m.get("text")) for m in (history.get("data") or [])]
    assert ("user", "Say CONTRACT-ANSWER") in texts and ("assistant", "CONTRACT-ANSWER") in texts, history
    bridge.send({"op": "query", "id": "h2", "what": "list_sessions", "args": {}})
    listing = bridge.until(lambda f: f.get("type") == "result" and f.get("id") == "h2")
    assert any(row["id"] == "bridge-chat" and row["messages"] >= 2 for row in listing["data"]), listing


@pytest.mark.parametrize("answer", ["once", "deny"])
def test_bridge_relays_gateway_approvals(gateway, bridge, answer):
    target = gateway.root / "instances/contract/workspace/contract-output.txt"
    bridge.until(lambda f: f.get("type") == "agent_state")
    bridge.send({"op": "send", "text": "CONTRACT-WRITE: write the test file",
                 "session": "bridge-approval", "turn_id": "bridge-turn-2"})
    request = bridge.until(lambda f: f.get("type") == "request")
    assert request["kind"] == "approval" and "once" in request["options"]
    assert not target.exists()

    bridge.send({"op": "respond", "id": request["id"], "answer": answer})
    bridge.until(lambda f: f.get("type") == "reply")

    if answer == "once":
        assert target.read_text(encoding="utf-8") == "CONTRACT-CONTENT"
    else:
        assert not target.exists()
    assert gateway.request("/v1/approvals")[1]["approvals"] == []


def test_bridge_always_answer_is_one_grant_shared_with_every_client(gateway, bridge):
    """"always" through the bridge persists the same per-skill grant the
    bridge used to write locally; the Gateway then honours it without asking."""
    target = gateway.root / "instances/contract/workspace/contract-output.txt"
    bridge.until(lambda f: f.get("type") == "agent_state")
    bridge.send({"op": "send", "text": "CONTRACT-WRITE: first", "session": "grant",
                 "turn_id": "grant-1"})
    request = bridge.until(lambda f: f.get("type") == "request")
    bridge.send({"op": "respond", "id": request["id"], "answer": "always"})
    bridge.until(lambda f: f.get("type") == "reply")
    assert target.read_text(encoding="utf-8") == "CONTRACT-CONTENT"
    grants = json.loads((gateway.root / "instances/contract/permissions.json").read_text())
    assert grants["granted_skills"], grants

    target.unlink()
    asked = len([f for f in bridge.frames if f.get("type") == "request"])
    bridge.send({"op": "send", "text": "CONTRACT-WRITE: second", "session": "grant",
                 "turn_id": "grant-2"})
    bridge.until(lambda f: f.get("type") == "reply")
    assert target.read_text(encoding="utf-8") == "CONTRACT-CONTENT"
    assert len([f for f in bridge.frames if f.get("type") == "request"]) == asked, "no second prompt"


def test_bridge_files_dispatcher_focus_reports_for_gateway_turns(gateway, bridge):
    import sqlite3

    from jaeger_ai.core.instance.instance import InstanceLayout
    from jaeger_ai.features.dispatcher.store import DispatcherStore

    store = DispatcherStore(InstanceLayout(gateway.root / "instances" / "contract"))
    session = store.route("focus-card", "Say CONTRACT-ANSWER")
    bridge.until(lambda f: f.get("type") == "agent_state")
    bridge.send({"op": "send", "text": "Say CONTRACT-ANSWER", "session": session,
                 "turn_id": "focus-turn-1"})
    reply = bridge.until(lambda f: f.get("type") == "reply")
    assert reply["text"] == "CONTRACT-ANSWER"
    with store.connect() as db:
        db.row_factory = sqlite3.Row
        row = db.execute("SELECT * FROM reports WHERE run_id='focus-turn-1'").fetchone()
    assert row is not None and row["status"] == "completed" and row["session"] == session


def test_gateway_owner_refires_a_stalled_turn(gateway):
    gateway.request("/v1/sessions", {
        "session_id": "stall", "title": "stall", "profile": "jaeger", "source": "test",
    })
    _, receipt = gateway.request("/v1/sessions/stall/turns", {
        "text": "Say CONTRACT-STALL then finish", "request_id": "stall-1",
    })
    row = gateway.wait_for_terminal("stall", "stall-1")
    assert row["status"] == "completed", row
    assert "CONTRACT-ANSWER" in row["result"]["output"]
    calls = (gateway.root / "provider-calls.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(calls) == 2, calls


def test_bridge_display_text_is_what_gateway_history_shows(gateway, bridge):
    bridge.until(lambda f: f.get("type") == "agent_state")
    bridge.send({"op": "send", "text": "Say CONTRACT-ANSWER",
                 "display_text": "visible question", "session": "shown",
                 "turn_id": "shown-1"})
    reply = bridge.until(lambda f: f.get("type") == "reply")
    assert reply["text"] == "CONTRACT-ANSWER"
    _, session = gateway.request("/v1/sessions/shown")
    user = [m for m in session["messages"] if m["role"] == "user"]
    assert user[0]["content"] == "visible question"
    _, row = gateway.request("/v1/sessions/shown/requests/shown-1")
    assert row["input_text"] == "Say CONTRACT-ANSWER"
    assert row["execution"]["display_text"] == "visible question"


def test_bridge_empty_attachment_ids_do_not_become_unrestricted(gateway, bridge):
    bridge.until(lambda f: f.get("type") == "agent_state")
    bridge.send({"op": "send", "text": "Say CONTRACT-ANSWER", "session": "atts",
                 "turn_id": "atts-1", "attachment_ids": []})
    bridge.until(lambda f: f.get("type") == "reply")
    _, row = gateway.request("/v1/sessions/atts/requests/atts-1")
    assert row["execution"]["attachments"] == []


def test_bridge_is_subordinate_is_snapshotted_and_replays(gateway, bridge):
    bridge.until(lambda f: f.get("type") == "agent_state")
    bridge.send({"op": "send", "text": "Say CONTRACT-ANSWER", "session": "sub",
                 "turn_id": "sub-1", "is_subordinate": True})
    reply = bridge.until(lambda f: f.get("type") == "reply")
    assert reply["text"] == "CONTRACT-ANSWER"
    _, row = gateway.request("/v1/sessions/sub/requests/sub-1")
    assert row["execution"]["is_subordinate"] is True
    with pytest.raises(HTTPError) as conflict:
        gateway.request("/v1/sessions/sub/turns", {
            "text": "Say CONTRACT-ANSWER", "request_id": "sub-1",
        })
    assert conflict.value.code == 409
    _, replay = gateway.request("/v1/sessions/sub/turns", {
        "text": "Say CONTRACT-ANSWER", "request_id": "sub-1", "is_subordinate": True,
    })
    assert replay.get("replayed") is True


def test_bridge_tool_grant_is_enforced_by_the_gateway_owner(gateway, bridge):
    """allowed_tools=[] (a dispatcher worker's grant) must not widen to the
    full catalog when the Gateway executes the turn."""
    target = gateway.root / "instances/contract/workspace/contract-output.txt"
    bridge.until(lambda f: f.get("type") == "agent_state")
    bridge.send({"op": "send", "text": "CONTRACT-WRITE: try anyway", "session": "granted",
                 "turn_id": "grant-none", "allowed_tools": []})
    bridge.until(lambda f: f.get("type") == "reply")
    assert not target.exists()
    assert not any(f.get("type") == "request" for f in bridge.frames), "never even asked"
    _, row = gateway.request("/v1/sessions/granted/requests/grant-none")
    assert row["execution"]["allowed_tools"] == []


def test_bridge_cancel_reaches_the_gateway_owned_turn(gateway, bridge):
    bridge.until(lambda f: f.get("type") == "agent_state")
    bridge.send({"op": "send", "text": "Say CONTRACT-WAIT",
                 "session": "bridge-cancel", "turn_id": "bridge-turn-3"})
    deadline = time.monotonic() + 10
    while not (gateway.root / "provider-waiting").exists():
        assert time.monotonic() < deadline, (gateway.root / "gateway.log").read_text()
        time.sleep(0.05)

    bridge.send({"op": "cancel", "turn_id": "bridge-turn-3"})
    reply = bridge.until(lambda f: f.get("type") == "reply")

    assert reply.get("cancelled") is True, reply
    _, row = gateway.request("/v1/sessions/bridge-cancel/requests/bridge-turn-3")
    assert row["status"] == "cancelled"
    assert not (gateway.root / "provider-release").exists()


def test_bridge_never_falls_back_to_a_local_agent_when_the_gateway_is_down(tmp_path):
    state = tmp_path
    (state / "instances" / "contract").mkdir(parents=True)
    from jaeger_ai.core.instance.schemas import Config, ExternalModelConfig, ModelConfig, dump_yaml

    dump_yaml(state / "instances/contract/config.yaml", Config(
        instance_name="contract", model=ModelConfig(model_path="/dev/null"),
        external_model=ExternalModelConfig(enabled=True, provider="openai",
                                           model="contract-model", base_url="http://127.0.0.1:9/v1"),
    ))
    with socket.socket() as probe:           # a port nothing listens on
        probe.bind(("127.0.0.1", 0))
        dead = f"http://127.0.0.1:{probe.getsockname()[1]}"
    owned = OwnedBridge(state, dead)
    try:
        state_frame = owned.until(lambda f: f.get("type") == "agent_state")
        assert state_frame["state"] == "failed"
        assert "Gateway unavailable" in state_frame["error"]
        fatal = owned.until(lambda f: f.get("type") == "fatal")
        assert fatal["kind"] == "gateway"
        bye = owned.until(lambda f: f.get("type") == "bye")
        assert bye["reason"] == "quit"
        owned.process.wait(timeout=5)
        assert owned.process.returncode != 0
        assert not any(f.get("type") == "delta" for f in owned.frames)
    finally:
        owned.stop()


@pytest.fixture
def short_gateway():
    """An owned Gateway rooted under /tmp: macOS caps AF_UNIX paths near 104
    bytes, and pytest's tmp_path is too long for <instance>/run/bridge.sock."""
    import shutil
    import tempfile

    root = Path(tempfile.mkdtemp(prefix="jgw", dir="/tmp"))
    owned = OwnedGateway(root)
    try:
        owned.start()
        yield owned
    finally:
        owned.stop()
        shutil.rmtree(root, ignore_errors=True)


def test_attached_client_turns_also_go_through_the_gateway(short_gateway):
    gateway = short_gateway
    owner = OwnedBridge(gateway.root, gateway.url)
    attached = None
    try:
        assert owner.until(lambda f: f.get("type") == "agent_state")["state"] == "ready"
        sock = gateway.root / "instances/contract/run/bridge.sock"
        deadline = time.monotonic() + 10
        while not sock.exists():
            assert time.monotonic() < deadline, (gateway.root / "bridge.log").read_text()
            time.sleep(0.05)
        attached = OwnedBridge(gateway.root, gateway.url, extra_args=["--attach"])
        attached.send({"op": "send", "text": "Say CONTRACT-ANSWER", "session": "attached",
                       "turn_id": "attached-1"})
        reply = attached.until(lambda f: f.get("type") == "reply")
        assert reply["text"] == "CONTRACT-ANSWER", reply
        _, row = gateway.request("/v1/sessions/attached/requests/attached-1")
        assert row["status"] == "completed" and row["result"]["backend"] == "owner-react"
    finally:
        if attached is not None:
            attached.stop()
        owner.stop()


def _contract_layout(gateway):
    from jaeger_ai.core.instance.instance import InstanceLayout
    return InstanceLayout(gateway.root / "instances" / "contract")


def test_gateway_owns_the_producer_lease(gateway, monkeypatch):
    from jaeger_ai.core.runtime.background_producers import BackgroundProducers, other_holder_pid

    monkeypatch.setenv("JAEGER_BACKGROUND_PRODUCERS", "1")
    layout = _contract_layout(gateway)
    assert other_holder_pid(layout) == gateway.process.pid
    status = json.loads((layout.run_dir / "background_producers.json").read_text())
    assert status["pid"] == gateway.process.pid and status["cron"] is True
    second = BackgroundProducers(layout, type("S", (), {
        "is_busy": lambda self: False,
        "last_user_quiet_s": lambda self: 0.0,
        "last_user_session": lambda self: "desktop-app",
        "submit_turn": lambda *a, **k: {"text": "nope"},
    })())
    assert second.try_start() is False


def test_gateway_cron_fire_is_one_durable_turn(gateway):
    from datetime import datetime, timedelta

    from jaeger_agent.memory import memory as mem
    from jaeger_agent.memory import sqlite_store

    layout = _contract_layout(gateway)
    sqlite_store.bind(layout)
    try:
        when = (datetime.now().astimezone() - timedelta(seconds=2)).isoformat()
        mem.add_schedule("", "Say CONTRACT-ANSWER", name="once", at=when)
    finally:
        sqlite_store.close()

    deadline = time.monotonic() + 15
    session = None
    while time.monotonic() < deadline:
        try:
            _, session = gateway.request("/v1/sessions/cron:once")
        except HTTPError:
            session = None
        if session and any(m.get("role") == "assistant" for m in session.get("messages") or []):
            break
        time.sleep(0.1)
    assert session is not None, (gateway.root / "gateway.log").read_text()
    texts = [m.get("content") for m in session["messages"] if m.get("role") == "assistant"]
    assert any("CONTRACT-ANSWER" in (t or "") for t in texts), session
    assert len(_provider_calls(gateway)) >= 1


def test_gateway_webhook_turn_replays_duplicate_delivery(gateway):
    layout = _contract_layout(gateway)
    deadline = time.monotonic() + 10
    status_path = layout.run_dir / "background_producers.json"
    while time.monotonic() < deadline:
        if status_path.is_file():
            port = json.loads(status_path.read_text()).get("webhook_port")
            if port:
                break
        time.sleep(0.05)
    else:
        raise AssertionError((gateway.root / "gateway.log").read_text())

    body = json.dumps({
        "action": "turn", "prompt": "Say CONTRACT-ANSWER", "delivery_id": "wh-owned",
    }).encode()
    before = len(_provider_calls(gateway))
    payloads = []
    for _ in range(2):
        req = Request(
            f"http://127.0.0.1:{port}/hook", data=body,
            headers={"Content-Type": "application/json"}, method="POST",
        )
        with urlopen(req, timeout=20) as resp:
            payloads.append(json.load(resp))
    assert payloads[0]["fired"] == "turn"
    assert payloads[0]["request_id"] == "webhook:wh-owned"
    assert payloads[1]["replayed"] is True
    _, row = gateway.request("/v1/sessions/webhook/requests/webhook:wh-owned")
    assert row["status"] == "completed"
    assert "CONTRACT-ANSWER" in (row["result"].get("output") or "")
    assert len(_provider_calls(gateway)) == before + 1


def test_create_runtime_submits_to_the_owned_gateway(gateway, monkeypatch):
    """Mind/window factory uses this process's Gateway, not a local boot."""
    from jaeger_ai.core.mind_runtime import create_runtime

    previous_attach = os.environ.pop("JAEGER_NO_ATTACH", None)
    previous_url = os.environ.get("JAEGER_GATEWAY_URL")
    os.environ["JAEGER_GATEWAY_URL"] = gateway.url
    monkeypatch.setattr(
        "jaeger_ai.core.mind_runtime.JaegerAIRuntime",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("local boot")),
    )
    runtime = None
    try:
        runtime = create_runtime(bus=object(), config={"instance_name": "contract"})
        assert getattr(runtime, "gateway", False) is True
        result = runtime.run_turn("Say CONTRACT-ANSWER", session_key="mind-gui")
        assert result["text"] == "CONTRACT-ANSWER", result
        _, row = gateway.request("/v1/sessions/mind-gui")
        assert any(m.get("role") == "assistant" for m in row.get("messages") or [])
    finally:
        if runtime is not None:
            runtime.close()
        if previous_attach is None:
            os.environ.pop("JAEGER_NO_ATTACH", None)
        else:
            os.environ["JAEGER_NO_ATTACH"] = previous_attach
        if previous_url is None:
            os.environ.pop("JAEGER_GATEWAY_URL", None)
        else:
            os.environ["JAEGER_GATEWAY_URL"] = previous_url


def test_gateway_mode_bridge_does_not_take_the_producer_lease(gateway, bridge):
    from jaeger_ai.core.runtime.background_producers import other_holder_pid

    bridge.until(lambda f: f.get("type") == "agent_state")
    layout = _contract_layout(gateway)
    assert other_holder_pid(layout) == gateway.process.pid
