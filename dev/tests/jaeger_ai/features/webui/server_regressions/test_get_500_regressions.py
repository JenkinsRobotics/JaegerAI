"""The six GETs that returned 500 on live 8790 (smoke 2026-10-31): undefined names left by the route
extraction, and the optional agent `cron` package imported before input validation."""
from __future__ import annotations

import builtins
import io
import json
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

import pytest

import api.routes as routes

API = Path(routes.__file__).resolve().parent


class _H:
    def __init__(self):
        self.status = None
        self.headers = {}
        self.wfile = io.BytesIO()
        self.rfile = io.BytesIO(b"")
        self.command = "GET"
        self.path = "/"
        self.client_address = ("127.0.0.1", 1)

    def send_response(self, status):
        self.status = status

    def send_header(self, k, v):
        self.headers[k] = v

    def end_headers(self):
        pass

    def body(self):
        raw = self.wfile.getvalue().decode("utf-8", "replace")
        try:
            return json.loads(raw)
        except ValueError:
            return raw


def get(path):
    h = _H()
    h.path = path
    routes.handle_get(h, urlparse(path))
    return h.status, h.body()


def test_no_undefined_names_in_extracted_route_modules():
    out = subprocess.run([sys.executable, "-m", "ruff", "check", "--select", "F821", "--output-format", "concise",
                          str(API / "routes.py"), str(API / "route_insights.py"), str(API / "route_notes.py")],
                         capture_output=True, text=True)
    if "No module named ruff" in out.stderr:
        pytest.skip("ruff not installed")
    assert out.returncode == 0, out.stdout[-2000:]


@pytest.fixture
def no_cron(monkeypatch):
    real = builtins.__import__
    monkeypatch.delitem(sys.modules, "cron", raising=False)
    monkeypatch.delitem(sys.modules, "cron.jobs", raising=False)

    def imp(name, *a, **k):
        if name == "cron" or name.startswith("cron."):
            raise ModuleNotFoundError("No module named 'cron'")
        return real(name, *a, **k)
    monkeypatch.setattr(builtins, "__import__", imp)
    monkeypatch.setattr(routes, "_runner_schedule_forward", lambda *a, **k: None, raising=False)

