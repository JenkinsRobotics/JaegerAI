"""scripts/verify-stack-smoke.py checks the four live services (Gateway 33418,
WebUI 8790, MCP 8792, voice 8794) with no network in this test."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "verify-stack-smoke.py"


def _load():
    spec = importlib.util.spec_from_file_location("verify_stack_smoke", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_checks_target_the_live_ports():
    mod = _load()
    assert [(name, port) for name, port, _, _ in mod.CHECKS] == [
        ("gateway", 33418), ("webui", 8790), ("mcp", 8792), ("voice", 8794)]


def test_all_healthy_passes_and_one_down_fails(monkeypatch, capsys):
    mod = _load()
    healthy = {33418: (200, {"status": "ok"}), 8790: (200, {"status": "ok"}),
               8792: (401, "unauthorized"), 8794: (200, {"status": "ok"})}
    monkeypatch.setattr(mod, "_get", lambda url, timeout=4.0: healthy[int(url.split(":")[2].split("/")[0])])
    assert mod.main(["--json"]) == 0
    rows = json.loads(capsys.readouterr().out)
    assert all(r["ok"] for r in (rows if isinstance(rows, list) else rows["checks"]))
    healthy[8794] = (0, "connection refused")
    assert mod.main(["--json"]) != 0
