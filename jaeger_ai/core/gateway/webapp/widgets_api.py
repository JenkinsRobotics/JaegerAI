"""Widgets (Widgets & n8n plan step 1; WIDGETS-SPEC §9 + Decisions) and the read endpoints they need.

Loopback WebUI routes (caller = the WebUI session; Gateway calls use the WebUI caller key):
  GET  /v1/widgets[?surface=web|widgetkit|control]     definitions (plan schema)
  GET  /v1/widgets/{id}/data                           {id, data, observed_at, stale, error?}
  POST /v1/widgets/{id}/actions/{action}               {item?, host?}  — never executes directly, except e-stop:
         tier none        → read/open only (no side effect; returns the link)
         tier confirm     → quick sheet: creates an inbox approval, auto-decides it, then runs (audited)
         tier owner       → full approval card (+Touch ID in the app); runs after it is approved (settle)
         tier safety_stop → e-stop only: runs at once, idempotent, audited, never re-arms
  GET  /v1/widgets/actions                             pending/finished action log (newest first)
  POST /v1/widgets/actions/settle                      run owner-tier actions whose approval was granted
  GET  /v1/machine/health        CPU, GPU, memory, disk, thermals (resource_manager.probe_mac, read-only)
  GET  /v1/machine/servers       gateway / webui / ollama / comfyui / n8n loopback health
  GET  /v1/robots                stub (no robot bus configured)
  POST /v1/robots/{id}/estop     the one approval-free action (also reachable as a widget action)
  GET  /v1/research/youtube/progress   per-job % / videos done / step / ETA from the jobs runner
  GET  /v1/automations/n8n/status | /workflows | /workflows/{id} | /executions[?workflow_id=]
  GET  /v1/automations/cron      Jaeger cron jobs + legacy ~/.n8n-cron.sh entries (names only)
n8n is reached only on loopback (N8N_URL, default http://127.0.0.1:5678) with its API key from
JAEGER_N8N_API_KEY or the macOS Keychain item ``ai.jaeger.n8n`` / ``api-key``; the key is never returned.
Nothing here starts n8n, writes a plist or touches launchd.
"""
from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlencode, urlparse

LOOPBACK = {"127.0.0.1", "localhost", "::1"}
SIZES = ("small", "medium", "large")
TIERS = ("none", "confirm", "owner", "safety_stop")
_lock = threading.RLock()


class WidgetError(Exception):
    def __init__(self, status: int, message: str, code: str = "error"):
        super().__init__(message)
        self.status, self.message, self.code = status, message, code


def _w(id_, title, endpoint, view, *, query=None, poll=60, stale=300, size=("small", "medium", "large"),
       actions=(), widgetkit_view=None, fields=None, control=None):
    return {"id": id_, "version": 1, "title": title, "source": {"endpoint": endpoint, "query": query or {}},
            "view": view, "refresh": {"mode": "push", "fallback_poll_s": poll, "stale_after_s": stale},
            "size": {"min": size[0], "default": size[1], "max": size[2]}, "actions": list(actions),
            "surfaces": {"web": {"size": {"default": size[1]}},
                         "widgetkit": {"view": widgetkit_view or view, "fields": fields or [],
                                       "actions": [a["id"] for a in actions if a["approval_tier"] != "none"]},
                         "control": control}}


def _a(id_, label, endpoint, tier, *, risk=None, type_="permission"):
    return {"id": id_, "label": label, "endpoint": endpoint, "approval_tier": tier,
            "risk": risk or {"none": "low", "confirm": "low", "owner": "high", "safety_stop": "critical"}[tier],
            "type": type_}


