"""Gateway model callsites send the admitted user turn exactly once."""

from __future__ import annotations

import json as std_json

import pytest

from jaeger_ai.core.entity.runtime import EntityRuntime
from jaeger_ai.core.gateway.server import JaegerGatewayApp
from jaeger_ai.core.gateway.session_store import GatewaySessionStore


@pytest.mark.asyncio
@pytest.mark.parametrize("lane", ["model", "delegate", "vision"])
async def test_gateway_model_callsite_removes_only_current_admitted_row(
    lane,
    monkeypatch,
    tmp_path,
):
    current_text = (
        "What is shown in this image?"
        if lane == "vision"
        else "Explain the repeated request."
    )
    prompt = {
        "model": (
            "<background>read-only context</background>\n\n"
            f"Current request — act on this and nothing else:\n{current_text}"
        ),
        "delegate": f"Delegate this request to Ops: {current_text}",
        "vision": current_text,
    }[lane]

    store = GatewaySessionStore(tmp_path / f"{lane}.sqlite3")
    app = JaegerGatewayApp(store=store)
    store.ensure_session("s")
    # The earlier user turn is intentionally byte-for-byte identical to the
    # current one. Only the final row admitted below may be removed.
    store.append_message("s", "user", current_text, timestamp=10.0)
    store.append_message("s", "assistant", "Earlier answer.", timestamp=11.0)

    requested = None
    image_bytes = None
    if lane == "vision":
        image = tmp_path / "panel.png"
        image_bytes = b"synthetic-image"
        image.write_bytes(image_bytes)
        attachment = store.add_attachment("s", {
            "attachment_id": "att_image",
            "safe_path": str(image),
            "original_filename": "panel.png",
            "mime_type": "image/png",
            "size_bytes": len(image_bytes),
        })
        requested = {"attachment_ids": [attachment["attachment_id"]]}

    admitted = store.admit_request(
        "s",
        current_text,
        request_id=f"request-{lane}",
        requested=requested,
    )
    captured: list[dict] = []

    class Response:
        status = 200

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def text(self):
            return '{"message":{"content":"MODEL-OK"}}'

    class Session:
        def __init__(self, *_args, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        def post(self, _url, *, json, headers=None):
            del headers
            captured.append(std_json.loads(std_json.dumps(json)))
            return Response()

    class Runtime:
        def execute_turn(self, text, *, context, **_kwargs):
            if lane == "vision":
                assert text.startswith(current_text)
            else:
                assert text == current_text
            if lane == "model":
                answer = context["model_runner"](prompt)
                return {"text": answer}
            if lane == "delegate":
                return context["delegate_runner"]("ops", prompt)
            return dict(context["react_runner"](prompt))

    monkeypatch.setattr("jaeger_ai.core.gateway.server.ClientSession", Session)
    monkeypatch.setattr(app, "_resolve_session_agent", lambda _sid: None)
    monkeypatch.setattr(app, "_system_prompt_for_agent", lambda _agent: "SYSTEM")
    monkeypatch.setattr(
        EntityRuntime,
        "get_singleton",
        classmethod(lambda cls, *_args, **_kwargs: Runtime()),
    )

    await app._execute_turn(
        "s",
        admitted["turn_id"],
        current_text,
        request_id=admitted["request_id"],
        execution=admitted["execution"],
    )

    assert len(captured) == 1
    expected_current = {"role": "user", "content": prompt}
    if image_bytes is not None:
        import base64

        expected_current["images"] = [base64.b64encode(image_bytes).decode("utf-8")]
    assert captured[0]["messages"] == [
        {"role": "system", "content": "SYSTEM"},
        {"role": "user", "content": current_text},
        {"role": "assistant", "content": "Earlier answer."},
        expected_current,
    ]
    # Two equal strings are intentional: one historical turn and one current
    # prompt. A third would be the duplicate admitted tail-row regression.
    if prompt == current_text:
        assert sum(
            row.get("content") == current_text
            for row in captured[0]["messages"]
        ) == 2
    else:
        assert prompt.count(current_text) == 1


def test_history_projection_does_not_drop_an_unadmitted_tail(tmp_path):
    app = JaegerGatewayApp(
        store=GatewaySessionStore(tmp_path / "unadmitted.sqlite3"),
    )
    session = {
        "messages": [
            {"role": "user", "content": "same", "timestamp": 1.0},
            {"role": "assistant", "content": "answer", "timestamp": 2.0},
            {"role": "user", "content": "same", "timestamp": 3.0},
        ],
    }

    assert app._history_before_admitted_user(session, None) == session["messages"]
