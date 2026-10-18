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
