"""Resource manager - MOCKED tests (fake probe, clock, sleep and Ollama; no Mac probes)."""
from __future__ import annotations

import importlib.util
import json
import pathlib

import pytest

API = pathlib.Path(__file__).resolve().parents[5] / "jaeger_ai/core/gateway/webapp"
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


def test_reads_return_defaults_without_writing(mod, tmp_path):
    rm, _ = make(mod, tmp_path, [OK])
    c = rm.config()
    assert c["min_free_mem_gb"] == 4.0 and c["concurrency"]["heavy"] == 1
    rm.status()
    assert not (tmp_path / "resources.json").exists() and list(tmp_path.iterdir()) == []


def test_owner_resources_json_still_applies(mod, tmp_path):
    (tmp_path / "resources.json").write_text(json.dumps({"min_free_mem_gb": 8, "concurrency": {"heavy": 2}}))
    rm, _ = make(mod, tmp_path, [OK])
    c = rm.config()
    assert c["min_free_mem_gb"] == 8 and c["concurrency"]["heavy"] == 2
    (tmp_path / "resources.json").write_text("not json")
    assert rm.config()["min_free_mem_gb"] == 4.0


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


def test_interactive_inference_protects_desktop_without_eviction(mod, tmp_path, monkeypatch):
    active = {**OK, "mem_free_gb": 22, "idle_s": 2, "ollama_loaded": ["warm:latest"]}
    rm, state = make(mod, tmp_path, [active, {**active, "mem_pressure": 2}])
    queries = []

    def inventory(path, **options):
        queries.append(path)
        return {"models": [{"name": "cold:latest", "size": 17 * 2**30}]}

    monkeypatch.setattr(mod, "_ollama_call", inventory)
    endpoint = "http://localhost:11434/v1"
    assert rm.inference_blockers("warm", ollama_endpoint=endpoint) == []
    assert rm.inference_blockers("cold:latest", ollama_endpoint=endpoint) == [
        "the model would leave too little memory for the desktop",
    ]
    assert queries == ["/api/tags"]
    state["t"] += 4
    assert rm.inference_blockers("warm:latest", ollama_endpoint=endpoint) == ["memory pressure is high"]
    assert state["calls"] == []


def test_interactive_inference_reserves_half_the_mac_for_active_desktop(mod, tmp_path):
    active = {**OK, "mem_total_gb": 32, "mem_free_gb": 28, "idle_s": 2}
    (tmp_path / "resources.json").write_text(json.dumps({"model_gb": {"large": 17}}))
    rm, state = make(mod, tmp_path, [active, {**active, "idle_s": 999}])
    assert rm.inference_blockers("large") == ["the model is too large to load while the desktop is in use"]
    state["t"] += 4
    assert rm.inference_blockers("large") == []


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


def test_inference_deferral_telemetry_and_shared_module(mod, tmp_path):
    rm, _ = make(mod, tmp_path, [OK])
    assert rm.status()["last_inference_deferral"] is None
    rm.record_inference_deferral("qwen3-vl:8b", ["memory pressure is high"], outcome="deferred_fallback_eligible")
    st = rm.status()
    assert st["last_inference_deferral"]["model"] == "qwen3-vl:8b"
    assert st["last_inference_deferral"]["reasons"] == ["memory pressure is high"]
    assert st["last_inference_deferral"]["outcome"] == "deferred_fallback_eligible"
    assert len(st["inference_deferrals"]) == 1

    from jaeger_ai.core.gateway.webapp import resource_manager as canonical_rm, unified_api
    assert unified_api._rmmod() is canonical_rm
