"""A message typed during a runner-owned run is queued, not bounced.

Live regression (WebUI, 2026-09-22): the second message of a Jaeger
conversation, sent while the first turn was still finishing, went to
/api/chat/steer, got ``no_cached_agent``, and was pushed back into the
composer instead of being sent after the run.
"""

from __future__ import annotations

from types import SimpleNamespace


def test_runner_owned_run_answers_queued(monkeypatch):
    import api.config as cfg
    import api.streaming as streaming

    captured = {}
    monkeypatch.setattr("api.helpers.j", lambda _h, body, **_k: captured.update(body) or True)
    monkeypatch.setattr(streaming, "get_session", lambda _sid: SimpleNamespace(active_stream_id="run-7"))
    cfg.register_active_run("run-7", session_id="sess-1", runner=True)
    try:
        streaming._handle_chat_steer(object(), {"session_id": "sess-1", "text": "and then?"})
    finally:
        cfg.unregister_active_run("run-7")

    assert captured == {"accepted": False, "fallback": "gateway_steer_queued", "stream_id": "run-7"}


def test_no_active_run_still_reports_no_cached_agent(monkeypatch):
    import api.streaming as streaming

    captured = {}
    monkeypatch.setattr("api.helpers.j", lambda _h, body, **_k: captured.update(body) or True)
    monkeypatch.setattr(streaming, "get_session", lambda _sid: SimpleNamespace(active_stream_id=None))
    streaming._handle_chat_steer(object(), {"session_id": "sess-2", "text": "hi"})
    assert captured["fallback"] == "no_cached_agent"
