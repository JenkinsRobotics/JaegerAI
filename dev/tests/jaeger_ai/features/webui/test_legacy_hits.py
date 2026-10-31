"""Removal stage 2: legacy /api/* hit counter (counts only, never breaks a request)."""
from __future__ import annotations

import importlib.util
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[5] / "jaeger_ai/features/webui/api/legacy_hits.py"


def _load():
    spec = importlib.util.spec_from_file_location("_legacy_hits", ROOT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_counts_by_group_and_normalised_route_and_flushes(tmp_path, monkeypatch):
    monkeypatch.setenv("JAEGER_STATE_DIR", str(tmp_path))
    m = _load(); m._reset_for_tests()
    m.record("GET", "/api/session/3f2a9c1e0b7d4e11/messages?x=secret", now=1000.0)
    m.record("get", "/api/session/0123456789abcdef/messages", now=1001.0)
    m.record("POST", "/api/kanban/boards", now=1002.0)
    m.record("GET", "/v1/agents", now=1003.0)  # not legacy: ignored
    snap = m.snapshot()
    assert snap["groups"] == {"session": 2, "kanban": 1}
    assert snap["routes"]["GET /api/session/:id/messages"]["hits"] == 2
    m.flush(now=2000.0)
    data = json.loads((tmp_path / "logs" / "legacy-api-hits.json").read_text())
    assert "secret" not in json.dumps(data)
    assert data["routes"]["POST /api/kanban/boards"]["hits"] == 1


def test_reload_continues_counts_and_record_never_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("JAEGER_STATE_DIR", str(tmp_path))
    m = _load(); m._reset_for_tests()
    m.record("GET", "/api/models", now=1.0); m.flush()
    m2 = _load(); m2._reset_for_tests()
    m2.record("GET", "/api/models", now=2.0)
    assert m2.snapshot()["routes"]["GET /api/models"]["hits"] == 2
    monkeypatch.setenv("JAEGER_STATE_DIR", "/dev/null/nope")
    m3 = _load(); m3._reset_for_tests()
    m3.record("GET", "/api/x", now=3.0); m3.flush()  # unwritable: silently ignored
