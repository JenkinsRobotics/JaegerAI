"""Device resource manager for heavy on-device Jaeger jobs (YouTube research first; reusable).

- probe(): free unified memory, memory-pressure level, CPU load, GPU utilisation, disk, thermal and
  power state, how long since the user last touched keyboard/mouse, and which Ollama models are loaded.
- acquire(kind, job, priority, model=None): a priority queue with per-class concurrency limits.
  It blocks (backing off 5 s → 60 s) while limits say no, records why, and resumes by itself.
  For model work it keeps ONE large model resident: other loaded Ollama models are unloaded
  (keep_alive 0) before the next one loads. release_models() unloads at the end of a job.
- Limits live in <state>/resources.json (optional; defaults apply when it is absent; reads never create it).
- disk budget for <state>/research and cleanup of temp media files.
Everything is injectable (probe, sleep, clock, ollama) so tests run without a Mac.
"""
from __future__ import annotations

import heapq
import itertools
import json
import os
import re
import shutil
import subprocess
import threading
import time
import urllib.request
from contextlib import contextmanager
from pathlib import Path

DEFAULTS = {
    "min_free_mem_gb": 4.0,            # keep this much unified memory free after a model loads
    "max_memory_pressure": 1,          # kern.memorystatus_vm_pressure_level: 1 normal, 2 warn, 4 critical
    "max_cpu_load": 0.85,              # 1-min load average / cores
    "max_gpu_util_pct": 90,            # don't start new GPU work above this
    "min_free_disk_gb": 15.0,
    "research_disk_budget_gb": 40.0,   # <state>/research may not grow past this
    "pause_on_thermal": True,          # any thermal/performance warning → wait
    "min_battery_pct": 30,             # on battery below this → wait (no battery = AC)
    "user_active_idle_s": 60,          # HID idle below this = user is using the Mac
    "user_active_policy": "throttle",  # "throttle": heavy work only if well under limits; "pause": wait
    "concurrency": {"heavy": 1, "light": 2},
    "model_gb": {"gemma4:12b": 9.5, "qwen3-vl:8b": 7.0, "qwen2.5vl:7b": 7.0, "minicpm-v:latest": 5.5, "_default": 8.0},
    "backoff_s": [5, 60],
}
HEAVY = {"llm", "vlm", "vision", "whisper"}
LIGHT = {"ocr", "audio", "ffmpeg", "download"}


