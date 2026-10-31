"""Resource manager - MOCKED tests (fake probe, clock, sleep and Ollama; no Mac probes)."""
from __future__ import annotations

import importlib.util
import json
import pathlib

import pytest

API = pathlib.Path(__file__).resolve().parents[5] / "jaeger_ai/features/webui/api"
OK = {"mem_free_gb": 20.0, "mem_pressure": 1, "cpu_load": 0.2, "gpu_util": 5, "disk_free_gb": 200, "thermal": "nominal",
      "on_battery": False, "battery_pct": 100, "idle_s": 999, "ollama_loaded": []}


@pytest.fixture()
def mod():
    spec = importlib.util.spec_from_file_location("_rm_test", API / "resource_manager.py")
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    return m


def make(mod, tmp_path, snaps):
    state = {"t": 0.0, "i": 0, "calls": []}
    seq = list(snaps)

    def probe(root):
        s = dict(seq[min(state["i"], len(seq) - 1)]); state["i"] += 1; return s

    def sleep(d):
        state["t"] += d

    def ollama(path, body=None):
        state["calls"].append((path, body))
        return {"models": [{"name": "minicpm-v:latest"}]} if path == "/api/ps" else {}
    rm = mod.ResourceManager(lambda: tmp_path, probe=probe, sleep=sleep, clock=lambda: state["t"], ollama=ollama)
    return rm, state


def test_config_file_created_with_defaults(mod, tmp_path):
    rm, _ = make(mod, tmp_path, [OK])
    c = rm.config()
    assert json.loads((tmp_path / "resources.json").read_text())["min_free_mem_gb"] == 4.0 and c["concurrency"]["heavy"] == 1


def test_check_reasons(mod, tmp_path):
    rm, _ = make(mod, tmp_path, [OK])
    assert rm.check("llm", "gemma4:12b", OK) == []
    bad = {**OK, "mem_free_gb": 6, "mem_pressure": 2, "thermal": "serious", "on_battery": True, "battery_pct": 10}
    why = " ".join(rm.check("llm", "gemma4:12b", bad))
    assert all(x in why for x in ("low memory", "pressure", "thermal", "battery"))


def test_user_active_throttles_heavy_not_light(mod, tmp_path):
    rm, _ = make(mod, tmp_path, [OK])
    busy = {**OK, "idle_s": 5, "cpu_load": 0.6}
    assert rm.check("llm", None, busy) and not rm.check("ocr", None, busy)


def test_acquire_backs_off_then_resumes_and_unloads_others(mod, tmp_path):
    rm, st = make(mod, tmp_path, [{**OK, "mem_pressure": 4}, {**OK, "mem_pressure": 4}, OK])
    with rm.acquire("llm", job="j", model="gemma4:12b") as info:
        assert info["waited_s"] >= 5
    u = rm.job_usage("j")
    assert u["wait_events"] == 2 and u["steps"]["llm"]["count"] == 1
    assert ("/api/generate", {"model": "minicpm-v:latest", "keep_alive": 0}) in st["calls"]


def test_status_and_cleanup(mod, tmp_path):
    rm, _ = make(mod, tmp_path, [OK])
    s = rm.status()
    assert set(s) >= {"snapshot", "config", "can_start", "active", "queued", "jobs"}
    d = tmp_path / "v"; d.mkdir()
    for n in ("lowres.mp4", "audio22k.wav", "x.part", "keep.json", "audio.m4a"):
        (d / n).write_bytes(b"x")
    mod.cleanup_temp(d)
    (d / "audio.json").write_text("{}")
    mod.cleanup_temp(d)
    assert sorted(p.name for p in d.iterdir()) == ["audio.json", "keep.json"]


def test_own_model_gpu_load_does_not_block_but_foreign_does(mod, tmp_path):
    rm, _ = make(mod, tmp_path, [OK])
    hot = {**OK, "gpu_util": 97}
    assert rm.check("vlm", "qwen3-vl:8b", {**hot, "ollama_loaded": ["qwen3-vl:8b"]}) == []
    assert rm.check("vlm", "qwen3-vl:8b", {**hot, "ollama_loaded": []})  # nothing of ours loaded -> someone else's GPU work
    assert rm.check("vlm", "qwen3-vl:8b", {**hot, "ollama_loaded": ["other:7b"]})
