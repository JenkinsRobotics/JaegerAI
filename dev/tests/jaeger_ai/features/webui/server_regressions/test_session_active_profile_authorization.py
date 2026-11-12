"""Regression tests for session-profile visibility on request-scoped session_id uses.

The security contract is now enforced with a generic preflight for request-supplied
session IDs. These tests cover the most sensitive paths that previously loaded
foreign-profile sessions directly: duplicate, file reads, and chat/start.
"""

from __future__ import annotations

import io
import time
from urllib.parse import urlparse

import api.routes as routes
import api.upload as upload


class _FakeHandler:
    def __init__(self):
        self.status = None
        self.headers = {"Content-Type": "multipart/form-data; boundary=test", "Content-Length": "1"}
        self.rfile = io.BytesIO(b"")
        self.wfile = io.BytesIO()
        self.command = "GET"
        self.path = "/"
        self.client_address = ("127.0.0.1", 12345)

    def send_response(self, status):
        self.status = status

    def send_header(self, key, value):
        self.headers[key] = value

    def end_headers(self):
        pass


def _capture(monkeypatch):
    cap = {}

    def _j(_h, obj, *_, **__):
        cap["ok"] = obj
        return True

    def _bad(_h, msg, code=400):
        cap["bad"] = (msg, code)
        return True

    monkeypatch.setattr(routes, "j", _j)
    monkeypatch.setattr(routes, "bad", _bad)
    return cap


def _capture_upload(monkeypatch):
    cap = {}

    def _j(_h, obj, *_, **kwargs):
        cap["ok"] = obj
        cap["status"] = kwargs.get("status", 200)
        return True

    monkeypatch.setattr(upload, "j", _j)
    return cap


class _SimpleSession:
    def __init__(self, sid, profile="default", workspace="/workspace", messages=None, context_messages=None, pending_user_message=None):
        self.session_id = sid
        self.profile = profile
        self.workspace = workspace
        self.model = "test-model"
        self.model_provider = None
        self.title = "Test"
        self.messages = messages or []
        self.tool_calls = []
        self.project_id = None
        self.context_messages = context_messages
        self.pending_user_message = pending_user_message
        self.personality = None
        self.enabled_toolsets = None
        self.context_length = None
        self.threshold_tokens = None
        self.truncation_watermark = None
        self.truncation_boundary = None
        self.gateway_routing = None
        self.gateway_routing_history = []
        self.llm_title_generated = False
        self.manual_title = False
        self.composer_draft = {}
        self.context_engine = None
        self.context_engine_state = {}
        self.input_tokens = 0
        self.output_tokens = 0
        self.estimated_cost = 0.0
        self.cache_read_tokens = 0
        self.cache_write_tokens = 0


def test_session_duplicate_foreign_profile_session_blocked_by_visibility_guard(monkeypatch):
    handler = _FakeHandler()
    foreign = _SimpleSession("foreign_duplicate", profile="other")
    monkeypatch.setattr(routes, "get_session", lambda sid, metadata_only=False: foreign)
    monkeypatch.setattr(routes, "_get_active_profile_name", lambda: "default")
    monkeypatch.setattr(routes, "_check_csrf", lambda _handler: True)
    monkeypatch.setattr(routes, "read_body", lambda _handler: {"session_id": "foreign_duplicate"})
    monkeypatch.setattr(routes.Session, "load", staticmethod(lambda sid: (_ for _ in ()).throw(AssertionError("duplicate should not materialize foreign session"))))

    cap = _capture(monkeypatch)
    routes.handle_post(handler, urlparse("/api/session/duplicate"))

    assert cap["bad"] == ("Session not found", 404)


def test_session_delete_foreign_profile_blocked_before_mutation(monkeypatch):
    handler = _FakeHandler()
    foreign = _SimpleSession("foreign_delete", profile="other")

    monkeypatch.setattr(routes, "_check_csrf", lambda _handler: True)
    monkeypatch.setattr(
        routes,
        "read_body",
        lambda _handler: {"session_id": "foreign_delete"},
    )
    monkeypatch.setattr(
        routes,
        "get_session",
        lambda sid, metadata_only=False: foreign,
    )
    monkeypatch.setattr(routes, "_get_active_profile_name", lambda: "default")
    monkeypatch.setattr(
        routes,
        "_lookup_cli_session_metadata",
        lambda _sid: (_ for _ in ()).throw(
            AssertionError("delete mutation path should not run")
        ),
    )

    cap = _capture(monkeypatch)
    routes.handle_post(handler, urlparse("/api/session/delete"))

    assert cap["bad"] == ("Session not found", 404)


def test_session_delete_foreign_cli_only_session_blocked_before_mutation(
    monkeypatch,
):
    handler = _FakeHandler()
    monkeypatch.setattr(routes, "_check_csrf", lambda _handler: True)
    monkeypatch.setattr(
        routes,
        "read_body",
        lambda _handler: {"session_id": "foreign_cli_delete"},
    )
    monkeypatch.setattr(
        routes,
        "get_session",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(KeyError("missing sidecar")),
    )
    monkeypatch.setattr(
        routes,
        "_lookup_cli_session_metadata",
        lambda _sid: {"profile": "other", "source_tag": "cli"},
    )
    monkeypatch.setattr(routes, "_get_active_profile_name", lambda: "default")
    monkeypatch.setattr(
        routes,
        "_get_session_agent_lock",
        lambda _sid: (_ for _ in ()).throw(
            AssertionError("delete mutation path should not run")
        ),
    )

    cap = _capture(monkeypatch)
    routes.handle_post(handler, urlparse("/api/session/delete"))

    assert cap["bad"] == ("Session not found", 404)