class ResourceManager:
    def __init__(self, state_root, probe=None, sleep=time.sleep, clock=time.time, ollama=None):
        self._root = state_root
        self._probe = probe or probe_mac
        self._sleep, self._clock = sleep, clock
        self._ollama = ollama or _ollama_call
        self._cv = threading.Condition()
        self._heap: list = []
        self._seq = itertools.count()
        self._active: dict[int, dict] = {}
        self._jobs: dict[str, dict] = {}
        self._snap: tuple[float, dict] | None = None
        self._resident: str | None = None

    # ── config / probe ────────────────────────────────────────────────
    def config_path(self) -> Path:
        return Path(self._root()) / "resources.json"

    def config(self) -> dict:
        p = self.config_path()
        try:
            user = json.loads(p.read_text("utf-8"))
        except (OSError, ValueError):
            user = None
        if not isinstance(user, dict):
            user = {}  # reads never write: defaults apply until the owner saves a resources.json
        cfg = {**DEFAULTS, **{k: v for k, v in user.items() if k in DEFAULTS}}
        cfg["concurrency"] = {**DEFAULTS["concurrency"], **(user.get("concurrency") or {})}
        cfg["model_gb"] = {**DEFAULTS["model_gb"], **(user.get("model_gb") or {})}
        return cfg

    def snapshot(self, max_age: float = 3.0) -> dict:
        now = self._clock()
        if self._snap and now - self._snap[0] < max_age:
            return self._snap[1]
        s = self._probe(Path(self._root()))
        s["research_gb"] = research_usage_gb(Path(self._root()) / "research")
        s["at"] = now
        self._snap = (now, s)
        return s

    # ── decisions ─────────────────────────────────────────────────────
    def check(self, kind: str, model: str | None = None, snap: dict | None = None) -> list[str]:
        """Reasons this step must wait right now (empty = go)."""
        c, s = self.config(), snap or self.snapshot()
        why = []
        heavy = kind in HEAVY
        need = 0.0
        if model and model != s.get("_assume_resident") and model not in (s.get("ollama_loaded") or []):
            need = c["model_gb"].get(model, c["model_gb"]["_default"])
            # models we'll unload first give their memory back
            need -= sum(c["model_gb"].get(m, c["model_gb"]["_default"]) for m in (s.get("ollama_loaded") or []) if m != model)
            need = max(need, 0.0)
        active_user = s.get("idle_s") is not None and s["idle_s"] < c["user_active_idle_s"]
        strict = 1.0
        if active_user and heavy:
            if c["user_active_policy"] == "pause":
                why.append(f"user active (idle {s['idle_s']:.0f}s)")
            else:
                strict = 0.6  # throttle: tighter CPU/GPU limits, 1.5× memory headroom
        if s.get("mem_free_gb") is not None and s["mem_free_gb"] - need < c["min_free_mem_gb"] * (1.5 if strict < 1 else 1):
            why.append(f"low memory ({s['mem_free_gb']:.1f} GB free, need {need:.1f} + {c['min_free_mem_gb'] * (1.5 if strict < 1 else 1):.1f})")
        if (s.get("mem_pressure") or 1) > c["max_memory_pressure"]:
            why.append(f"memory pressure level {s['mem_pressure']}")
        if s.get("cpu_load") is not None and s["cpu_load"] > c["max_cpu_load"] * strict:
            why.append(f"CPU load {s['cpu_load']:.2f}")
        own_gpu = bool(model) and set(s.get("ollama_loaded") or []) <= {model} and (s.get("ollama_loaded") or self._recent_own())
        if heavy and not own_gpu and s.get("gpu_util") is not None and s["gpu_util"] > c["max_gpu_util_pct"] * strict:
            why.append(f"GPU {s['gpu_util']}%")
        if s.get("disk_free_gb") is not None and s["disk_free_gb"] < c["min_free_disk_gb"]:
            why.append(f"disk {s['disk_free_gb']:.0f} GB free")
        if kind == "download" and s.get("research_gb", 0) > c["research_disk_budget_gb"]:
            why.append(f"research disk budget ({s['research_gb']:.1f}/{c['research_disk_budget_gb']} GB)")
        if c["pause_on_thermal"] and s.get("thermal") not in (None, "nominal"):
            why.append(f"thermal: {s['thermal']}")
        if s.get("on_battery") and (s.get("battery_pct") or 0) < c["min_battery_pct"]:
            why.append(f"battery {s.get('battery_pct')}%")
        return why

    def _recent_own(self, window_s: float = 15.0) -> bool:
        """GPU load right after our own heavy step is ours, not the user's."""
        return self._clock() - getattr(self, "_last_heavy_end", -1e9) < window_s

    # ── queue ─────────────────────────────────────────────────────────
    def _klass(self, kind: str) -> str:
        return "heavy" if kind in HEAVY else "light"

    def _running(self, klass: str) -> int:
        return sum(1 for a in self._active.values() if a["klass"] == klass)

    @contextmanager
    def acquire(self, kind: str, job: str = "-", priority: int = 5, model: str | None = None):
        """Lower priority number runs first. Blocks until a slot is free and the device allows it."""
        klass = self._klass(kind)
        ticket = next(self._seq)
        t0 = self._clock()
        usage = self._job(job)
        started = t0
        with self._cv:
            heapq.heappush(self._heap, (priority, ticket, klass))
        delay = self.config()["backoff_s"][0]
        try:
            while True:
                with self._cv:
                    mine_next = next((t for p, t, k in sorted(self._heap) if k == klass), None) == ticket
                    slot = self._running(klass) < self.config()["concurrency"][klass]
                if mine_next and slot:
                    why = self.check(kind, model)
                    if not why:
                        break
                    usage["last_wait_reason"] = "; ".join(why)
                    usage["wait_events"] += 1
                else:
                    usage["last_wait_reason"] = "queued"
                self._snap = None if mine_next and slot else self._snap
                self._sleep(delay if mine_next and slot else 0.2)
                if mine_next and slot:
                    delay = min(delay * 2, self.config()["backoff_s"][1])
            with self._cv:
                self._heap = [h for h in self._heap if h[1] != ticket]; heapq.heapify(self._heap)
                self._active[ticket] = {"kind": kind, "klass": klass, "job": job, "model": model, "since": self._clock()}
                self._cv.notify_all()
            waited = self._clock() - t0
            usage["wait_s"] += waited
            started = self._clock()
            if model:
                self.ensure_only(model)
            yield {"waited_s": round(waited, 2)}
        finally:
            with self._cv:
                self._heap = [h for h in self._heap if h[1] != ticket]; heapq.heapify(self._heap)
                a = self._active.pop(ticket, None)
                self._cv.notify_all()
            if a and klass == "heavy":
                self._last_heavy_end = self._clock()
            if a:
                st = usage["steps"].setdefault(kind, {"count": 0, "busy_s": 0.0})
                st["count"] += 1
                st["busy_s"] = round(st["busy_s"] + self._clock() - started, 2)
                usage["last_wait_reason"] = None

    # ── models ────────────────────────────────────────────────────────
    def ensure_only(self, model: str) -> None:
        """Unload every other Ollama model before `model` loads, so one large model is resident."""
        try:
            loaded = [m.get("name") for m in self._ollama("/api/ps").get("models", [])]
        except Exception:  # noqa: BLE001
            loaded = []
        for m in loaded:
            if m != model:
                self.unload(m)
        self._resident = model

    def unload(self, model: str) -> None:
        try:
            self._ollama("/api/generate", {"model": model, "keep_alive": 0})
        except Exception:  # noqa: BLE001
            pass
        self._snap = None

    def release_models(self, models) -> None:
        for m in set(models):
            self.unload(m)
        self._resident = None

    # ── reporting ─────────────────────────────────────────────────────
    def _job(self, job: str) -> dict:
        with self._cv:
            return self._jobs.setdefault(job, {"wait_s": 0.0, "wait_events": 0, "steps": {}, "last_wait_reason": None})

    def job_usage(self, job: str) -> dict:
        u = self._jobs.get(job)
        return json.loads(json.dumps(u)) if u else {"wait_s": 0.0, "wait_events": 0, "steps": {}, "last_wait_reason": None}

    def status(self) -> dict:
        s = self.snapshot()
        with self._cv:
            active = [dict(a) for a in self._active.values()]
            queued = [{"priority": p, "class": k} for p, _, k in sorted(self._heap)]
        return {"snapshot": s, "config": self.config(), "config_path": str(self.config_path()),
                "can_start": {k: self.check(k, snap=s) for k in ("llm", "whisper", "ocr", "download")},
                "active": active, "queued": queued, "jobs": {j: self.job_usage(j) for j in list(self._jobs)}}


