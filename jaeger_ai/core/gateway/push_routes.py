"""Web Push subscriptions and the server-side sender (APPROVALS-NOTIFICATIONS-SPEC §5).

Routes (owner/admin auth from caller_auth):
  GET    /v1/push/vapid-public-key      {public_key}  (applicationServerKey)
  GET    /v1/push/subscriptions         {subscriptions:[{id, device_label, platform, standalone, push_service, ...}]}
  POST   /v1/push/subscriptions         {endpoint, keys{p256dh,auth}, device_label, platform, standalone} → 201/200
  DELETE /v1/push/subscriptions/{id}
  POST   /v1/push/test                  {subscription_id?}
  GET    /v1/push/queue                 held/batched counts (diagnostics, no payload text)
  POST   /v1/push/job-events            {task_id, state, title?}  (WebUI jobs runner → job.updated event)
  POST   /v1/push/presence              {client_id, visible}  (an open app window the owner is looking at)

Policy (an event-bus observer enqueues; a 60 s ticker sends, so publishing never blocks):
  * categories/quiet hours/preview/mute come from ``GET/PATCH /v1/notifications`` preferences.
  * approval critical → immediate, always (breaks quiet hours); high → immediate (urgent category).
  * approval medium/low → batched, one push per 30 min ("3 low-risk approvals"; a lone item is sent as itself).
  * quiet hours hold everything except ``allow`` (critical; and items expiring inside quiet hours,
    which notify 30 min before expiry); a morning summary is sent when quiet hours end.
  * approval.resolved → silent replacement with the same tag, body "Resolved".
  * job/task failed or blocked → task_failed; handoff finished → bot_finished (in-app only by default).
  * scheduled job finished (cron:* session) → ``scheduled`` with the result; "nothing to report" replies stay quiet.
  * a long owner turn (>= LONG_TURN_S) that finishes while no app window is in use → ``replies_away``
    (ChatGPT-style "your reply is ready"); background/maintenance turns never push.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import quote
from zoneinfo import ZoneInfo

from aiohttp import web

from . import webpush

logger = logging.getLogger(__name__)
KEY = "push:queue"
BATCH_S = 30 * 60
EXPIRY_LEAD_S = 30 * 60
TICK_S = 60
STALE_S = 24 * 3600
MAX_LANE = 50
LONG_TURN_S = 20.0      # owner turns at least this long notify when the owner is away
PRESENCE_S = 45.0       # an app window counts as "in use" this long after its last heartbeat
_QUIET_REPLIES = ("HEARTBEAT_OK", "NO_REPLY", "NOTHING_TO_REPORT")
_BACKGROUND_SOURCES = frozenset({"cron", "memory_upkeep", "skill_review", "initiative", "sensor", "heartbeat"})


def _has_subscribers() -> bool:
    try:
        return bool(webpush.list_subscriptions())
    except Exception:  # noqa: BLE001
        return False
def _subject() -> str:
    """VAPID ``sub``: Apple rejects localhost addresses, so prefer the app's own https origin."""
    env = os.environ.get("JAEGER_PUSH_SUBJECT", "").strip()
    if env.startswith(("mailto:", "https://")):
        return env
    for s in webpush.list_subscriptions():
        origin = str(s.get("origin") or "")
        if origin.startswith("https://"):
            return origin
    return "mailto:jaeger-push@users.noreply.github.com"


def _quiet_reply(text: str) -> bool:
    head = text.strip().strip("`*_ .").upper()
    return any(head == q or head.startswith(q + " ") or head.endswith(q) for q in _QUIET_REPLIES)


def _session_url(session_id: str | None) -> str:
    return f"/?session={quote(session_id, safe='')}&src=push" if session_id else "/?src=push"


# ── preferences / quiet hours ────────────────────────────────────────
def _prefs(store) -> dict:
    from jaeger_ai.features.notifications.routes import settings
    with store._immediate() as conn:
        return settings(conn)


def _parse(hhmm: str) -> tuple[int, int]:
    h, m = hhmm.split(":")
    return int(h), int(m)


def quiet_window(q: dict, now: float) -> tuple[float, float] | None:
    """(start, end) epoch of the quiet window containing ``now``, else None."""
    if not q.get("enabled", True):
        return None
    tz = ZoneInfo(q.get("tz") or "America/Los_Angeles")
    local = datetime.fromtimestamp(now, tz)
    (sh, sm), (eh, em) = _parse(q["start"]), _parse(q["end"])
    for day in (local.date() - timedelta(days=1), local.date()):
        start = datetime(day.year, day.month, day.day, sh, sm, tzinfo=tz)
        end = datetime(day.year, day.month, day.day, eh, em, tzinfo=tz)
        if end <= start:
            end += timedelta(days=1)
        if start.timestamp() <= now < end.timestamp():
            return start.timestamp(), end.timestamp()
    return None


