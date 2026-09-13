"""OS1 first-boot hardware bench — real probes with live progress.

Runs during hybrid onboarding while the operator continues character
selection. Not a fake spinner: each probe records what ran, a score /
reading, and an ETA so the Mac UI can stream status.
"""

from __future__ import annotations

import os
import platform
import shutil
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from jaeger_ai.core.models.host_recommendation import (
    classify_tier,
    detect_total_memory_gb,
    recommend_for_tier,
)

_LOCK = threading.Lock()
_JOBS: dict[str, "BenchJob"] = {}


@dataclass
class ProbeEvent:
    name: str
    detail: str
    ok: bool
    value: str = ""
    ms: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "detail": self.detail,
            "ok": self.ok,
            "value": self.value,
            "ms": self.ms,
        }


@dataclass
class BenchJob:
    id: str
    status: str = "running"  # running | done | error
    current: str = ""
    progress: float = 0.0
    eta_s: float = 12.0
    log: list[ProbeEvent] = field(default_factory=list)
    recommendation: dict[str, Any] | None = None
    error: str | None = None
    started_at: float = field(default_factory=time.time)

    def as_dict(self) -> dict[str, Any]:
        elapsed = max(0.0, time.time() - self.started_at)
        return {
            "id": self.id,
            "status": self.status,
            "current": self.current,
            "progress": round(self.progress, 3),
            "eta_s": max(0, int(self.eta_s)),
            "elapsed_s": int(elapsed),
            "log": [e.as_dict() for e in self.log],
            "recommendation": self.recommendation,
            "error": self.error,
            "brand": "Jenkins Robotics Jaeger AI OS1",
        }


def start() -> dict[str, Any]:
    """Kick a new bench (or return the active one)."""
    with _LOCK:
        for job in _JOBS.values():
            if job.status == "running":
                return job.as_dict()
        job = BenchJob(id=uuid.uuid4().hex[:12], eta_s=14.0)
        _JOBS[job.id] = job
    threading.Thread(target=_run, args=(job.id,), daemon=True).start()
    return job.as_dict()


def status(job_id: str | None = None) -> dict[str, Any]:
    with _LOCK:
        if job_id and job_id in _JOBS:
            return _JOBS[job_id].as_dict()
        # latest
        if not _JOBS:
            return {"status": "idle", "brand": "Jenkins Robotics Jaeger AI OS1"}
        latest = max(_JOBS.values(), key=lambda j: j.started_at)
        return latest.as_dict()


def _emit(job: BenchJob, name: str, detail: str, ok: bool, value: str = "", ms: int = 0) -> None:
    job.current = detail
    job.log.append(ProbeEvent(name=name, detail=detail, ok=ok, value=value, ms=ms))


def _run(job_id: str) -> None:
    with _LOCK:
        job = _JOBS[job_id]
    probes = (
        ("host", "Reading host identity"),
        ("memory", "Measuring unified memory"),
        ("cpu", "Counting CPU cores"),
        ("disk", "Checking free disk for models"),
        ("ollama", "Probing Ollama endpoint"),
        ("tier", "Choosing model tier from results"),
    )
    n = len(probes)
    try:
        mem_gb = 0.0
        ollama_ok = False
        for i, (name, detail) in enumerate(probes):
            t0 = time.time()
            job.progress = i / n
            job.eta_s = max(1.0, (n - i) * 1.8)
            job.current = detail
            ok, value = True, ""
            try:
                if name == "host":
                    value = f"{platform.system()} {platform.machine()}"
                elif name == "memory":
                    mem_gb = float(detect_total_memory_gb())
                    value = f"{mem_gb:.1f} GB"
                elif name == "cpu":
                    value = f"{os.cpu_count() or 1} cores"
                elif name == "disk":
                    usage = shutil.disk_usage(os.path.expanduser("~"))
                    free_gb = usage.free / (1024 ** 3)
                    value = f"{free_gb:.0f} GB free"
                    ok = free_gb >= 20
                elif name == "ollama":
                    ok, value = _probe_ollama()
                    ollama_ok = ok
                elif name == "tier":
                    tier = classify_tier(mem_gb)
                    rec = recommend_for_tier(tier)
                    value = rec.tier_label
                    # Ollama online → use the locked local endpoint as
                    # the serving provider; otherwise the in-process GGUF.
                    provider = "ollama-local" if ollama_ok else "in-process"
                    job.recommendation = {
                        "host_memory_gb": round(mem_gb, 1),
                        "tier_label": rec.tier_label,
                        "tier_description": rec.description,
                        "provider": provider,
                        "awake": {
                            "key": rec.awake.registry_key,
                            "display_name": rec.awake.display_name,
                            "size_gb": rec.awake.size_gb,
                            "notes": rec.awake.notes,
                        },
                        "asleep": None if rec.asleep is None else {
                            "key": rec.asleep.registry_key,
                            "display_name": rec.asleep.display_name,
                            "size_gb": rec.asleep.size_gb,
                            "notes": rec.asleep.notes,
                        },
                    }
            except Exception as exc:  # noqa: BLE001
                ok, value = False, str(exc)[:160]
            ms = int((time.time() - t0) * 1000)
            _emit(job, name, detail, ok, value=value, ms=ms)
            # Brief pause so the Mac panel can stream each probe rather
            # than collapsing the whole bench into one frame.
            time.sleep(0.2)
        job.progress = 1.0
        job.eta_s = 0
        job.current = "Hardware bench complete"
        job.status = "done"
    except Exception as exc:  # noqa: BLE001
        job.status = "error"
        job.error = str(exc)[:300]
        job.current = "Hardware bench failed"


def _probe_ollama() -> tuple[bool, str]:
    import urllib.request

    url = os.environ.get("JAEGER_OLLAMA_URL", "http://192.168.64.1:11434").rstrip("/")
    try:
        with urllib.request.urlopen(f"{url}/api/tags", timeout=2.5) as resp:
            ok = 200 <= getattr(resp, "status", 200) < 300
            return ok, f"{url} {'online' if ok else 'bad status'}"
    except Exception as exc:  # noqa: BLE001
        return False, f"{url} unreachable ({type(exc).__name__})"
