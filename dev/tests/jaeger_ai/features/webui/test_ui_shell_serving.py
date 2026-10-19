"""The WebUI serves the new UI build at / and the old shell only at /legacy."""
from __future__ import annotations

import importlib.util
import io
import pathlib
import sys
from types import SimpleNamespace
from urllib.parse import urlparse

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[5] / "jaeger_ai/features/webui/api/ui_shell.py"


def _load():
    spec = importlib.util.spec_from_file_location("_ui_shell", ROOT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _Handler:
    def __init__(self):
        self.status, self.headers, self.wfile = None, {}, io.BytesIO()

    def send_response(self, code):
        self.status = code

    def send_header(self, k, v):
        self.headers[k] = v

    def end_headers(self):
        pass


@pytest.fixture()
def dist(tmp_path, monkeypatch):
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text('<script src="./assets/app.js"></script>')
    (tmp_path / "assets" / "app.js").write_text("console.log(1)")
    (tmp_path.parent / "secret.txt").write_text("no")
    monkeypatch.setenv("JAEGER_WEBUI_UI_DIST", str(tmp_path))
    monkeypatch.delenv("JAEGER_WEBUI_LEGACY", raising=False)
    return tmp_path


def _get(mod, path):
    h = _Handler()
    return mod.serve(h, urlparse(path)), h


def test_root_and_assets_come_from_the_build(dist):
    mod = _load()
    out, h = _get(mod, "/")
    assert out is True and h.status == 200 and b"./assets/app.js" in h.wfile.getvalue()
    out, h = _get(mod, "/assets/app.js")
    assert h.status == 200 and h.headers["Content-Type"].startswith("text/javascript")
    out, h = _get(mod, "/assets/../../secret.txt")
    assert h.status == 404
    assert _get(mod, "/api/sessions")[0] is False


def test_legacy_only_behind_flag(dist, monkeypatch):
    mod = _load()
    out, h = _get(mod, "/legacy")
    assert out is True and h.status == 404
    monkeypatch.setenv("JAEGER_WEBUI_LEGACY", "1")
    assert _get(mod, "/legacy")[0] == "legacy"


def test_without_a_build_root_falls_through_to_the_old_shell(tmp_path, monkeypatch):
    monkeypatch.setenv("JAEGER_WEBUI_UI_DIST", str(tmp_path / "missing"))
    assert _get(_load(), "/")[0] is False


def test_run_script_defaults_to_loopback():
    script = (ROOT.parents[4] / "scripts/run-jaeger-webui.sh").read_text()
    assert 'JAEGER_WEBUI_ALLOW_LAN:-0' in script
    # An inherited HERMES_WEBUI_HOST must not re-open LAN on its own.
    head = script.split('JAEGER_WEBUI_ALLOW_LAN:-0', 1)[0]
    assert 'if [[ -n "${HERMES_WEBUI_HOST:-}" ]]' not in head


def test_old_service_worker_is_replaced_by_a_kill_switch(dist):
    mod = _load()
    for path in ("/sw.js", "/static/sw.js"):
        out, h = _get(mod, path)
        body = h.wfile.getvalue().decode()
        assert out is True and h.status == 200
        assert h.headers["Content-Type"].startswith("text/javascript")
        assert h.headers["Cache-Control"] == "no-cache, no-store"
        assert h.headers["Clear-Site-Data"] == '"cache"'
        for needle in ("skipWaiting", "caches.keys", "caches.delete", "clients.claim",
                       "registration.unregister", "navigate"):
            assert needle in body, needle
        assert "SHELL_ASSETS" not in body and "hermes-shell" not in body
    _, h = _get(mod, "/")
    assert h.headers["Cache-Control"] == "no-cache, no-store"
    _, h = _get(mod, "/index.html")
    assert h.headers["Cache-Control"] == "no-cache, no-store"


def test_static_manifest_keeps_the_pwa_type(dist):
    mod = _load()
    out, h = _get(mod, "/static/manifest.json")
    assert out is True and h.status == 200
    assert h.headers["Content-Type"].startswith("application/manifest+json")
    assert b'"name"' in h.wfile.getvalue()
    assert _get(mod, "/static/../../etc/passwd.webmanifest")[1].status == 404


def test_without_a_build_sw_and_manifest_stay_legacy(tmp_path, monkeypatch):
    monkeypatch.setenv("JAEGER_WEBUI_UI_DIST", str(tmp_path / "missing"))
    mod = _load()
    for path in ("/sw.js", "/static/sw.js", "/static/manifest.json"):
        assert _get(mod, path)[0] is False


def test_build_root_files_are_served_with_their_types(dist):
    (dist / "jaeger-icon.svg").write_text("<svg/>")
    (dist / "jaeger-icon-180.png").write_bytes(b"\x89PNG")
    (dist / "manifest.webmanifest").write_text('{"name": "Jaeger"}')
    (dist / ".env").write_text("SECRET=1")
    (dist / "copy.html").write_text("<html>")
    (dist / "alias").symlink_to(dist / "index.html")
    (dist.parent / "outside.png").write_bytes(b"no")
    (dist / "out.png").symlink_to(dist.parent / "outside.png")
    mod = _load()
    for path, ctype in (("/jaeger-icon.svg", "image/svg+xml"), ("/jaeger-icon-180.png", "image/png"),
                        ("/manifest.webmanifest", "application/manifest+json"),
                        ("/manifest.json", "application/manifest+json")):
        out, h = _get(mod, path)
        assert out is True and h.status == 200 and h.headers["Content-Type"].startswith(ctype), path
    assert b'"Jaeger"' in _get(mod, "/manifest.json")[1].wfile.getvalue()
    for path in ("/.env", "/copy.html", "/alias", "/out.png", "/assets", "/../secret.txt", "/missing.png"):
        assert _get(mod, path)[0] is False, path


def test_manifest_json_falls_through_without_a_build_manifest(dist):
    assert _get(_load(), "/manifest.json")[0] is False


def test_without_a_build_root_files_stay_legacy(tmp_path, monkeypatch):
    monkeypatch.setenv("JAEGER_WEBUI_UI_DIST", str(tmp_path / "missing"))
    mod = _load()
    for path in ("/manifest.webmanifest", "/manifest.json", "/jaeger-icon.svg"):
        assert _get(mod, path)[0] is False
