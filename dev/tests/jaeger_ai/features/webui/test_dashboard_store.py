"""Workspace layout store behind GET/PUT /v1/dashboard (unified UI)."""
from __future__ import annotations

import importlib.util
import json
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[5] / "jaeger_ai/features/webui/api/dashboard_store.py"


def _load():
    spec = importlib.util.spec_from_file_location("_dashboard_store", ROOT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("JAEGER_STATE_HOME", str(tmp_path))
    return _load()


def test_missing_file_reads_empty(store):
    assert store.read() == {"v": 1, "hosts": {"page": [], "float": [], "overlay": [], "menubar": []}}


def test_round_trip_and_atomic_write(store, tmp_path):
    doc = {"v": 1, "hosts": {"page": [{"i": "agents.status", "x": 0, "y": 0, "w": 4, "h": 3, "extra": "dropped"}]}}
    saved = store.write(doc)
    assert saved["hosts"]["page"] == [{"i": "agents.status", "x": 0, "y": 0, "w": 4, "h": 3}]
    assert json.loads((tmp_path / "dashboard.json").read_text())["hosts"]["page"][0]["i"] == "agents.status"
    assert store.read() == saved


@pytest.mark.parametrize("bad", [None, {"v": 2, "hosts": {}}, {"v": 1, "hosts": {"page": [{"i": "", "x": 0, "y": 0, "w": 1, "h": 1}]}},
                                 {"v": 1, "hosts": {"page": [{"i": "a", "x": -1, "y": 0, "w": 1, "h": 1}]}}])
def test_rejects_bad_documents(store, bad):
    with pytest.raises(ValueError):
        store.write(bad)