# ── classification ───────────────────────────────────────────────────
def classify(event: str, data: dict, store=None) -> dict | None:
    """Map a gateway event to a push candidate, or None."""
    if event == "approval.request":
        from .approvals_inbox import project
        row = data.get("approval") if isinstance(data.get("approval"), dict) else data
        if not row.get("approval_id"):
            return None
        stored = store.get_approval(row["approval_id"]) if store is not None else None
        if stored is not None and stored.get("status") != "pending":
            return None
        row = stored or {"options": [], "status": "pending", "metadata": {}, "created_at": time.time(), **row}
        item = project(row)
        cat = ("spend_send" if item["type"] in ("spend", "send") else
               "design_reviews" if item["type"] == "design_review" else
               "approvals_urgent" if item["risk"] in ("high", "critical") else "approvals_routine")
        return {"kind": "approval", "category": cat, "id": item["approval_id"], "risk": item["risk"],
                "type": item["type"], "title_text": item["title"], "agent_id": item["agent_id"],
                "expires_at": item["expires_at"], "session_id": item.get("session_id")}
    if event == "notification.proactive" and data.get("push"):
        # Droid mode said Matthew is away (or not alone): his phone gets it instead of the room.
        rid = str(data.get("request_id") or "")
        return {"kind": "proactive", "category": "proactive_away", "id": f"proactive:{rid}", "risk": "low",
                "title_text": "Jaeger", "body": str(data.get("body") or ""), "session_id": data.get("session_id"),
                "tag": "proactive"}
    if event == "approval.resolved" and data.get("approval_id"):
        return {"kind": "resolved", "category": None, "id": data["approval_id"]}
    if event in ("task.updated", "job.updated"):
        ent = data.get("task") if isinstance(data.get("task"), dict) else data
        state = ent.get("state") or ent.get("status")
        if event == "job.updated" and state in ("done", "done_with_errors"):
            return {"kind": "finished", "category": "bot_finished", "id": str(ent.get("task_id") or ""), "risk": "low",
                    "title_text": ent.get("title") or "Job finished", "agent_id": ent.get("agent_id")}
        if state in ("failed", "blocked", "needs_owner", "execution_unknown", "stuck", "error", "runner_down"):
            return {"kind": "task", "category": "task_failed", "id": str(ent.get("task_id") or ent.get("id") or ""),
                    "risk": "medium", "title_text": ent.get("title") or "A task needs attention", "state": state,
                    "agent_id": ent.get("agent_id")}
        return None
    if event == "agent.handoff.finished":
        h = data.get("handoff") if isinstance(data.get("handoff"), dict) else data
        if h.get("status") in ("completed", "completed_verified"):
            return {"kind": "finished", "category": "bot_finished", "id": str(h.get("id") or ""), "risk": "low",
                    "title_text": (h.get("result") or {}).get("summary") or "Delegated work finished",
                    "agent_id": h.get("to_agent_id")}
        if h.get("status") in ("failed", "blocked"):
            return {"kind": "task", "category": "task_failed", "id": str(h.get("id") or ""), "risk": "medium",
                    "title_text": "Delegated work failed", "agent_id": h.get("to_agent_id")}
    return None


