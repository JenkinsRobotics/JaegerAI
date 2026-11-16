"""Live task feed: what is running right now and its current step.

Fed by the Gateway event bus (the same stream the UI's live trace reads):
``turn.start`` opens a row, ``tool.started`` / ``turn.progress`` move its
step, ``turn.finish`` / ``turn.failed`` close it. Two consumers:

* ``GET /v1/live/tasks`` — the Mac app (JaegerShell) polls this for the menu
  bar progress state, the running-task list and its in-place notification.
* Step-by-step web push to the phone: started (once a turn runs past
  ``START_AFTER_S``), throttled progress milestones, then done/failed. Every
  push for one turn reuses the tag ``task-<request_id>`` so the phone replaces
  the notification instead of stacking. A turn that got progress pushes is
  marked so the generic "reply ready" push does not duplicate its done push.

Background turns (skill review, heartbeat, reflection) are listed for the Mac
menu but never pushed.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any

from aiohttp import web

logger = logging.getLogger(__name__)

START_AFTER_S = 20.0        # a turn this long gets a "started" push
MILESTONE_EVERY_S = 60.0    # at most one progress push per minute per turn
RECENT_KEEP_S = 120.0       # finished rows stay visible this long
MAX_STEP_CHARS = 120


def _clip(text: Any, n: int = MAX_STEP_CHARS) -> str:
    s = " ".join(str(text or "").split())
    return s if len(s) <= n else s[: n - 1] + "…"


_TOOL_WORDS = {
    "web_search": "Searching the web", "web_extract": "Reading a web page", "terminal": "Running a command",
    "read_file": "Reading a file", "write_file": "Writing a file", "patch": "Editing a file",
    "search_files": "Searching files", "get_events": "Checking the calendar", "list_mail": "Checking mail",
    "read_mail": "Reading mail", "call_agent": "Asking a teammate", "delegate_task": "Starting a helper",
    "browser_navigate": "Opening a page", "memory": "Updating memory", "recall": "Recalling memory",
    "schedule_prompt": "Scheduling", "system_control": "Controlling the Mac", "mac_status": "Checking the Mac",
}


def step_for_tool(tool: str) -> str:
    tool = str(tool or "")
    return _TOOL_WORDS.get(tool) or (f"Using {tool}" if tool else "Working")


class LiveTasks:
    def __init__(self, gateway, *, clock=time.time, sender=None):
        self.gw = gateway
        self.clock = clock
        self._sender = sender
        self._lock = threading.RLock()
        self.running: dict[str, dict] = {}
        self.recent: dict[str, dict] = {}
        self.pushed: set[str] = set()   # request ids that got a progress push
        self.seq = 0

    # ── event bus observer (cheap; network goes to a thread) ──
    def observe(self, evt) -> None:
        name = getattr(evt, "event", "") or ""
        if name not in ("turn.start", "tool.started", "turn.progress", "turn.finish", "turn.failed"):
            return
        data = getattr(evt, "data", {}) or {}
        if data.get("replayed"):
            return
        rid = str(data.get("request_id") or "")
        sid = str(getattr(evt, "session_id", "") or data.get("session_id") or "")
        now = float(getattr(evt, "timestamp", 0) or self.clock())
        try:
            if name == "turn.start":
                self._start(rid or str(data.get("turn_id") or ""), sid, data, now)
            elif name == "tool.started":
                self._step(rid, step_for_tool(data.get("tool")), now, tool=True)
            elif name == "turn.progress":
                msg = data.get("message") or data.get("text")
                if msg and str(data.get("channel") or "commentary") == "commentary":
                    self._step(rid, _clip(msg), now)
            else:
                self._finish(rid, sid, name == "turn.failed", data, now)
        except Exception:  # noqa: BLE001 — never break the event bus
            logger.warning("live task tracking failed for %s", name, exc_info=True)

    def _background(self, sid: str, rid: str) -> bool:
        if sid.startswith(("cron:", "heartbeat", "skill-review")) or rid.startswith(("skill-review", "reflect")):
            return not sid.startswith("cron:")  # scheduled jobs are real work for the owner
        disp = getattr(self.gw, "push_dispatcher", None)
        if disp is not None and rid:
            try:
                return bool(disp._is_background(disp._request_meta(rid)))
            except Exception:  # noqa: BLE001
                return False
        return False

    def _title(self, sid: str, data: dict) -> str:
        if sid.startswith("cron:"):
            return "⏰ " + (sid.split(":", 1)[1] or "Scheduled job")
        try:
            sess = self.gw.store.get_session(sid) or {}
            t = str(sess.get("title") or "").strip()
            if t and t.lower() not in {"new chat", "untitled"}:
                return _clip(t, 80)
        except Exception:  # noqa: BLE001
            pass
        return _clip(data.get("text") or "Jaeger task", 80)

    def _start(self, rid: str, sid: str, data: dict, now: float) -> None:
        if not rid:
            return
        row = {"request_id": rid, "session_id": sid, "title": self._title(sid, data), "step": "Starting",
               "steps": 0, "started_at": now, "updated_at": now, "status": "running",
               "background": self._background(sid, rid), "url": f"/chat/{sid}" if sid else "/",
               "_pushed_at": 0.0}
        with self._lock:
            self.running[rid] = row
            self.seq += 1

    def _step(self, rid: str, step: str, now: float, tool: bool = False) -> None:
        with self._lock:
            row = self.running.get(rid)
            if row is None:
                return
            row["step"] = step
            row["steps"] += 1 if tool else 0
            row["updated_at"] = now
            self.seq += 1

    def _finish(self, rid: str, sid: str, failed: bool, data: dict, now: float) -> None:
        with self._lock:
            row = self.running.pop(rid, None)
            if row is None:
                return
            row.update(status="failed" if failed else "done", updated_at=now, finished_at=now,
                       step="Failed" if failed else "Done",
                       result=_clip(data.get("error") if failed else (data.get("output") or data.get("text")), 200))
            self.recent[rid] = row
            self.seq += 1
        if rid in self.pushed:
            self._push(row, final=True)

    # ── phone push (started → milestones → done) ──
    def tick(self) -> None:
        now = self.clock()
        with self._lock:
            for rid, row in list(self.recent.items()):
                if now - float(row.get("finished_at") or now) > RECENT_KEEP_S:
                    self.recent.pop(rid, None)
                    self.pushed.discard(rid)
            due = []
            for rid, row in self.running.items():
                if row["background"] or now - row["started_at"] < START_AFTER_S:
                    continue
                if rid not in self.pushed or now - row["_pushed_at"] >= MILESTONE_EVERY_S:
                    due.append(row)
        for row in due:
            self._push(row)

    def _push(self, row: dict, final: bool = False) -> None:
        rid = row["request_id"]
        first = rid not in self.pushed
        with self._lock:
            self.pushed.add(rid)
            row["_pushed_at"] = self.clock()
        elapsed = int((row.get("finished_at") or self.clock()) - row["started_at"])
        if final:
            title = ("Failed: " if row["status"] == "failed" else "Done: ") + row["title"]
            body = row.get("result") or ("Open the chat to see why." if row["status"] == "failed" else "Tap to see the result")
        else:
            title = ("Started: " if first else "Working: ") + row["title"]
            body = f"{row['step']} · step {row['steps']} · {elapsed // 60}m {elapsed % 60}s"
        payload = {"v": 1, "id": f"task-{rid}", "type": "progress", "title": _clip(title, 110),
                   "body": _clip(body, 200), "url": row["url"] + ("?src=push" if "?" not in row["url"] else ""),
                   "tag": f"task-{rid}"[:60], "silent": (not first and not final), "privacy": "full"}
        threading.Thread(target=self._send, args=(payload,), daemon=True, name="jaeger-live-push").start()

    def _send(self, payload: dict) -> None:
        try:
            if self._sender is not None:
                self._sender(payload)
                return
            from . import push_routes, webpush
            if not webpush.list_subscriptions():
                return
            disp = getattr(self.gw, "push_dispatcher", None)
            out = webpush.send(payload, subject=push_routes._subject(), urgency="normal", ttl=600,
                               poster=getattr(disp, "poster", None))
            logger.info("live push %s %r delivered=%s", payload.get("tag"), payload.get("title"), out.get("delivered"))
        except Exception:  # noqa: BLE001
            logger.warning("live task push failed", exc_info=True)

    def snapshot(self) -> dict:
        now = self.clock()
        def view(r: dict) -> dict:
            out = {k: v for k, v in r.items() if not k.startswith("_")}
            out["elapsed_s"] = round((r.get("finished_at") or now) - r["started_at"], 1)
            return out
        with self._lock:
            running = sorted((view(r) for r in self.running.values()), key=lambda r: r["started_at"])
            recent = sorted((view(r) for r in self.recent.values()), key=lambda r: -r["finished_at"])
            return {"seq": self.seq, "running": running, "recent": recent[:10],
                    "busy": any(not r["background"] for r in running), "count": len(running)}


def register(gateway) -> LiveTasks:
    live = LiveTasks(gateway)
    gateway.live_tasks = live
    add = getattr(gateway.event_bus, "add_observer", None)
    if add:
        add(live.observe)
    stop = threading.Event()

    def loop() -> None:
        while not stop.wait(5.0):
            try:
                live.tick()
            except Exception:  # noqa: BLE001
                logger.warning("live task tick failed", exc_info=True)

    async def _start(_app):
        threading.Thread(target=loop, daemon=True, name="jaeger-live-tasks").start()

    async def _stop(_app):
        stop.set()

    gateway.app.on_startup.append(_start)
    gateway.app.on_cleanup.append(_stop)

    async def tasks(request: web.Request) -> web.Response:
        return web.json_response(live.snapshot())

    gateway.app.router.add_get("/v1/live/tasks", tasks)
    return live