def test_cli_metadata_lookup_finds_older_session_outside_visible_cap(monkeypatch):
    from api import profiles

    monkeypatch.setattr(routes, "get_cli_sessions", lambda **_kwargs: [])
    monkeypatch.setattr(routes, "_get_active_profile_name", lambda: "default")
    monkeypatch.setattr(
        profiles,
        "list_profiles_api",
        lambda: [{"name": "default"}, {"name": "jaeger"}],
    )
    monkeypatch.setattr(
        routes,
        "agent_session_rows_existing",
        lambda ids, profile=None: frozenset(ids) if profile == "jaeger" else frozenset(),
    )

    metadata = routes._lookup_cli_session_metadata("older_cli_session")

    assert metadata["session_id"] == "older_cli_session"
    assert metadata["profile"] == "jaeger"
    assert metadata["source_tag"] == "cli"


def test_file_read_foreign_profile_session_returns_404_before_file_ops(monkeypatch):
    handler = _FakeHandler()
    foreign = _SimpleSession("foreign_file", profile="other", workspace="/workspace")
    monkeypatch.setattr(routes, "get_session", lambda sid, metadata_only=False: foreign)
    monkeypatch.setattr(routes, "_get_active_profile_name", lambda: "default")
    monkeypatch.setattr(routes, "get_session_for_file_ops", lambda sid: (_ for _ in ()).throw(AssertionError("file ops should not run")))
    cap = _capture(monkeypatch)

    routes.handle_get(handler, urlparse("/api/file?session_id=foreign_file&path=notes.txt"))

    assert cap["bad"] == ("Session not found", 404)


def test_attachment_upload_foreign_profile_session_returns_404_before_write(monkeypatch):
    handler = _FakeHandler()
    foreign = _SimpleSession("upload_foreign", profile="other")
    monkeypatch.setattr(upload, "parse_multipart", lambda *_args: ({"session_id": "upload_foreign"}, {"file": ("note.txt", b"x")}))
    monkeypatch.setattr(upload, "get_session", lambda sid: foreign)
    monkeypatch.setattr(upload, "_get_active_profile_name", lambda: "default")
    monkeypatch.setattr(
        upload,
        "_upload_destination",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("upload destination should not be resolved")),
    )

    cap = _capture_upload(monkeypatch)
    upload.handle_upload(handler)

    assert cap == {"ok": {"error": "Session not found"}, "status": 404}


def test_archive_upload_extract_foreign_profile_session_returns_404_before_extract(monkeypatch):
    handler = _FakeHandler()
    foreign = _SimpleSession("extract_foreign", profile="other")
    monkeypatch.setattr(upload, "parse_multipart", lambda *_args: ({"session_id": "extract_foreign"}, {"file": ("archive.zip", b"zip")}))
    monkeypatch.setattr(upload, "get_session", lambda sid: foreign)
    monkeypatch.setattr(upload, "_get_active_profile_name", lambda: "default")
    monkeypatch.setattr(
        upload,
        "extract_archive",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("archive extraction should not run")),
    )

    cap = _capture_upload(monkeypatch)
    upload.handle_upload_extract(handler)

    assert cap == {"ok": {"error": "Session not found"}, "status": 404}


def test_workspace_upload_foreign_profile_session_returns_404_before_workspace_resolution(monkeypatch):
    handler = _FakeHandler()
    foreign = _SimpleSession("workspace_foreign", profile="other", workspace="/workspace/foreign")
    monkeypatch.setattr(upload, "parse_multipart", lambda *_args: ({"session_id": "workspace_foreign"}, {"file": ("note.txt", b"x")}))
    monkeypatch.setattr(upload, "get_session", lambda sid: foreign)
    monkeypatch.setattr(upload, "_get_active_profile_name", lambda: "default")
    monkeypatch.setattr(
        upload,
        "resolve_trusted_workspace",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("workspace should not be resolved")),
    )

    cap = _capture_upload(monkeypatch)
    upload.handle_workspace_upload(handler)

    assert cap == {"ok": {"error": "Session not found"}, "status": 404}


def test_stream_owner_unregistered_on_worker_early_return(monkeypatch):
    """A stream cancelled before the worker starts (q is None) must not leak its owner entry.

    The route layer registers the stream owner synchronously before launching the
    worker. If the stream is cancelled before the worker reaches `q = STREAMS.get(...)`,
    the worker early-returns before register_active_run / the teardown finally — so the
    owner entry must be released on that early-return path or STREAM_SESSION_OWNERS leaks.
    """
    from api import config
    import api.streaming as streaming

    with config.STREAM_SESSION_OWNERS_LOCK:
        previous = dict(config.STREAM_SESSION_OWNERS)
        config.STREAM_SESSION_OWNERS.clear()
    # Owner registered by the route layer, but the stream was already cancelled
    # (never placed in STREAMS), so the worker will hit `q is None`.
    config.register_stream_owner("leak-stream", "some_session")
    try:
        with config.STREAMS_LOCK:
            config.STREAMS.pop("leak-stream", None)
        streaming._run_agent_streaming(
            "some_session", "hi", "m", "/tmp", "leak-stream",
        )
        with config.STREAM_SESSION_OWNERS_LOCK:
            assert "leak-stream" not in config.STREAM_SESSION_OWNERS
    finally:
        with config.STREAM_SESSION_OWNERS_LOCK:
            config.STREAM_SESSION_OWNERS.clear()
            config.STREAM_SESSION_OWNERS.update(previous)
