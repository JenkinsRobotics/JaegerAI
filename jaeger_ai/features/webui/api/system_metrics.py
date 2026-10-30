"""Host metrics + service status for the unified UI Home (2026-10-30).

GET /v1/system/metrics -> {"now": sample, "history": [samples...]} for CPU/RAM/disk/GPU and
gateway latency. A daemon thread samples every INTERVAL seconds into a bounded ring buffer,
started lazily on first request, so charts have history on load. Read-only: nothing here
changes the machine. GPU utilisation comes from `ioreg` (Apple Silicon, no sudo); it is None
when unavailable. GET /v1/system/status -> gateway + Tailscale (read-only `tailscale status`).
"""
from __future__ import annotations

import json
import shutil
import subprocess
import threading
import time
import urllib.request
from collections import deque

INTERVAL = 10.0
HISTORY = 360  # one hour at 10s
GATEWAY = "http://127.0.0.1:33418/health"

_buf: deque = deque(maxlen=HISTORY)
_lock = threading.Lock()
_started = False


def _gpu() -> float | None:
    try:
        out = subprocess.run(["ioreg", "-r", "-d", "1", "-c", "IOAccelerator"], capture_output=True, text=True, timeout=3).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    marker = '"Device Utilization %"='
    i = out.find(marker)
    if i < 0:
        return None
    digits = "".join(ch for ch in out[i + len(marker):i + len(marker) + 4] if ch.isdigit())
    return float(digits) if digits else None


def gateway_probe() -> dict:
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(GATEWAY, timeout=3) as r:
            ok = 200 <= r.status < 300
    except Exception:  # noqa: BLE001 - any failure means unreachable
        return {"ok": False, "latency_ms": None}
    return {"ok": ok, "latency_ms": round((time.perf_counter() - t0) * 1000, 1)}


def sample() -> dict:
    try:
        import psutil
    except ImportError:
        psutil = None
    s: dict = {"t": time.time(), "gpu": _gpu(), "gateway": gateway_probe()}
    if psutil:
        vm = psutil.virtual_memory()
        du = psutil.disk_usage("/")
        s.update(cpu=psutil.cpu_percent(interval=None), mem=vm.percent, mem_used=vm.used, mem_total=vm.total,
                 disk=du.percent, disk_used=du.used, disk_total=du.total, cores=psutil.cpu_count())
    else:
        s.update(cpu=None, mem=None, disk=round(100 * shutil.disk_usage("/").used / shutil.disk_usage("/").total, 1))
    return s


def _loop() -> None:
    while True:
        try:
            snap = sample()
            with _lock:
                _buf.append(snap)
        except Exception:  # noqa: BLE001 - keep sampling
            pass
        time.sleep(INTERVAL)


def _ensure() -> None:
    global _started
    with _lock:
        if _started:
            return
        _started = True
    threading.Thread(target=_loop, name="jaeger-ui-metrics", daemon=True).start()


def metrics() -> dict:
    _ensure()
    with _lock:
        history = list(_buf)
    return {"now": history[-1] if history else sample(), "history": history, "interval": INTERVAL, "source": "psutil+ioreg"}


def tailscale() -> dict:
    exe = shutil.which("tailscale") or "/opt/homebrew/bin/tailscale"
    try:
        out = subprocess.run([exe, "status", "--json"], capture_output=True, text=True, timeout=4)
        d = json.loads(out.stdout or "{}")
    except (OSError, subprocess.SubprocessError, ValueError):
        return {"available": False}
    me = d.get("Self") or {}
    peers = d.get("Peer") or {}
    return {"available": True, "state": d.get("BackendState"), "host": me.get("HostName"), "online": bool(me.get("Online")),
            "peers": len(peers), "peers_online": sum(1 for p in peers.values() if p.get("Online"))}


def status() -> dict:
    return {"gateway": gateway_probe(), "tailscale": tailscale()}
