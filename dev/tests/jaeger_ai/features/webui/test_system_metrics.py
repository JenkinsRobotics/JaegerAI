"""Home metrics endpoint helpers (unified UI)."""
from __future__ import annotations

import importlib.util
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[5] / "jaeger_ai/features/webui/api/system_metrics.py"


def _load():
    spec = importlib.util.spec_from_file_location("_system_metrics", ROOT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_sample_shape(monkeypatch):
    m = _load()
    monkeypatch.setattr(m, "gateway_probe", lambda: {"ok": True, "latency_ms": 1.0})
    monkeypatch.setattr(m, "_gpu", lambda: None)
    s = m.sample()
    assert s["gateway"]["ok"] is True and 0 <= s["disk"] <= 100 and "cpu" in s and "t" in s


def test_unreachable_gateway_reports_down(monkeypatch):
    m = _load()
    monkeypatch.setattr(m, "GATEWAY", "http://127.0.0.1:9/health")
    assert m.gateway_probe() == {"ok": False, "latency_ms": None}


def test_history_is_bounded():
    m = _load()
    assert m._buf.maxlen == m.HISTORY