def build_payload(c: dict, prefs: dict, badge: int) -> dict:
    """Spec §5 payload. ``title_only`` (default) and ``hidden`` never carry details."""
    preview = prefs.get("preview", "title_only")
    if c["kind"] == "approval":
        title = f"Approval needed · {c['risk'].capitalize()}"
        url = _session_url(c.get("session_id"))
    elif c["kind"] == "batch":
        title, url = c["title"], "/?src=push"
    elif c["kind"] == "summary":
        title, url = "While quiet hours were on", "/?src=push"
    elif c["kind"] == "resolved":
        title, url = "Resolved", "/?src=push"
    elif c["kind"] == "proactive":
        title, url = "Jaeger has something for you", _session_url(c.get("session_id"))
    elif c["kind"] in ("scheduled", "reply"):
        title, url = str(c.get("title_text") or "Jaeger"), _session_url(c.get("session_id"))
    else:
        title = "Task needs attention" if c["kind"] == "task" else "Work finished"
        url = "/work?src=push"
    body = ""
    if preview == "full":
        body = c.get("body") or (f"{c.get('agent_id')}: {c.get('title_text')}" if c.get("agent_id") else str(c.get("title_text") or ""))
    elif c["kind"] in ("batch", "summary", "resolved"):
        body = c.get("body") or ""
    elif c["kind"] == "scheduled":
        body = "Tap to see the result"
    elif c["kind"] == "reply":
        body = "Tap to read the reply"
    elif c["kind"] == "proactive":
        body = "Tap to read it"
    if preview == "hidden":
        title, body = "Jaeger", ""
    out = {"v": 1, "id": c.get("id"), "type": c["kind"], "kind": c.get("type"), "risk": c.get("risk"),
           "title": title, "body": body[:240], "agent_id": c.get("agent_id") if preview != "hidden" else None,
           "url": url, "tag": c.get("tag") or c.get("id") or c["kind"], "expires_at": c.get("expires_at"),
           "badge": badge, "privacy": preview, "silent": c["kind"] == "resolved"}
    return {k: v for k, v in out.items() if v is not None}


