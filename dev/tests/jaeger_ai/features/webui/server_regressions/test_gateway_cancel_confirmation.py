"""A cancel acknowledgement is not a durable terminal outcome."""

import io
import json
from types import SimpleNamespace

import pytest
from api import config, gateway_chat, jaeger_gateway_routes


@pytest.fixture
def stop(monkeypatch):
    requests = []
    replies = []
    clock = iter(range(0, 100, 2))
    monkeypatch.setattr(gateway_chat, "time", SimpleNamespace(
        monotonic=lambda: next(clock), sleep=lambda _: None,
    ))
    monkeypatch.setattr(config, "get_config", dict)
    monkeypatch.setattr(config, "stream_owner_session_id", lambda _: "session")
    monkeypatch.setattr(jaeger_gateway_routes, "lookup", lambda _: ("http://gateway.invalid", ""))
    monkeypatch.setattr(gateway_chat, "_gateway_api_key", lambda: "")
    monkeypatch.setattr(gateway_chat, "_is_jaeger_gateway", lambda _: True)

    def open_request(request, **_kwargs):
        requests.append(request)
        reply = replies.pop(0) if len(replies) > 1 else replies[0]
        response = io.BytesIO(json.dumps(reply).encode())
        response.status = 200
        return response

    monkeypatch.setattr(gateway_chat.urllib.request, "urlopen", open_request)
    return requests, replies


def test_accepted_cancel_waits_for_authoritative_terminal_record(stop):
    requests, replies = stop
    replies.extend([
        {"status": "cancelling", "cancellation_confirmed": False},
        {"status": "cancelling"},
        {"status": "cancelled"},
    ])
    assert gateway_chat.stop_gateway_run("request") is True
    assert [request.method for request in requests] == ["POST", "GET", "GET"]
    assert requests[-1].full_url.endswith("/v1/sessions/session/requests/request")


@pytest.mark.parametrize("status", ["cancelling", "running", "unknown"])
def test_pending_or_unknown_outcome_does_not_confirm_stop(stop, status):
    _requests, replies = stop
    replies.append({"status": status, "cancellation_confirmed": False})
    assert gateway_chat.stop_gateway_run("request") is False


@pytest.mark.parametrize("status", ["cancelled", "completed", "failed"])
def test_already_terminal_request_needs_no_poll(stop, status):
    requests, replies = stop
    replies.append({"status": status, "already_terminal": True})
    assert gateway_chat.stop_gateway_run("request") is True
    assert len(requests) == 1
