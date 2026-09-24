"""Exercise the actual WebUI adapter without sockets, providers, or saved state."""

import io
import json
import threading
from types import SimpleNamespace

import pytest
from api import gateway_chat, jaeger_gateway_routes, models, streaming


@pytest.fixture
def adapter(monkeypatch):
    requests = []
    events = []
    publications = []
    upload_reply = {"attachment_id": "uploaded-file"}
    stream = SimpleNamespace(body=b'event: turn.delta\ndata: {"delta":"partial reply","request_id":"request"}\n\n')

    def open_request(request, **_kwargs):
        requests.append(request)
        if request.full_url.endswith("/attachments"):
            return io.BytesIO(json.dumps(upload_reply).encode())
        if "/stream" in request.full_url:
            return io.BytesIO(stream.body)
        return io.BytesIO(b'{"start_event_id": 1}')

    monkeypatch.setattr(gateway_chat.urllib.request, "urlopen", open_request)
    monkeypatch.setattr(gateway_chat, "_publish_gateway_run_id", lambda *_: publications.append(
        requests[-1].full_url if requests else "before any request"
    ))
    monkeypatch.setattr(jaeger_gateway_routes, "remember", lambda *_: None)
    monkeypatch.setattr(gateway_chat, "update_active_run", lambda *_, **__: None)
    monkeypatch.setattr(gateway_chat, "STREAM_PARTIAL_TEXT", {})
    monkeypatch.setattr(gateway_chat, "STREAM_LIVE_TOOL_CALLS", {})
    monkeypatch.setattr(models, "SESSIONS", {})
    monkeypatch.setattr(streaming, "_session_payload_with_full_messages", lambda session, **kwargs: {
        "session_id": session.session_id, **kwargs,
    })
    monkeypatch.setattr(gateway_chat, "_iter_sse_lines_cancellable", lambda response, _: iter(response))

    def run(attachments=None):
        result = gateway_chat._run_jaeger_gateway_streaming(
            "session", "question", "test-model", "/isolated/workspace", "request",
            "http://gateway.invalid", "", attachments=attachments,
            model_provider="test-provider", options={"reasoning_effort": "high"},
            put_gateway_event=lambda event, data: events.append((event, data)),
            cancel_event=threading.Event(), session=SimpleNamespace(
                profile="test", session_id="session", messages=[], save=lambda: None,
            ),
        )
        return result

    return SimpleNamespace(run=run, requests=requests, events=events,
                           publications=publications, upload_reply=upload_reply, stream=stream)


@pytest.mark.parametrize("attachment", ["invalid", {}, {"name": "missing-path.txt"}])
def test_invalid_attachment_stops_before_turn_admission(adapter, attachment):
    adapter.run([attachment])
    assert not any(request.full_url.endswith("/turns") for request in adapter.requests)
    assert adapter.events[-1][0] == "apperror"
    assert adapter.events[-1][1]["type"] == "attachment_error"
    assert not adapter.publications


def test_upload_without_id_stops_before_turn_admission(adapter):
    adapter.upload_reply.clear()
    adapter.run([{"path": "/isolated/workspace/file.txt"}])
    assert not any(request.full_url.endswith("/turns") for request in adapter.requests)
    assert adapter.events[-1][1]["type"] == "attachment_error"


@pytest.mark.parametrize("attachments,expected", [(None, []), ([{"attachment_id": "existing"}], ["existing"]), ([{"path": "/isolated/workspace/file.txt"}], ["uploaded-file"])])
def test_admission_preserves_attachment_scope_and_model_options(adapter, attachments, expected):
    adapter.run(attachments)
    request = next(request for request in adapter.requests if request.full_url.endswith("/turns"))
    body = json.loads(request.data)
    assert body["attachment_ids"] == expected
    assert body["model"] == "test-model"
    assert body["provider"] == "test-provider"
    assert body["options"] == {"reasoning_effort": "high"}
    assert adapter.publications == ["http://gateway.invalid/v1/sessions/session/turns"]


def test_partial_stream_eof_is_not_success(adapter):
    text, _usage = adapter.run()
    assert text == "partial reply"
    assert adapter.events[0] == ("token", {"text": "partial reply"})
    assert adapter.events[-1][0] == "apperror"
    assert adapter.events[-1][1]["type"] == "gateway_stream_error"
    assert not any(event in {"done", "finish"} for event, _ in adapter.events)


@pytest.mark.parametrize("raw,expected", [
    (None, {"input_tokens": None, "output_tokens": None, "estimated_cost": None, "measured": False}),
    ({"prompt_tokens": 0, "completion_tokens": 0, "estimated_cost": 0},
     {"input_tokens": 0, "output_tokens": 0, "estimated_cost": 0, "measured": True}),
    ({"prompt_tokens": 7, "completion_tokens": 3},
     {"input_tokens": 7, "output_tokens": 3, "estimated_cost": None, "measured": True}),
])
def test_terminal_usage_distinguishes_missing_measurements_from_zero(adapter, raw, expected):
    adapter.stream.body += b"event: turn.finish\ndata: " + json.dumps({"usage": raw}).encode() + b"\n\n"
    _text, usage = adapter.run()
    assert usage == expected
    done = next(data for event, data in adapter.events if event == "done")
    assert done["usage"] == expected


def test_checkpoints_and_tool_activity_do_not_pollute_final_answer(adapter):
    packets = [
        ('turn.delta', {'delta': 'Inspecting.'}),
        ('turn.progress', {}),
        ('tool.started', {'tool': 'read_file', 'activity_id': 't'}),
        ('tool.completed', {'tool': 'read_file', 'activity_id': 't'}),
        ('turn.delta', {'delta': 'Checkpoint.'}),
        ('turn.checkpoint', {'text': 'Checkpoint.'}),
        ('turn.delta', {'delta': 'Final partial'}),
        ('turn.finish', {'output': 'Implemented and verified.'}),
    ]
    adapter.stream.body = b''.join(
        f'event: {name}\ndata: {json.dumps({**data, "request_id": "request"})}\n\n'.encode()
        for name, data in packets
    )
    text, _ = adapter.run()
    assert text == 'Implemented and verified.'
    assert [e for e, _ in adapter.events] == [
        'token', 'interim_assistant', 'tool', 'tool_complete',
        'token', 'interim_assistant', 'token', 'done', 'stream_end',
    ]
    completed = next(data for event, data in adapter.events if event == 'tool_complete')
    assert completed['tid'] == 't'
    assert completed['done'] is True
    assert completed['event_type'] == 'tool.completed'
    assert gateway_chat.STREAM_LIVE_TOOL_CALLS['request'] == [completed]
    done = next(data for event, data in adapter.events if event == 'done')
    assert done['session']['tool_calls'][0]['done'] is True
    assert done['session']['tool_calls'][0]['assistant_msg_idx'] == 1