DEFINITIONS = [
    _w("machine.health", "System health", "/v1/machine/health", "stat", poll=30, stale=60, fields=["cpu_pct"],
       actions=[_a("pause_all", "Pause all agents", "POST /v1/stop", "confirm")],
       control={"kind": "button", "action": "pause_all", "label": "Pause Jaeger"}),
    _w("tasks.running", "Running tasks", "/v1/tasks", "list", query={"state": "running", "limit": 5}, fields=["count"],
       actions=[_a("cancel", "Cancel", "POST /v1/tasks/{item}/cancel", "confirm"),
                _a("approve", "Approve", "POST /v1/tasks/{item}/approve", "owner", type_="code_change")]),
    _w("approvals.waiting", "Approvals", "/v1/approvals/counts", "stat", poll=30, fields=["pending"],
       actions=[_a("review", "Review", "GET /work/approvals/{item}", "none")]),
    _w("agents.presence", "Agents", "/v1/agents/summary", "status", fields=["agents"]),
    _w("research.youtube", "YouTube research", "/v1/research/youtube/progress", "timeline", poll=30, fields=["progress"],
       actions=[_a("pause", "Pause", "POST /v1/research/youtube/{item}/pause", "confirm"),
                _a("resume", "Resume", "POST /v1/research/youtube/{item}/resume", "confirm"),
                _a("open", "Open", "GET /work/research/{item}", "none")]),
    _w("servers.status", "Servers", "/v1/machine/servers", "status", poll=30, stale=90,
       actions=[_a("restart", "Restart", "POST /v1/machine/servers/{item}/restart", "owner")]),
    _w("robots.estop", "Robots", "/v1/robots", "control", poll=10, stale=60, size=("small", "small", "medium"),
       actions=[_a("estop", "E-STOP", "POST /v1/robots/{item}/estop", "safety_stop"),
                _a("rearm", "Re-arm", "POST /v1/robots/{item}/rearm", "owner")],
       control={"kind": "button", "action": "estop", "label": "E-STOP"}),
    _w("automations.n8n", "Automations", "/v1/automations/n8n/workflows", "list", poll=60,
       actions=[_a("run", "Run now", "POST /v1/automations/n8n/workflows/{item}/run", "confirm"),
                _a("activate", "Enable", "POST /v1/automations/n8n/workflows/{item}/activate", "confirm"),
                _a("deactivate", "Pause", "POST /v1/automations/n8n/workflows/{item}/deactivate", "confirm")]),
    _w("gateway", "Gateway", "/v1/gateway-health", "status", poll=30),
]
BY_ID = {d["id"]: d for d in DEFINITIONS}
LOCAL_PREFIXES = ("/v1/machine/", "/v1/robots", "/v1/research/youtube", "/v1/automations/", "/v1/gateway-health")


# ── hooks (tests replace these) ───────────────────────────────────────
def state_root() -> Path:
    raw = os.environ.get("JAEGER_UNIFIED_STATE", "").strip()
    return Path(raw).expanduser() if raw else Path.home() / ".jaeger" / "unified"


def gateway_call(method: str, path: str, body: dict | None = None) -> tuple[int, object]:
    from api import jaeger_sessions as js  # type: ignore
    data = json.dumps(body).encode() if body is not None else (b"{}" if method != "GET" else None)
    req = urllib.request.Request(js.gateway_base() + path, data=data, method=method)
    req.add_header("Accept", "application/json")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    js._add_caller_auth(req)
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            return int(resp.status), json.loads(resp.read().decode("utf-8") or "null")
    except urllib.error.HTTPError as exc:
        try:
            return int(exc.code), json.loads(exc.read().decode("utf-8") or "null")
        except ValueError:
            return int(exc.code), {"error": "gateway error"}


def local_call(method: str, path: str, body: dict | None = None) -> tuple[int, object]:
    """Dispatch to a WebUI-owned route in-process (no HTTP hop)."""
    out: dict = {}

    def j(_h, payload, status=200):
        out.update(status=status, payload=payload)
        return True
    parsed = urlparse(path)
    if route(None, parsed, method, lambda _h: body or {}, j):
        return out.get("status", 200), out.get("payload")
    from api import unified_api  # type: ignore
    if unified_api.route(None, parsed, method, lambda _h: body or {}, j):
        return out.get("status", 200), out.get("payload")
    return 404, {"error": "not found"}


