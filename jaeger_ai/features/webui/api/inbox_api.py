"""WebUI (8790) side of the approvals inbox and notifications.

The Gateway owns approvals, audit, notification preferences, VAPID keys,
subscriptions and the push sender (core/gateway/approvals_inbox.py,
push_routes.py, webpush.py, features/notifications/routes.py). This module only:
  1. proxies the spec routes the existing WebUI proxy does not already cover
     (POST /v1/approvals/<suffix> is already proxied by routes.py):
       GET  /v1/approvals/counts, /v1/approvals/{id}/events
       GET/PATCH /v1/notifications
       GET/POST/DELETE /v1/push/...
  2. watches the WebUI 24/7 jobs runner (``unified_api.runner_status``) and
     forwards job finished / stuck / runner-down transitions to the Gateway
     (POST /v1/push/job-events), which applies categories and quiet hours.

"Stuck" = the runner tile's own rule: a running job with no progress for
60 min (``runner_status`` ``stuck``), which fires before the runner's 90 min
auto-retry; "runner down" = stale runner heartbeat (``health == down``).
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from pathlib import Path

POLL_S = 60
TERMINAL = ("done", "done_with_errors", "error", "cancelled")
_GET = re.compile(r"^/v1/(approvals/counts|approvals/[A-Za-z0-9_.:-]+/events|notifications|push/[a-z-]+)$")
_PUSH_WRITE = re.compile(r"^/v1/push/(subscriptions|test|job-events)$")
_PUSH_DELETE = re.compile(r"^/v1/push/subscriptions/[A-Za-z0-9_-]+$")


def _sessions():
    from api import jaeger_sessions  # type: ignore
    return jaeger_sessions


def handles(p: str) -> bool:
    return bool(_GET.match(p) or _PUSH_WRITE.match(p) or _PUSH_DELETE.match(p))


def route(handler, parsed, method: str, read_body, j) -> bool:
    p = parsed.path
    js = _sessions()
    ensure_poller()
    query = f"?{parsed.query}" if parsed.query else ""
    if method == "GET" and _GET.match(p):
        return js._proxy(handler, "GET", p + query)
    if (method == "POST" and _PUSH_WRITE.match(p)) or (method == "PATCH" and p == "/v1/notifications"):
        return js._proxy(handler, method, p, json.dumps(read_body(handler) or {}).encode())
    if method == "DELETE" and _PUSH_DELETE.match(p):
        return js._proxy(handler, "DELETE", p, b"")
    return False


# ── jobs runner → gateway push ───────────────────────────────────────
def state_root() -> Path:
    raw = os.environ.get("JAEGER_UNIFIED_STATE", "").strip()
    return Path(raw).expanduser() if raw else Path.home() / ".jaeger" / "unified"


def jobs_snapshot() -> dict:
    from api import unified_api  # type: ignore
    return unified_api.runner_status()


def post_job_event(event: dict) -> None:
    """Hook (tests replace it): POST to the Gateway with the WebUI caller token."""
    from urllib.request import Request, urlopen
    js = _sessions()
    req = Request(f"{js.gateway_base()}/v1/push/job-events", data=json.dumps(event).encode(), method="POST")
    req.add_header("Content-Type", "application/json")
    js._add_caller_auth(req)
    with urlopen(req, timeout=10):
        pass


def poll_once() -> dict:
    seen_path = state_root() / "notifications" / "jobs_seen.json"
    try:
        seen = json.loads(seen_path.read_text("utf-8"))
    except (OSError, ValueError):
        seen = {}
    out, errors = [], []
    try:
        snap = jobs_snapshot()
        down = snap.get("health") == "down"
        if down and not seen.get("__runner__", {}).get("down") and snap.get("jobs"):
            out.append({"task_id": "runner", "state": "runner_down", "title": "Job runner is not responding"})
        seen["__runner__"] = {"down": down}
        for job in snap.get("jobs") or []:
            tid = str(job.get("task_id") or "")
            if not tid:
                continue
            prev = seen.get(tid, {})
            state, stuck = job.get("state"), bool(job.get("stuck"))
            title = str(job.get("title") or tid)
            if state in TERMINAL and prev.get("state") not in (None, state) and prev.get("state") not in TERMINAL:
                out.append({"task_id": tid, "state": state, "title": title})
            if stuck and not prev.get("stuck"):
                out.append({"task_id": tid, "state": "stuck", "title": title})
            seen[tid] = {"state": state, "stuck": stuck}
    except Exception as exc:  # noqa: BLE001
        errors.append({"source": "jobs", "error": type(exc).__name__})
    sent = []
    for ev in out:
        try:
            post_job_event(ev); sent.append(ev)
        except Exception as exc:  # noqa: BLE001
            errors.append({"source": "gateway", "error": type(exc).__name__})
    seen_path.parent.mkdir(parents=True, exist_ok=True)
    seen_path.write_text(json.dumps(seen), "utf-8")
    return {"events": sent, "errors": errors}


_poller: threading.Thread | None = None


def ensure_poller() -> None:
    global _poller
    if _poller is not None and _poller.is_alive():
        return
    def loop():
        while True:
            time.sleep(POLL_S)
            try:
                poll_once()
            except Exception:  # noqa: BLE001
                pass
    _poller = threading.Thread(target=loop, name="jaeger-job-notify", daemon=True)
    _poller.start()