# ── dispatcher ───────────────────────────────────────────────────────
class PushDispatcher:
    def __init__(self, gateway, *, poster=None, clock=time.time):
        self.gw, self.poster, self.clock = gateway, poster, clock
        self._lock = threading.RLock()
        self._seen: dict[int, float] = {}
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._turn_started: dict[str, float] = {}
        self._presence: dict[str, float] = {}

    # ── owner presence (an app window in use suppresses "reply ready" pushes) ──
    def note_presence(self, client_id: str, visible: bool) -> None:
        now = self.clock()
        with self._lock:
            if visible:
                self._presence[client_id] = now
            else:
                self._presence.pop(client_id, None)
            for k, t in list(self._presence.items()):
                if now - t > PRESENCE_S * 4:
                    self._presence.pop(k, None)

    def owner_watching(self) -> bool:
        now = self.clock()
        return any(now - t <= PRESENCE_S for t in list(self._presence.values()))

    def _request_meta(self, rid: str) -> dict:
        try:
            with self.gw.store._get_conn() as conn:
                row = conn.execute("SELECT * FROM client_requests WHERE request_id=?", (rid,)).fetchone()
        except Exception:  # noqa: BLE001
            return {}
        if row is None:
            return {}
        out = {"created_at": row["created_at"]}
        for col in ("requested_json", "execution_json"):
            try:
                out[col] = json.loads(row[col] or "{}") if col in row.keys() else {}
            except (TypeError, ValueError):
                out[col] = {}
        return out

    @staticmethod
    def _is_background(meta: dict) -> bool:
        def walk(v) -> bool:
            if isinstance(v, dict):
                if v.get("background") is True or str(v.get("source") or "") in _BACKGROUND_SOURCES:
                    return True
                return any(walk(x) for x in v.values())
            if isinstance(v, list):
                return any(walk(x) for x in v)
            return False
        return walk(meta.get("requested_json")) or walk(meta.get("execution_json"))

    def _turn_candidate(self, evt) -> dict | None:
        sid = str(getattr(evt, "session_id", "") or "")
        data = getattr(evt, "data", {}) or {}
        name = getattr(evt, "event", "")
        rid = str(data.get("request_id") or "")
        started = self._turn_started.pop(rid, None)
        text = str(data.get("output") or data.get("text") or "").strip()
        if sid.startswith("cron:"):
            job = sid.split(":", 1)[1] or "Scheduled job"
            if name == "turn.failed":
                return {"kind": "task", "category": "task_failed", "id": rid or job, "risk": "medium",
                        "title_text": f"Scheduled job failed: {job}", "state": "failed", "session_id": sid}
            if not text or _quiet_reply(text):
                return None
            return {"kind": "scheduled", "category": "scheduled", "id": rid or job, "risk": "low",
                    "title_text": f"⏰ {job}", "body": text, "session_id": sid, "tag": f"schedule-{job}"[:60]}
        if not rid or data.get("replayed"):
            return None
        live = getattr(self.gw, "live_tasks", None)
        if live is not None and rid in getattr(live, "pushed", ()):
            return None  # live_tasks already sent started/progress and sends the done push on the same tag
        meta = self._request_meta(rid)
        if self._is_background(meta):
            return None
        finished = float(getattr(evt, "timestamp", 0) or self.clock())
        timing = data.get("timing") if isinstance(data.get("timing"), dict) else {}
        duration = None
        if isinstance(timing.get("turn_finish_ms"), (int, float)) and timing["turn_finish_ms"] > 0:
            duration = float(timing["turn_finish_ms"]) / 1000.0
        elif started:
            duration = finished - started
        elif meta.get("created_at"):
            duration = finished - float(meta["created_at"])
        if duration is None or duration < LONG_TURN_S or self.owner_watching():
            return None
        title = "Jaeger"
        try:
            sess = self.gw.store.get_session(sid) or {}
            title = str(sess.get("title") or "").strip() or title
        except Exception:  # noqa: BLE001
            pass
        if name == "turn.failed":
            return {"kind": "reply", "category": "replies_away", "id": rid, "risk": "low", "session_id": sid,
                    "title_text": title, "body": "Jaeger couldn't finish that. Open the chat to see why.",
                    "tag": f"reply-{sid}"[:60]}
        if not text:
            return None
        return {"kind": "reply", "category": "replies_away", "id": rid, "risk": "low", "session_id": sid,
                "title_text": title, "body": text, "tag": f"reply-{sid}"[:60]}

    # persistent queue in schema_meta (no secrets in it)
    def _load(self) -> dict:
        with self.gw.store._immediate() as conn:
            row = conn.execute("SELECT value FROM schema_meta WHERE key=?", (KEY,)).fetchone()
        q = json.loads(row[0]) if row else {}
        q.setdefault("now", []); q.setdefault("batch", []); q.setdefault("held", []); q.setdefault("scheduled", [])
        q.setdefault("pushed_tags", []); q.setdefault("batch_since", None); q.setdefault("quiet_until", None)
        # Stale items are noise, not news: drop anything queued more than a day
        # ago (or with no queue time at all) and cap each lane.
        cutoff = self.clock() - STALE_S
        for k in ("now", "batch", "held", "scheduled"):
            q[k] = [x for x in q[k] if float(x.get("queued_at") or 0) >= cutoff][-MAX_LANE:]
        if not q["batch"]:
            q["batch_since"] = None
        if not q["held"]:
            q["quiet_until"] = None
        return q

    def _save(self, q: dict) -> None:
        q["pushed_tags"] = q["pushed_tags"][-500:]
        with self.gw.store._immediate() as conn:
            conn.execute("INSERT INTO schema_meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                         (KEY, json.dumps(q)))

    def observe(self, evt) -> None:
        """Event-bus observer: classify and enqueue only (cheap; no network)."""
        eid = getattr(evt, "event_id", None)
        if eid is not None:
            if eid in self._seen:
                return
            self._seen[eid] = self.clock()
            if len(self._seen) > 2000:
                for k in sorted(self._seen)[:1000]:
                    self._seen.pop(k, None)
        name = getattr(evt, "event", "")
        if name == "turn.start":
            rid = str((getattr(evt, "data", {}) or {}).get("request_id") or "")
            if rid:
                self._turn_started[rid] = float(getattr(evt, "timestamp", 0) or self.clock())
                if len(self._turn_started) > 500:
                    for k in list(self._turn_started)[:250]:
                        self._turn_started.pop(k, None)
            return
        if name in ("turn.finish", "turn.failed"):
            try:
                c = self._turn_candidate(evt)
            except Exception:  # noqa: BLE001
                logger.warning("push turn classification failed", exc_info=True)
                c = None
        else:
            c = classify(name, getattr(evt, "data", {}) or {}, self.gw.store)
        if c and c.get("kind") in ("approval", "finished"):
            try:  # wake event-driven reflection (heartbeat) for salient moments
                from jaeger_ai.core.runtime import reflection_triggers
                reflection_triggers.write("approval_waiting" if c["kind"] == "approval" else "job_finished",
                                          title=str(c.get("title_text") or "")[:80], risk=c.get("risk"))
            except Exception:  # noqa: BLE001
                pass
        if c:
            try:
                self.enqueue(c)
            except Exception:  # noqa: BLE001
                logger.warning("push enqueue failed", exc_info=True)

    def enqueue(self, c: dict) -> str:
        now = self.clock()
        if c.get("kind") != "resolved" and not _has_subscribers():
            return "drop"  # no device to push to; the in-app inbox still has it
        c = {**c, "queued_at": now}
        with self._lock:
            prefs = _prefs(self.gw.store)
            q = self._load()
            route = self._route(c, prefs, q, now)
            if route == "now":
                q["now"].append(c)
            elif route == "batch":
                q["batch"].append(c); q["batch_since"] = q["batch_since"] or now
            elif route == "held":
                q["held"].append(c)
            elif route.startswith("at:"):
                q["scheduled"].append({**c, "send_at": float(route[3:])})
            self._save(q)
        if route == "now":
            self._wake.set()  # deliver now, not on the next minute tick
        return route

    def _route(self, c: dict, prefs: dict, q: dict, now: float) -> str:
        if c["kind"] == "approval" and (c["id"] in q["pushed_tags"] or any(
                x.get("id") == c["id"] for k in ("now", "batch", "held", "scheduled") for x in q[k])):
            return "drop"  # same approval on the child and parent streams
        if c["kind"] == "resolved":
            for k in ("now", "batch", "held", "scheduled"):
                q[k] = [x for x in q[k] if not (x["kind"] == "approval" and x.get("id") == c["id"])]
            return "now" if c["id"] in q["pushed_tags"] else "drop"
        if not prefs.get("enabled", True) or c.get("agent_id") in prefs.get("muted_agent_ids", []):
            return "drop"
        cat = prefs["categories"].get(c["category"]) or {}
        if not cat.get("push"):
            return "drop"
        qh = prefs["quiet_hours"]
        win = quiet_window(qh, now)
        if c.get("risk") == "critical":
            return "now"
        if win:
            if c["category"] == "approvals_urgent" and cat.get("breaks_quiet_hours") and "critical" not in qh["allow"]:
                return "now"
            exp = c.get("expires_at")
            if "expiring" in qh["allow"] and exp and exp < win[1]:
                return f"at:{max(now, exp - EXPIRY_LEAD_S)}"
            q["quiet_until"] = win[1]
            return "held"
        if c["category"] == "approvals_routine":
            return "batch"
        return "now"

    def _badge(self) -> int:
        try:
            return len(self.gw.store.list_pending_approvals())
        except Exception:  # noqa: BLE001
            return 0

    def _send(self, c: dict, prefs: dict, q: dict) -> dict:
        payload = build_payload(c, prefs, self._badge())
        urgency = "high" if c.get("risk") in ("high", "critical") else "low" if c["kind"] == "resolved" else "normal"
        out = webpush.send(payload, subject=_subject(), urgency=urgency, poster=self.poster)
        if c["kind"] == "approval":
            q["pushed_tags"].append(c["id"])
            try:
                from .approvals_inbox import audit
                audit(self.gw.store, c["id"], "pushed", actor="system", data={"delivered": out["delivered"]})
            except Exception:  # noqa: BLE001
                pass
        return out

    def tick(self) -> dict:
        """Send due items. Safe to call any time (tests call it directly)."""
        now = self.clock()
        sent = 0
        with self._lock:
            prefs = _prefs(self.gw.store)
            q = self._load()
            for c in q["now"]:
                self._send(c, prefs, q); sent += 1
            q["now"] = []
            due = [c for c in q["scheduled"] if c["send_at"] <= now]
            q["scheduled"] = [c for c in q["scheduled"] if c["send_at"] > now]
            for c in due:
                self._send(c, prefs, q); sent += 1
            if q["batch"] and q["batch_since"] and now - q["batch_since"] >= BATCH_S:
                items, q["batch"], q["batch_since"] = q["batch"], [], None
                if len(items) == 1:
                    self._send(items[0], prefs, q)
                else:
                    self._send({"kind": "batch", "id": "approvals-batch", "tag": "approvals-batch", "risk": "low",
                                "title": f"{len(items)} low-risk approvals", "body": "Review them together in Work › Approvals"},
                               prefs, q)
                sent += 1
            if q["held"] and not quiet_window(prefs["quiet_hours"], now):
                held, q["held"], q["quiet_until"] = q["held"], [], None
                approvals = sum(1 for c in held if c["kind"] == "approval")
                others = len(held) - approvals
                parts = ([f"{approvals} approval{'s' if approvals != 1 else ''} waiting"] if approvals else []) + \
                        ([f"{others} update{'s' if others != 1 else ''}"] if others else [])
                self._send({"kind": "summary", "id": "morning-summary", "tag": "morning-summary", "risk": "low",
                            "body": " · ".join(parts)}, prefs, q)
                sent += 1
            self._save(q)
        return {"sent": sent}

    def discard_undeliverable(self) -> None:
        """No push subscription: nothing can be delivered, so don't let a queue pile up."""
        with self._lock:
            q = self._load()
            if any(q[k] for k in ("now", "batch", "held", "scheduled")):
                for k in ("now", "batch", "held", "scheduled"):
                    q[k] = []
                q["batch_since"] = q["quiet_until"] = None
                self._save(q)

    def status(self) -> dict:
        q = self._load()
        return {k: len(q[k]) for k in ("now", "batch", "held", "scheduled")} | {"batch_since": q["batch_since"],
                                                                                "quiet_until": q["quiet_until"]}

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        def loop():
            while not self._stop.is_set():
                self._wake.wait(TICK_S)
                self._wake.clear()
                if self._stop.is_set():
                    break
                try:
                    if webpush.list_subscriptions():
                        self.tick()
                    else:
                        self.discard_undeliverable()
                except Exception:  # noqa: BLE001
                    logger.warning("push tick failed", exc_info=True)
        self._thread = threading.Thread(target=loop, name="jaeger-push", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()


# ── routes ───────────────────────────────────────────────────────────
def register(gateway) -> PushDispatcher:
    dispatcher = PushDispatcher(gateway)
    gateway.push_dispatcher = dispatcher
    add = getattr(gateway.event_bus, "add_observer", None)
    if add:
        add(dispatcher.observe)

    async def _start(_app):
        dispatcher.start()

    async def _stop(_app):
        dispatcher.stop()

    gateway.app.on_startup.append(_start)
    gateway.app.on_cleanup.append(_stop)

    async def public_key(request):
        return web.json_response({"public_key": webpush.vapid_public_key()})

    async def list_subs(request):
        return web.json_response({"subscriptions": [webpush.public_view(s) for s in webpush.list_subscriptions()]})

    async def add_sub(request):
        try:
            body = await request.json()
            if not isinstance(body, dict):
                raise ValueError
            view, created = webpush.add_subscription(body)
        except webpush.PushError as exc:
            return web.json_response({"error": str(exc)}, status=400)
        except (ValueError, TypeError):
            return web.json_response({"error": "JSON object required"}, status=400)
        return web.json_response({"subscription": view}, status=201 if created else 200)

    async def del_sub(request):
        if not webpush.remove_subscription(request.match_info["id"]):
            return web.json_response({"error": "Subscription not found"}, status=404)
        return web.json_response({"ok": True})

    async def test(request):
        body = await request.json() if request.can_read_body else {}
        sid = (body or {}).get("subscription_id")
        if sid and not any(s.get("id") == sid for s in webpush.list_subscriptions()):
            return web.json_response({"error": "Subscription not found"}, status=404)
        import asyncio
        out = await asyncio.to_thread(webpush.send, {"v": 1, "type": "test", "title": "Jaeger test notification",
                                                     "body": "Push is working", "url": "/settings/notifications",
                                                     "tag": "push-test"},
                                      subject=_subject(), only=sid, poster=dispatcher.poster)
        return web.json_response(out)

    async def presence(request):
        try:
            body = await request.json()
            cid = str(body.get("client_id") or "").strip()[:64]
            if not cid:
                raise ValueError
        except (ValueError, TypeError, AttributeError):
            return web.json_response({"error": "client_id is required"}, status=400)
        dispatcher.note_presence(cid, bool(body.get("visible")))
        return web.json_response({"ok": True, "watching": dispatcher.owner_watching()})

    async def job_event(request):
        """WebUI job runner → push: {task_id, state: done|done_with_errors|error|stuck|runner_down, title?}."""
        try:
            body = await request.json()
            tid, state = str(body["task_id"])[:120], str(body["state"])
            if state not in ("done", "done_with_errors", "error", "stuck", "runner_down", "cancelled"):
                raise ValueError
        except (ValueError, TypeError, KeyError):
            return web.json_response({"error": "task_id and a known state are required"}, status=400)
        evt = gateway.event_bus.publish("*", "job.updated", {"task": {"task_id": tid, "state": state,
                                                                     "title": str(body.get("title") or "")[:160]}})
        return web.json_response({"event_id": evt.event_id}, status=202)

    async def queue(request):
        return web.json_response(dispatcher.status())

    r = gateway.app.router
    r.add_get("/v1/push/vapid-public-key", public_key)
    r.add_get("/v1/push/subscriptions", list_subs)
    r.add_post("/v1/push/subscriptions", add_sub)
    r.add_delete("/v1/push/subscriptions/{id}", del_sub)
    r.add_post("/v1/push/test", test)
    r.add_post("/v1/push/presence", presence)
    r.add_get("/v1/push/queue", queue)
    r.add_post("/v1/push/job-events", job_event)
    return dispatcher