def now() -> float:
    return time.time()


# ── audit + action log ───────────────────────────────────────────────
def _audit_path() -> Path:
    return state_root() / "audit" / "widget_actions.jsonl"


def audit(entry: dict) -> dict:
    entry = {"at": now(), **entry}
    with _lock:
        p = _audit_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")
    return entry


def action_log(limit: int = 100) -> list[dict]:
    try:
        lines = _audit_path().read_text("utf-8").splitlines()
    except OSError:
        return []
    out = []
    for line in reversed(lines[-2000:]):
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
        if len(out) >= limit:
            break
    return out


def _pending_path() -> Path:
    return state_root() / "widget_pending.json"


def _pending() -> dict:
    try:
        d = json.loads(_pending_path().read_text("utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_pending(d: dict) -> None:
    p = _pending_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(d), "utf-8")


# ── definitions + data ───────────────────────────────────────────────
def definitions(surface: str | None = None) -> list[dict]:
    if surface and surface not in ("web", "widgetkit", "control"):
        raise WidgetError(400, "surface must be web, widgetkit or control")
    defs = DEFINITIONS
    if surface == "control":
        defs = [d for d in defs if d["surfaces"]["control"]]
    return defs


def _call(method: str, path: str, body: dict | None = None) -> tuple[int, object]:
    return local_call(method, path, body) if path.startswith(LOCAL_PREFIXES) else gateway_call(method, path, body)


def data(wid: str) -> dict:
    d = BY_ID.get(wid)
    if d is None:
        raise WidgetError(404, "Unknown widget", "unknown_widget")
    src = d["source"]
    path = src["endpoint"] + ("?" + urlencode(src["query"]) if src["query"] else "")
    at = now()
    try:
        status, payload = _call("GET", path)
    except Exception as exc:  # noqa: BLE001
        return {"id": wid, "data": None, "observed_at": at, "stale": True, "error": type(exc).__name__}
    if status >= 400:
        return {"id": wid, "data": None, "observed_at": at, "stale": True, "error": f"source returned {status}"}
    if wid == "tasks.running" and isinstance(payload, dict):
        tasks = [t for t in payload.get("tasks") or [] if t.get("state") in ("running", "active", "in_progress")]
        payload = {"count": len(tasks), "tasks": tasks[: src["query"].get("limit", 5)]}
    return {"id": wid, "data": payload, "observed_at": at, "stale": False}


# ── actions ──────────────────────────────────────────────────────────
_ITEM = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")


def _resolve(d: dict, action_id: str, item: str | None) -> tuple[dict, str, str]:
    act = next((a for a in d["actions"] if a["id"] == action_id), None)
    if act is None:
        raise WidgetError(404, "Unknown action", "unknown_action")
    method, path = act["endpoint"].split(" ", 1)
    if "{item}" in path:
        if not item or not _ITEM.match(item):
            raise WidgetError(400, "item is required for this action", "item_required")
        path = path.replace("{item}", item)
    return act, method, path


def _execute(method: str, path: str) -> tuple[int, object]:
    return _call(method, path, {})


def act(wid: str, action_id: str, body: dict) -> tuple[int, dict]:
    d = BY_ID.get(wid)
    if d is None:
        raise WidgetError(404, "Unknown widget", "unknown_widget")
    item = body.get("item")
    item = str(item) if item is not None else None
    host = str(body.get("host") or "page") if body.get("host") in ("page", "widgetkit", "control_center", "menubar") else "page"
    a, method, path = _resolve(d, action_id, item)
    base = {"widget": wid, "action": action_id, "item": item, "host": host, "tier": a["approval_tier"]}
    if a["approval_tier"] == "none":
        return 200, {**base, "executed": False, "open": path}
    if a["approval_tier"] == "safety_stop":
        status, result = _execute(method, path)
        audit({**base, "event": "estop", "status": status, "approval": "exempt"})
        return (200 if status < 400 else 502), {**base, "executed": status < 400, "result": result}
    status, created = gateway_call("POST", "/v1/approvals/requests", {
        "source": "widget", "title": f"{a['label']}: {d['title']}" + (f" ({item})" if item else ""),
        "summary": f"{a['label']} from the {d['title']} widget ({host})", "risk": a["risk"], "type": a["type"],
        "payload": {"capability": a["endpoint"], "target": item, "duration": "once"},
        "action": {"widget": wid, "action": action_id, "method": method, "path": path}, "host": host})
    if status >= 400 or not isinstance(created, dict):
        raise WidgetError(503, "Could not create the approval", "approvals_unavailable")
    aid = created["approval"]["approval_id"]
    if a["approval_tier"] == "owner":
        with _lock:
            p = _pending(); p[aid] = {**base, "method": method, "path": path, "created_at": now()}; _save_pending(p)
        audit({**base, "event": "approval_requested", "approval_id": aid})
        return 202, {**base, "executed": False, "approval_id": aid, "status": "awaiting_approval",
                     "open": f"/work/approvals/{aid}"}
    # quick confirm: an audited, auto-decided approval record, then the call
    dstatus, decided = gateway_call("POST", f"/v1/approvals/{aid}/decide",
                                    {"decision": "approve", "device": host, "reason": "quick confirm"})
    if dstatus >= 400:
        audit({**base, "event": "confirm_refused", "approval_id": aid, "status": dstatus})
        return dstatus, {**base, "executed": False, "approval_id": aid, "error": (decided or {}).get("error") if isinstance(decided, dict) else None}
    rstatus, result = _execute(method, path)
    audit({**base, "event": "executed", "approval_id": aid, "status": rstatus})
    return (200 if rstatus < 400 else 502), {**base, "executed": rstatus < 400, "approval_id": aid, "result": result}


def settle() -> list[dict]:
    """Run owner-tier actions whose approval was granted; drop denied/expired ones. Each runs once."""
    done = []
    with _lock:
        pend = _pending()
        for aid, rec in list(pend.items()):
            status, row = gateway_call("GET", f"/v1/approvals/{aid}")
            if status == 404:
                pend.pop(aid); continue
            if not isinstance(row, dict) or row.get("status") != "resolved":
                continue
            pend.pop(aid)
            if row.get("decision") in ("deny", "expired", "changes", "cancelled"):
                done.append(audit({**rec, "event": "not_run", "approval_id": aid, "decision": row.get("decision")}))
                continue
            rstatus, _ = _execute(rec["method"], rec["path"])
            done.append(audit({**{k: v for k, v in rec.items() if k not in ("method",)}, "event": "executed",
                               "approval_id": aid, "status": rstatus}))
        _save_pending(pend)
    return done


# ── machine / servers / robots / research progress ───────────────────
def machine_health() -> dict:
    from api import unified_api  # type: ignore
    from api.host_capabilities import capabilities  # type: ignore
    snap = unified_api._rm().snapshot()
    return {"snapshot": snap, "capabilities": capabilities(snap), "observed_at": now()}


SERVERS = (("gateway", None, "/health"), ("ollama", 11434, "/api/version"), ("comfyui", 8188, "/system_stats"),
           ("n8n", 5678, "/healthz"))


def _probe_http(url: str, timeout: float = 1.5) -> dict:
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(urllib.request.Request(url, method="GET"), timeout=timeout) as r:
            return {"up": True, "status": int(r.status), "latency_ms": round((time.monotonic() - t0) * 1000)}
    except urllib.error.HTTPError as exc:
        return {"up": True, "status": int(exc.code), "latency_ms": round((time.monotonic() - t0) * 1000)}
    except (OSError, ValueError):
        return {"up": False, "status": None, "latency_ms": None}


def servers() -> dict:
    out = []
    for name, port, path in SERVERS:
        if port is None:
            try:
                from api import jaeger_sessions as js  # type: ignore
                base = js.gateway_base()
            except Exception:  # noqa: BLE001
                base = "http://127.0.0.1:8642"
        else:
            base = f"http://127.0.0.1:{port}"
        host = urlparse(base).hostname
        r = _probe_http(base + path) if host in LOOPBACK else {"up": None, "status": None, "latency_ms": None}
        out.append({"id": name, "url": base, **r})
    out.append({"id": "webui", "url": "http://127.0.0.1:8790", "up": True, "status": 200, "latency_ms": 0})
    return {"servers": out, "observed_at": now()}


def robots() -> dict:
    return {"robots": [], "stub": True, "reason": "No robot bus is configured yet", "observed_at": now()}


def estop(robot_id: str, host: str = "page") -> dict:
    """Idempotent, approval-exempt, audited. With no bus configured it records the stop request."""
    entry = audit({"event": "estop_request", "robot_id": robot_id, "host": host, "approval": "exempt",
                   "delivered": False, "reason": "no robot bus configured"})
    return {"robot_id": robot_id, "estopped": True, "delivered": False, "stub": True, "audited_at": entry["at"]}


def research_progress() -> dict:
    from api import unified_api  # type: ignore
    st = unified_api.runner_status()
    jobs = []
    for j in st.get("jobs") or []:
        total, done = j.get("item_count") or j.get("videos_in_job") or 0, j.get("videos_done") or 0
        pct = round(100 * done / total) if total else None
        eta = None
        if isinstance(j.get("progress"), dict):
            eta = j["progress"].get("eta_s")
        jobs.append({"task_id": j.get("task_id"), "title": j.get("title"), "state": j.get("state"),
                     "step": j.get("phase"), "videos_done": done, "videos_total": total, "percent": pct,
                     "eta_s": eta, "stuck": j.get("stuck"), "paused": j.get("paused"), "error_count": j.get("error_count")})
    return {"runner": st.get("health"), "jobs": jobs, "observed_at": now()}


# ── n8n (loopback REST API) + cron ───────────────────────────────────
def n8n_base() -> str:
    base = os.environ.get("N8N_URL", "http://127.0.0.1:5678").rstrip("/")
    if urlparse(base).hostname not in LOOPBACK:
        raise WidgetError(400, "n8n must be on loopback", "n8n_not_loopback")
    return base


def n8n_key() -> str | None:
    key = os.environ.get("JAEGER_N8N_API_KEY", "").strip()
    if key:
        return key
    try:
        out = subprocess.run(["security", "find-generic-password", "-s", "ai.jaeger.n8n", "-a", "api-key", "-w"],
                             capture_output=True, text=True, timeout=3)
        return (out.stdout.strip() or None) if out.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def n8n_request(method: str, path: str, body: dict | None = None) -> tuple[int, object]:
    key = n8n_key()
    if not key:
        raise WidgetError(503, "n8n API key is not set up (Keychain ai.jaeger.n8n)", "n8n_no_key")
    req = urllib.request.Request(n8n_base() + "/api/v1" + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None)
    req.add_header("X-N8N-API-KEY", key); req.add_header("Accept", "application/json")
    if body is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            return int(r.status), json.loads(r.read().decode("utf-8") or "null")
    except urllib.error.HTTPError as exc:
        return int(exc.code), {"error": f"n8n returned {exc.code}"}
    except OSError as exc:
        raise WidgetError(503, "n8n isn't running", "n8n_unreachable") from exc


def n8n_status() -> dict:
    base = n8n_base()
    r = _probe_http(base + "/healthz")
    return {"connected": bool(r["up"]) and bool(n8n_key()), "running": bool(r["up"]), "url": base,
            "api_key": "configured" if n8n_key() else "missing", "pinned_version": "2.14.2"}


def _workflow(w: dict) -> dict:
    nodes = w.get("nodes") or []
    trig = next((n for n in nodes if "trigger" in str(n.get("type", "")).lower() or "webhook" in str(n.get("type", "")).lower()), None)
    return {"id": w.get("id"), "name": w.get("name"), "active": bool(w.get("active")),
            "trigger": {"kind": (trig or {}).get("type"), "summary": (trig or {}).get("name")},
            "can_run": any(t in str((trig or {}).get("type", "")).lower() for t in ("manual", "webhook")),
            "updated_at": w.get("updatedAt")}


def n8n_workflows() -> dict:
    status, payload = n8n_request("GET", "/workflows")
    rows = (payload or {}).get("data") if isinstance(payload, dict) else None
    if status >= 400 or not isinstance(rows, list):
        raise WidgetError(502, "n8n workflows unavailable", "n8n_error")
    return {"workflows": [_workflow(w) for w in rows]}


def n8n_workflow(wid: str) -> dict:
    status, w = n8n_request("GET", f"/workflows/{wid}")
    if status == 404:
        raise WidgetError(404, "Workflow not found", "not_found")
    if status >= 400 or not isinstance(w, dict):
        raise WidgetError(502, "n8n workflow unavailable", "n8n_error")
    return {**_workflow(w), "nodes": [{"type": n.get("type"), "name": n.get("name"),
                                       "is_jaeger": "jaeger" in str(n.get("type", "")).lower()} for n in w.get("nodes") or []]}


def n8n_executions(workflow_id: str | None) -> dict:
    q = "?" + urlencode({"workflowId": workflow_id, "limit": 50}) if workflow_id else "?limit=50"
    status, payload = n8n_request("GET", "/executions" + q)
    rows = (payload or {}).get("data") if isinstance(payload, dict) else None
    if status >= 400 or not isinstance(rows, list):
        raise WidgetError(502, "n8n executions unavailable", "n8n_error")
    return {"executions": [{"id": e.get("id"), "workflow_id": e.get("workflowId"), "status": e.get("status"),
                            "started_at": e.get("startedAt"), "finished_at": e.get("stoppedAt")} for e in rows]}


def n8n_mutate(wid: str, op: str) -> dict:
    if op in ("activate", "deactivate"):
        status, w = n8n_request("POST", f"/workflows/{wid}/{op}")
        if status >= 400:
            raise WidgetError(502, f"n8n {op} failed", "n8n_error")
        return _workflow(w if isinstance(w, dict) else {"id": wid})
    # run: only Manual/Webhook-triggered workflows; webhooks are called on loopback
    w = n8n_workflow(wid)
    hook = next((n for n in (n8n_request("GET", f"/workflows/{wid}")[1] or {}).get("nodes", [])
                 if "webhook" in str(n.get("type", "")).lower()), None)
    if not hook or not (hook.get("parameters") or {}).get("path"):
        raise WidgetError(409, "This workflow has no Webhook trigger, so it can't be run from Jaeger", "not_runnable")
    url = f"{n8n_base()}/webhook/{hook['parameters']['path']}"
    r = _probe_http(url)
    return {"id": w["id"], "triggered": bool(r["up"]), "status": r["status"]}


def cron_jobs() -> dict:
    legacy = []
    p = Path.home() / ".n8n-cron.sh"
    try:
        legacy = sorted(set(re.findall(r"^\s*([a-z][a-z0-9-]+)\)\s*$", p.read_text("utf-8", errors="replace"), re.M)))
    except OSError:
        pass
    jobs = []
    try:
        from jaeger_agent.background import cron as cron_mod  # type: ignore
        for j in getattr(cron_mod, "list_jobs", lambda: [])():
            jobs.append(j if isinstance(j, dict) else getattr(j, "__dict__", {}))
    except Exception:  # noqa: BLE001
        pass
    return {"jobs": jobs, "legacy": [{"id": n, "group": "Legacy (Hermes)", "runner": "~/.n8n-cron.sh"} for n in legacy]}


# ── router ───────────────────────────────────────────────────────────
_R = {
    "widget_data": re.compile(r"^/v1/widgets/([a-z0-9_.]+)/data$"),
    "widget_act": re.compile(r"^/v1/widgets/([a-z0-9_.]+)/actions/([a-z_]+)$"),
    "estop": re.compile(r"^/v1/robots/([A-Za-z0-9_.:-]{1,64})/estop$"),
    "n8n_wf": re.compile(r"^/v1/automations/n8n/workflows/([A-Za-z0-9_-]{1,64})$"),
    "n8n_op": re.compile(r"^/v1/automations/n8n/workflows/([A-Za-z0-9_-]{1,64})/(run|activate|deactivate)$"),
}
_PATHS = ("/v1/widgets", "/v1/widgets/actions", "/v1/widgets/actions/settle", "/v1/machine/health", "/v1/machine/servers",
          "/v1/robots", "/v1/research/youtube/progress", "/v1/automations/n8n/status", "/v1/automations/n8n/workflows",
          "/v1/automations/n8n/executions", "/v1/automations/cron")


def handles(p: str) -> bool:
    return p in _PATHS or any(r.match(p) for r in _R.values())


def route(handler, parsed, method: str, read_body, j) -> bool:
    p = parsed.path
    if not handles(p):
        return False
    from urllib.parse import parse_qs
    q = {k: v[0] for k, v in parse_qs(parsed.query or "").items()}
    try:
        if method == "GET":
            if p == "/v1/widgets":
                return j(handler, {"widgets": definitions(q.get("surface")), "sizes": list(SIZES), "tiers": list(TIERS)}) or True
            if p == "/v1/widgets/actions":
                return j(handler, {"actions": action_log(), "pending": list(_pending().keys())}) or True
            m = _R["widget_data"].match(p)
            if m:
                return j(handler, data(m.group(1))) or True
            if p == "/v1/machine/health":
                return j(handler, machine_health()) or True
            if p == "/v1/machine/servers":
                return j(handler, servers()) or True
            if p == "/v1/robots":
                return j(handler, robots()) or True
            if p == "/v1/research/youtube/progress":
                return j(handler, research_progress()) or True
            if p == "/v1/automations/n8n/status":
                return j(handler, n8n_status()) or True
            if p == "/v1/automations/n8n/workflows":
                return j(handler, n8n_workflows()) or True
            m = _R["n8n_wf"].match(p)
            if m:
                return j(handler, n8n_workflow(m.group(1))) or True
            if p == "/v1/automations/n8n/executions":
                return j(handler, n8n_executions(q.get("workflow_id"))) or True
            if p == "/v1/automations/cron":
                return j(handler, cron_jobs()) or True
            return False
        if method == "POST":
            body = read_body(handler) or {}
            m = _R["widget_act"].match(p)
            if m:
                status, out = act(m.group(1), m.group(2), body if isinstance(body, dict) else {})
                return j(handler, out, status=status) or True
            if p == "/v1/widgets/actions/settle":
                return j(handler, {"settled": settle()}) or True
            m = _R["estop"].match(p)
            if m:
                return j(handler, estop(m.group(1), str((body or {}).get("host") or "page"))) or True
            m = _R["n8n_op"].match(p)
            if m:
                # Only reachable in-process from an approved widget action (local_call passes handler=None).
                if handler is not None:
                    raise WidgetError(403, "Use the Automations widget action (quick confirm)", "confirm_required")
                return j(handler, n8n_mutate(m.group(1), m.group(2))) or True
        return False
    except WidgetError as exc:
        return j(handler, {"error": exc.message, "code": exc.code}, status=exc.status) or True
