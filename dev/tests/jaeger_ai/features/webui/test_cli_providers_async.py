"""GET /v1/providers/cli answers fast: cached/stale rows + a background probe (never blocks on CLI subprocesses)."""
from __future__ import annotations

import importlib.util
import pathlib
import threading
import time

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[5] / "jaeger_ai/features/webui/api/cli_providers.py"


@pytest.fixture()
def cli(tmp_path, monkeypatch):
    monkeypatch.setenv("JAEGER_STATE_HOME", str(tmp_path))
    spec = importlib.util.spec_from_file_location("_cli_providers_async", ROOT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    gate = threading.Event()
    calls = []

    def slow_probe():
        calls.append(1)
        gate.wait(5)
        return [{"id": "codex", "label": "Codex", "kind": "cli", "installed": True, "path": "/bin/codex", "version": "1",
                 "signed_in": True, "status_note": "Signed in", "login_command": "codex login", "streams": True, "models": []}]
    monkeypatch.setattr(mod, "_probe_all", slow_probe)
    monkeypatch.setattr(mod, "_which", lambda b: None)
    mod._gate, mod._calls = gate, calls
    return mod


def _wait(cond, t=3):
    end = time.time() + t
    while time.time() < end and not cond():
        time.sleep(0.01)
    return cond()


def test_first_get_is_instant_and_refreshes_in_background(cli):
    t0 = time.perf_counter()
    out = cli.detect_status()
    assert time.perf_counter() - t0 < 0.5
    assert out["stale"] is True and out["refreshing"] is True and out["checked_at"] is None
    assert {r["state"] for r in out["providers"]} == {"checking"}
    again = cli.detect_status()  # a second GET does not start a second probe
    assert again["refreshing"] and len(cli._calls) == 1
    cli._gate.set()
    assert _wait(lambda: not cli.detect_status()["stale"])
    fresh = cli.detect_status()
    assert fresh["refreshing"] is False and fresh["providers"][0]["state"] == "ready" and fresh["checked_at"]


def test_stale_cache_served_while_refreshing(cli, monkeypatch):
    cli._gate.set()
    cli.detect(refresh=True)
    cli._gate.clear()
    cli._cache["at"] -= cli.TTL + 1
    t0 = time.perf_counter()
    out = cli.detect_status()
    assert time.perf_counter() - t0 < 0.5
    assert out["stale"] and out["refreshing"] and out["providers"][0]["id"] == "codex"
    cli._gate.set()
