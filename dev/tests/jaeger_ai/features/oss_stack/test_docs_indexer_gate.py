"""The docs gate must make progress under ordinary Mac load."""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parents[5] / "jaeger_ai/features/oss_stack/docs_indexer.py"


@pytest.fixture
def mod():
    spec = importlib.util.spec_from_file_location("_docs_indexer_gate_test", SOURCE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def install_manager(monkeypatch, snapshot):
    class Manager:
        def __init__(self, root):
            pass

        def snapshot(self):
            return snapshot

        def check(self, kind, snap):
            assert kind == "light" and snap["cpu_load"] is None
            why = []
            if snap["mem_free_gb"] < 4:
                why.append("low memory")
            if snap["mem_pressure"] > 1:
                why.append("memory pressure")
            if snap["thermal"] != "nominal":
                why.append("thermal")
            return why

    name = "jaeger_ai.features.webui.api.resource_manager"
    monkeypatch.setitem(sys.modules, name, types.SimpleNamespace(ResourceManager=Manager))


def test_high_load_does_not_hold_when_other_resources_healthy(mod, monkeypatch, tmp_path):
    snap = {"mem_free_gb": 20, "mem_pressure": 1, "cpu_load": 2.0,
            "disk_free_gb": 100, "thermal": "nominal", "on_battery": False}
    install_manager(monkeypatch, snap)
    monkeypatch.setattr(mod, "STATE_DIR", tmp_path)
    monkeypatch.setattr(mod, "HOME", tmp_path)
    monkeypatch.setattr(mod.os, "getloadavg", lambda: (100, 100, 100))
    assert mod.Indexer(tmp_path)._gate() == []


@pytest.mark.parametrize("change, expected", [
    ({"mem_pressure": 4}, "memory pressure"),
    ({"mem_free_gb": 1}, "low memory"),
    ({"thermal": "warning"}, "thermal"),
])
def test_real_pressure_holds(mod, monkeypatch, tmp_path, change, expected):
    snap = {"mem_free_gb": 20, "mem_pressure": 1, "cpu_load": 2.0,
            "disk_free_gb": 100, "thermal": "nominal", "on_battery": False}
    install_manager(monkeypatch, {**snap, **change})
    monkeypatch.setattr(mod, "STATE_DIR", tmp_path)
    monkeypatch.setattr(mod, "HOME", tmp_path)
    assert expected in " ".join(mod.Indexer(tmp_path)._gate())


def test_wait_and_success_are_saved(mod, monkeypatch, tmp_path):
    root = tmp_path / "docs"
    root.mkdir()
    (root / "a.txt").write_text("a document with enough text to index")
    monkeypatch.setattr(mod, "STATE_FILE", tmp_path / "index.json")
    monkeypatch.setattr(mod, "LOG", tmp_path / "index.jsonl")
    monkeypatch.setattr(mod.time, "sleep", lambda seconds: None)
    reasons = iter([["memory pressure"], []])
    ix = mod.Indexer(root, gate=lambda: next(reasons))
    monkeypatch.setattr(ix, "index_file", lambda path: 1)
    assert ix.pass_once(max_files=1) == {"files": 1, "chunks": 1, "errors": 0}
    assert ix.state["skip_reasons"] == []
    assert ix.state["last_skip"] <= ix.state["last_successful_index"]
    assert "last_successful_index" in mod.json.loads(mod.STATE_FILE.read_text())