# ── macOS probes (each one optional; None when unavailable) ─────────

def _out(cmd: list[str], timeout: float = 3) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def probe_mac(root: Path) -> dict:
    s: dict = {}
    vm = _out(["vm_stat"])
    ps = re.search(r"page size of (\d+)", vm)
    if ps:
        page = int(ps.group(1))
        pages = {k: int(v) for k, v in re.findall(r"Pages (free|inactive|speculative|purgeable):\s+(\d+)", vm)}
        s["mem_free_gb"] = round(sum(pages.values()) * page / 2**30, 2)
    tot = _out(["sysctl", "-n", "hw.memsize"]).strip()
    s["mem_total_gb"] = round(int(tot) / 2**30, 1) if tot.isdigit() else None
    lvl = _out(["sysctl", "-n", "kern.memorystatus_vm_pressure_level"]).strip()
    s["mem_pressure"] = int(lvl) if lvl.isdigit() else None
    try:
        s["cpu_load"] = round(os.getloadavg()[0] / (os.cpu_count() or 1), 2)
    except OSError:
        s["cpu_load"] = None
    g = re.search(r'"Device Utilization %"=(\d+)', _out(["ioreg", "-r", "-d", "1", "-c", "IOAccelerator"]))
    s["gpu_util"] = int(g.group(1)) if g else None
    try:
        du = shutil.disk_usage(root if root.exists() else Path.home())
        s["disk_free_gb"] = round(du.free / 2**30, 1)
    except OSError:
        s["disk_free_gb"] = None
    th = _out(["pmset", "-g", "therm"])
    s["thermal"] = "nominal" if not th or ("No thermal warning" in th and "No performance warning" in th) else ("warning: " + " ".join(l.strip() for l in th.splitlines() if "level" in l.lower())[:160])
    b = _out(["pmset", "-g", "batt"])
    s["on_battery"] = "Battery Power" in b
    pct = re.search(r"(\d+)%", b)
    s["battery_pct"] = int(pct.group(1)) if pct else None
    idle = re.search(r'"HIDIdleTime" = (\d+)', _out(["ioreg", "-c", "IOHIDSystem"]))
    s["idle_s"] = round(int(idle.group(1)) / 1e9, 1) if idle else None
    try:
        s["ollama_loaded"] = [m.get("name") for m in _ollama_call("/api/ps", timeout=1).get("models", [])]
    except Exception:  # noqa: BLE001
        s["ollama_loaded"] = None
    return s


def _ollama_call(path: str, body: dict | None = None, timeout: float = 30):
    req = urllib.request.Request("http://127.0.0.1:11434" + path, data=None if body is None else json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST" if body is not None else "GET")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
        return json.loads(raw) if raw else {}


def research_usage_gb(path: Path) -> float:
    total = 0
    if path.is_dir():
        for p in path.rglob("*"):
            try:
                if p.is_file():
                    total += p.stat().st_size
            except OSError:
                pass
    return round(total / 2**30, 3)


TEMP_PATTERNS = ("lowres.*", "audio.*", "audio16k.wav", "audio22k.wav", "*.part", "*.ytdl", "*.tmp")


KEEP_SUFFIXES = {".json", ".md", ".jpg", ".txt"}


def cleanup_temp(path: Path, older_than_s: float = 0, clock=time.time) -> int:
    """Delete leftover downloads/intermediate audio under the research tree. Returns bytes freed."""
    freed = 0
    if not path.is_dir():
        return 0
    for pat in TEMP_PATTERNS:
        for p in path.rglob(pat):
            try:
                if p.suffix in KEEP_SUFFIXES:  # results (audio.json etc.) are never temp
                    continue
                if p.is_file() and clock() - p.stat().st_mtime >= older_than_s:
                    freed += p.stat().st_size; p.unlink()
            except OSError:
                pass
    return freed


_shared: ResourceManager | None = None


def shared(state_root) -> ResourceManager:
    global _shared
    if _shared is None:
        _shared = ResourceManager(state_root)
    return _shared
