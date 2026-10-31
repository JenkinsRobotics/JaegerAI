"""Jaeger 24/7 job runner (launchd: com.jenkinsrobotics.jaeger-jobs). Slow and steady beats fast.

- One instance (flock on <state>/jobs/runner.lock). Loopback only: it opens no ports; it talks to Ollama on 127.0.0.1.
- Queue in <state>/jobs/queue.json: [{"task_id", "target": "all" | n, "batch": 40, "priority": 5, "enabled": true}].
  Each job grows by `batch` videos at a time (playlist order). Every batch runs the normal per-video step order and
  phases, then rebuilds the style guide and KB, so both update incrementally every `batch` videos.
- Everything resumes from files on disk: a crash, kill -9, reboot or code update just means launchd starts us again.
- Heartbeat <state>/jobs/runner.json every `heartbeat_s`. A job whose progress hasn't moved for `stuck_minutes`
  is cancelled and retried with exponential backoff; if its thread won't stop, the process exits and launchd
  restarts it (KeepAlive + ThrottleInterval).
- Uses the shared resource manager: heavy steps wait while memory/GPU/thermal say no; phase-1 workers are 1 while
  Matthew is using the Mac and up to 3 when it has been idle.
- The inbox watcher stays off unless the queue item says "watch": true. Nothing is uploaded or messaged.
"""
from __future__ import annotations

import fcntl
import importlib.util
import json
import os
import signal
import sys
import threading
import time
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULTS = {"heartbeat_s": 30, "stuck_minutes": 90, "retry_backoff_min": [2, 60], "idle_workers": 3, "busy_workers": 1, "batch": 40}


def _load(name: str, file: str):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, HERE / file)
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


def _rj(p: Path, default=None):
    try:
        return json.loads(p.read_text("utf-8"))
    except (OSError, ValueError):
        return default


def _wj(p: Path, data) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), "utf-8")
    tmp.replace(p)


class Runner:
    def __init__(self, yt, state: Path, rm=None, clock=time.time, sleep=time.sleep, exit_fn=os._exit):
        self.yt, self.state, self.rm = yt, Path(state), rm
        self.clock, self.sleep, self.exit = clock, sleep, exit_fn
        self.dir = self.state / "jobs"
        self.started_at = clock()
        self.retries: dict = {}
        self.next_try: dict = {}
        self.events: list = []
        self.stop = threading.Event()

    # -- files --
    def config(self) -> dict:
        p = self.dir / "config.json"
        c = _rj(p)
        if c is None:
            _wj(p, DEFAULTS)
            c = {}
        return {**DEFAULTS, **c}

    def queue(self) -> list:
        q = _rj(self.dir / "queue.json", [])
        return sorted([x for x in q if isinstance(x, dict) and x.get("task_id")], key=lambda x: x.get("priority", 5))

    def log(self, msg: str) -> None:
        line = time.strftime("%Y-%m-%d %H:%M:%S") + " " + msg
        self.events = (self.events + [line])[-50:]
        print(line, flush=True)

    def heartbeat(self, active, owned, health="ok") -> None:
        _wj(self.dir / "runner.json", {"pid": os.getpid(), "at": self.clock(), "started_at": self.started_at, "active": active, "owned": owned,
                                         "health": health, "retries": self.retries, "next_try": self.next_try, "events": self.events[-20:],
                                         "service": "com.jenkinsrobotics.jaeger-jobs"})

    # -- one pass --
    def io_workers(self) -> int:
        c = self.config()
        try:
            snap = self.rm.snapshot() if self.rm else {}
            idle = snap.get("idle_s")
            user_s = self.rm.config()["user_active_idle_s"] if self.rm else 60
        except Exception:  # noqa: BLE001
            idle, user_s = None, 60
        return c["idle_workers"] if (idle is None or idle >= max(user_s, 300)) else c["busy_workers"]

    def tick(self) -> dict:
        c = self.config()
        active, owned, health = [], [], "ok"
        for item in self.queue():
            tid = item["task_id"]
            if not item.get("enabled", True):
                continue
            try:
                j = self.yt._job(tid)
            except Exception as exc:  # noqa: BLE001
                self.log(f"{tid}: no job ({exc})")
                continue
            owned.append(tid)
            running = tid in self.yt._running
            if running:
                active.append(tid)
                idle_for = self.clock() - self.yt.last_progress_at(j)
                if idle_for < 300:
                    self.retries.pop(tid, None)
                if idle_for > c["stuck_minutes"] * 60 and not j.get("paused"):
                    health = "stuck"
                    n = self.retries.get(tid, 0) + 1
                    self.retries[tid] = n
                    lo, hi = c["retry_backoff_min"]
                    self.next_try[tid] = self.clock() + min(lo * 2 ** (n - 1), hi) * 60
                    self.log(f"{tid}: stuck {idle_for / 60:.0f} min -> cancel, retry #{n} after backoff")
                    self.yt.cancel(tid)
                    t = self.yt._running.get(tid, {}).get("thread")
                    if t:
                        t.join(timeout=600)
                        if t.is_alive():
                            self.log(f"{tid}: thread won't stop -> exiting so launchd restarts the runner")
                            self.heartbeat(active, owned, "restarting")
                            self.exit(3)
                continue
            if self.clock() < self.next_try.get(tid, 0):
                health = "backoff" if health == "ok" else health
                continue
            if self.yt.batch_done(j) and j["style_guide"].get("status") == "done" and j.get("kb", {}).get("status") == "done":
                target = j.get("item_count") if item.get("target", "all") == "all" else int(item["target"])
                if target and len(j["videos"]) < target:
                    n = min(len(j["videos"]) + int(item.get("batch") or c["batch"]), int(target))
                    added = self.yt.extend(tid, n)
                    self.log(f"{tid}: batch done -> extended to {n} videos (+{added})")
                    if not added:
                        continue
                else:
                    if item.get("watch"):
                        self.yt.poll_new(tid)
                    continue
            r = self.yt.start(tid)
            if r.get("started"):
                self.log(f"{tid}: started ({len(self.yt._job(tid)['videos'])} videos, workers {self.io_workers()})")
                active.append(tid)
        self.heartbeat(active, owned, health)
        return {"active": active, "owned": owned, "health": health}

    def run(self) -> None:
        self.log(f"runner up (pid {os.getpid()})")
        while not self.stop.is_set():
            try:
                self.tick()
            except Exception:  # noqa: BLE001
                self.log("tick error: " + traceback.format_exc(limit=3).replace("\n", " | ")[-400:])
            self.stop.wait(self.config()["heartbeat_s"])


def main() -> int:
    ua = _load("_unified_api_runner", "unified_api.py")
    state = Path(ua.state_root())
    (state / "jobs").mkdir(parents=True, exist_ok=True)
    lock = open(state / "jobs" / "runner.lock", "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print("another job runner holds the lock; exiting", flush=True)
        time.sleep(30)
        return 0
    yt = ua._yt()
    rm = ua._rm()
    runner = Runner(yt, state, rm=rm)
    yt.bind(is_runner=True, io_workers=runner.io_workers)

    def term(*_):
        runner.log("SIGTERM: stopping after current steps (state is on disk)")
        runner.stop.set()
        for tid in list(yt._running):
            yt.cancel(tid)
    signal.signal(signal.SIGTERM, term)
    runner.run()
    for r in list(yt._running.values()):
        r["thread"].join(timeout=120)
    return 0


if __name__ == "__main__":
    sys.exit(main())
