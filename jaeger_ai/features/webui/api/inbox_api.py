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


_INBOX = re.compile(r"^/v1/approvals/inbox(?:/(batch|[A-Za-z0-9_.:-]+/decide))?$")


def handles(p: str) -> bool:
    return bool(_INBOX.match(p) or _GET.match(p) or _PUSH_WRITE.match(p) or _PUSH_DELETE.match(p))


# ── one inbox: Gateway approvals + WebUI-process approvals ───────────
def gateway_approvals() -> list[dict]:
    from urllib.request import Request, urlopen
    js = _sessions()
    req = Request(f"{js.gateway_base()}/v1/approvals", method="GET")
    req.add_header("Accept", "application/json")
    js._add_caller_auth(req)
    with urlopen(req, timeout=4) as resp:
        rows = json.loads(resp.read().decode("utf-8") or "{}").get("approvals")
    if not isinstance(rows, list):
        raise RuntimeError("gateway approvals unavailable")
    return rows


def local_approvals() -> list[dict]:
    """WebUI-process pending cards (route_approvals queue)."""
    from api.route_approvals import _lock as qlock, _pending  # type: ignore
    out = []
    with qlock:
        for sid, queue in list(_pending.items()):
            for entry in (queue if isinstance(queue, list) else [queue] if queue else []):
                if isinstance(entry, dict):
                    out.append({**entry, "session_id": entry.get("session_id") or sid})
    return out


def respond_local(handler, session_id: str, approval_id: str, choice: str):
    from api import routes  # type: ignore
    return routes._handle_approval_respond(handler, {"session_id": session_id, "approval_id": approval_id, "choice": choice})


def _local_item(e: dict) -> dict:
    from jaeger_ai.core.gateway.approvals_inbox import project
    tool = str(e.get("tool") or e.get("command") or "")
    row = {"approval_id": str(e.get("approval_id") or ""), "session_id": e.get("session_id"), "request_id": None,
           "kind": "tool_confirm", "prompt": str(e.get("description") or e.get("command") or "Approval required")[:500],
           "options": e.get("options") or ["once", "session", "always", "deny"], "status": "pending", "decision": None,
           "created_at": e.get("created_at") or e.get("ts") or 0, "resolved_at": None,
           "metadata": {"type": "tool_confirm", "agent_id": e.get("agent") or "webui", "payload": {"tool": tool}}}
    return {**project(row), "backend": "webui"}


def merged_inbox() -> dict:
    items, seen, errors = [], set(), []
    try:
        for r in gateway_approvals():
            if r.get("approval_id") and r["approval_id"] not in seen:
                seen.add(r["approval_id"]); items.append({**r, "backend": "gateway"})
    except Exception as exc:  # noqa: BLE001
        errors.append({"source": "gateway", "error": type(exc).__name__})
    try:
        for e in local_approvals():
            it = _local_item(e)
            if it["approval_id"] and it["approval_id"] not in seen:
                seen.add(it["approval_id"]); items.append(it)
    except Exception as exc:  # noqa: BLE001
        errors.append({"source": "webui", "error": type(exc).__name__})
    items.sort(key=lambda i: -float(i.get("created_at") or 0))
    return {"approvals": items, "count": len(items), "sources_unavailable": errors}


def _local_decide(item: dict, body: dict, *, batch: bool = False) -> tuple[str | None, dict | None]:
    """Same rules as the Gateway decide; returns (choice, error)."""
    from jaeger_ai.core.gateway.approvals_inbox import MIN_REASON, _clean_reason
    decision = str(body.get("decision") or "").lower()
    if decision not in ("approve", "deny", "changes"):
        return None, {"status": 400, "code": "bad_decision", "error": "decision must be approve, deny or changes"}
    if decision != "approve":
        if len(_clean_reason(body)) < MIN_REASON:
            return None, {"status": 400, "code": "reason_required", "error": "A reason (a chip or at least 3 characters) is required"}
        return "deny", None  # the WebUI queue has no 'changes' channel; it is a reasoned deny
    if batch and not item["batchable"]:
        return None, {"status": 422, "code": "not_batchable", "error": f"Not batchable: {item['risk']} risk"}
    if item["requires_step_up"]:
        return None, {"status": 403, "code": "step_up_required", "error": "Approve this in the Jaeger app on the Mac"}
    scope = str(body.get("scope") or "once")
    return (scope if scope in item["options"] else None), (None if scope in item["options"] else
            {"status": 400, "code": "scope_not_offered", "error": f"This approval does not offer '{scope}'"})


class _Capture:
    """Stand-in handler so one batch can call the per-item respond path; replies are discarded."""
    def __init__(self, real):
        import io
        self.real, self.wfile, self.status = real, io.BytesIO(), None
        self.headers = getattr(real, "headers", {})
        self.client_address = getattr(real, "client_address", ("127.0.0.1", 0))

    def send_response(self, code, *a):
        self.status = code

    def send_header(self, *a):
        pass

    def end_headers(self):
        pass


def _inbox_route(handler, parsed, method, read_body, j) -> bool:
    p = parsed.path
    js = _sessions()
    if p == "/v1/approvals/inbox" and method == "GET":
        j(handler, merged_inbox()); return True
    if method != "POST":
        return False
    body = read_body(handler) or {}
    local = {i["approval_id"]: i for i in (_local_item(e) for e in local_approvals())}
    if p.endswith("/decide"):
        aid = p.split("/")[4]
        if aid not in local:
            return js._proxy(handler, "POST", f"/v1/approvals/{aid}/decide", json.dumps(body).encode())
        choice, err = _local_decide(local[aid], body)
        if err:
            j(handler, {"error": err["error"], "code": err["code"]}, status=err["status"]); return True
        respond_local(handler, local[aid]["session_id"], aid, choice)
        return True
    ids = body.get("ids") if isinstance(body.get("ids"), list) else []
    if not ids or body.get("decision") not in ("approve", "deny"):
        j(handler, {"error": "ids and decision approve|deny required"}, status=400); return True
    gw_ids = [i for i in ids if i not in local]
    results = []
    if gw_ids:
        from urllib.request import Request, urlopen
        req = Request(f"{js.gateway_base()}/v1/approvals/batch", data=json.dumps({**body, "ids": gw_ids}).encode(), method="POST")
        req.add_header("Content-Type", "application/json"); js._add_caller_auth(req)
        try:
            with urlopen(req, timeout=10) as resp:
                results += json.loads(resp.read().decode("utf-8") or "{}").get("results", [])
        except Exception as exc:  # noqa: BLE001
            results += [{"approval_id": i, "ok": False, "status": 503, "code": "gateway_unavailable", "error": type(exc).__name__} for i in gw_ids]
    for aid in [i for i in ids if i in local]:
        choice, err = _local_decide(local[aid], body, batch=True)
        if err:
            results.append({"approval_id": aid, "ok": False, **err}); continue
        cap = _Capture(handler)
        try:
            respond_local(cap, local[aid]["session_id"], aid, choice)
            results.append({"approval_id": aid, "ok": True, "decision": choice})
        except Exception as exc:  # noqa: BLE001
            results.append({"approval_id": aid, "ok": False, "status": 500, "code": "webui_error", "error": type(exc).__name__})
    ok = sum(bool(r.get("ok")) for r in results)
    j(handler, {"results": results, ("approved" if body["decision"] == "approve" else "denied"): ok, "rejected": len(results) - ok})
    return True


def route(handler, parsed, method: str, read_body, j) -> bool:
    p = parsed.path
    if _INBOX.match(p):
        return _inbox_route(handler, parsed, method, read_body, j)
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
