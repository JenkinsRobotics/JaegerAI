"""OS1 hardware_bench — live probes for hybrid onboarding."""
from __future__ import annotations

import time

from jaeger_ai.core.instance import hardware_bench as hw


def test_hardware_bench_start_and_status():
    started = hw.start()
    assert started["status"] in {"running", "done"}
    assert started.get("brand") == "Jenkins Robotics Jaeger AI OS1"
    job_id = started["id"]
    deadline = time.time() + 30
    snap = started
    while time.time() < deadline:
        snap = hw.status(job_id)
        if snap["status"] in {"done", "error"}:
            break
        time.sleep(0.3)
    assert snap["status"] == "done"
    assert snap["progress"] >= 1.0
    assert isinstance(snap.get("log"), list) and len(snap["log"]) >= 4
    rec = snap.get("recommendation") or {}
    assert "tier_label" in rec
    assert "host_memory_gb" in rec


def test_name_enrich_soft_fails_to_corpus(monkeypatch):
    from jaeger_ai.core.instance.name_selection import enrich_with_model_reason

    monkeypatch.setattr(
        "jaeger_ai.core.instance.name_selection._try_model_reason",
        lambda *a, **k: None,
    )
    record = {
        "name": "Vera",
        "origin": "Latin",
        "meaning": "truth",
        "register": "precise",
        "selected_from": 10,
    }
    out = enrich_with_model_reason(record, stance={"register": "precise"}, voice_profile="female")
    assert out["reason_source"] == "corpus"
    assert "Vera" in out["reason"]
