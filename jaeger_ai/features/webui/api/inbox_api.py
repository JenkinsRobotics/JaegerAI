"""Approvals inbox + Web Push notifications for the unified UI (WebUI-owned, loopback).

Approvals (one list across chats, child workers/specialists, jobs and WebUI-local cards)
  GET  /v1/inbox/approvals                         {approvals:[{approval_id, source, agent, tool, summary,
                                                    created_at, session_id, parent_session_id, task_id, options}]}
  POST /v1/inbox/approvals/<id>/approve {choice?}  choice once|session|always (default once)
  POST /v1/inbox/approvals/<id>/deny
       -> 200 respond result | 409 {code:"approval_not_pending"} when stale/already resolved | 404 unknown action
  Reuses: Gateway GET /v1/approvals (store.list_pending_approvals + origin) and the WebUI respond path
  (routes._respond_gateway_store_approval for Gateway cards, routes._handle_approval_respond for local cards).

Notifications (standard Web Push, RFC 8030/8291/8292 — works with Safari 16.4+ and other browsers)
  GET  /v1/notifications/vapid-public-key          {public_key} (applicationServerKey for pushManager.subscribe)
  POST /v1/notifications/subscribe   {subscription:{endpoint, keys:{p256dh, auth}}, label?}
  POST /v1/notifications/unsubscribe {endpoint}
  GET  /v1/notifications/subscriptions             endpoints redacted to origin + hash
  GET/PUT /v1/notifications/settings               {timezone, quiet_hours:{enabled,start,end}, approvals_bypass_quiet,
                                                    events:{approval_needed,job_finished,job_stuck}, deliver_push}
  GET  /v1/notifications/feed?since=&limit=        fallback list (newest first)
  POST /v1/notifications/poll                      evaluate events now (the background poller does this every 60 s)
Events
  approval_needed  a pending approval id not seen before
  job_finished     a research job entering done | done_with_errors | error | cancelled
  job_stuck        same rule as the Home jobs tile (unified_api.runner_status): running and no progress for
                   JOB_STUCK_S (60 min), or the runner heartbeat older than youtube_research.RUNNER_FRESH_S
                   (health "down"). The runner itself cancels+retries at 90 min, so the alert lands first.
State: <state>/notifications/{vapid.json (0600, private key — never logged/returned), subscriptions.json (0600),
settings.json, feed.json, seen.json}. Pushes go only to known push-service hosts and only when deliver_push is on.
"""
from __future__ import annotations

import base64
import datetime as _dt
import hashlib
import json
import os
import re
import struct
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

JOB_STUCK_S = 3600
FEED_MAX = 500
POLL_S = 60
TERMINAL = ("done", "done_with_errors", "error", "cancelled")
PUSH_HOSTS = ("web.push.apple.com", "fcm.googleapis.com", "updates.push.services.mozilla.com")
PUSH_HOST_SUFFIXES = (".push.apple.com", ".notify.windows.com", ".push.services.mozilla.com")
DEFAULT_SETTINGS = {"timezone": "America/Los_Angeles",
                    "quiet_hours": {"enabled": True, "start": "22:00", "end": "07:00"},
                    "approvals_bypass_quiet": True,
                    "events": {"approval_needed": True, "job_finished": True, "job_stuck": True},
                    "deliver_push": False,
                    "vapid_subject": "mailto:owner@localhost"}
_lock = threading.RLock()


class InboxError(Exception):
    def __init__(self, status: int, message: str, **extra):
        super().__init__(message)
        self.status, self.payload = status, {"error": message, **extra}


# ── hooks (replaced in tests) ─────────────────────────────────────────
def state_root() -> Path:
    return Path(os.environ.get("JAEGER_STATE_HOME") or os.environ.get("JAEGER_STATE_DIR") or Path.home() / ".jaeger")


def _routes():
    from api import routes  # type: ignore  # the live WebUI module
    return routes


def gateway_approvals() -> list[dict]:
    """Every pending Gateway approval (chats, child workers, handoffs, tasks), with origin."""
    from api.jaeger_sessions import gateway_base  # type: ignore
    from jaeger_ai.core.gateway.caller_auth import client_headers
    req = urllib.request.Request(gateway_base() + "/v1/approvals",
                                 headers={"Accept": "application/json", **client_headers("webui")})
    with urllib.request.urlopen(req, timeout=4) as resp:
        data = json.loads(resp.read().decode("utf-8") or "{}")
    rows = data.get("approvals") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        raise RuntimeError("gateway approvals unavailable")
    return [r for r in rows if isinstance(r, dict) and str(r.get("status") or "pending") == "pending"]


def local_approvals() -> list[dict]:
    """WebUI-process pending cards (tools.approval queue), Gateway mirrors excluded later by id."""
    from api.route_approvals import _lock as qlock, _pending  # type: ignore
    out = []
    with qlock:
        for sid, queue in list(_pending.items()):
            for entry in (queue if isinstance(queue, list) else [queue] if queue else []):
                if isinstance(entry, dict):
                    out.append({**entry, "session_id": entry.get("session_id") or sid})
    return out


def respond_gateway(session_id: str, approval_id: str, choice: str):
    return _routes()._respond_gateway_store_approval(session_id, approval_id, choice)


def respond_local(handler, session_id: str, approval_id: str, choice: str):
    return _routes()._handle_approval_respond(handler, {"session_id": session_id, "approval_id": approval_id,
                                                        "choice": choice})


def jobs_snapshot() -> dict:
    from api import unified_api  # type: ignore
    return unified_api.runner_status()


def now() -> float:
    return time.time()


# ── approvals inbox ───────────────────────────────────────────────────
def _gw_item(r: dict) -> dict:
    meta = r.get("metadata") if isinstance(r.get("metadata"), dict) else {}
    origin = r.get("origin") if isinstance(r.get("origin"), dict) else meta.get("origin") or {}
    task_id = meta.get("task_id") or origin.get("task_id")
    source = "job" if meta.get("task_id") else "child_worker" if origin.get("parent_session_id") else \
        "handoff" if r.get("kind") == "handoff" else "session"
    return {"approval_id": str(r.get("approval_id") or ""), "source": source, "origin": "gateway",
            "agent": origin.get("agent_id") or meta.get("agent_id") or meta.get("agent") or "native:jaeger",
            "tool": str(meta.get("tool") or r.get("kind") or ""),
            "summary": str(r.get("prompt") or "Approval required")[:500],
            "target": str(meta.get("target") or "")[:300] or None,
            "created_at": r.get("created_at"), "session_id": r.get("session_id"),
            "parent_session_id": origin.get("parent_session_id"), "task_id": task_id,
            "options": r.get("options") or ["once", "deny"]}


def _local_item(e: dict) -> dict:
    return {"approval_id": str(e.get("approval_id") or ""), "source": "session", "origin": "webui",
            "agent": e.get("agent") or "webui", "tool": str(e.get("tool") or e.get("command") or ""),
            "summary": str(e.get("description") or e.get("command") or "Approval required")[:500],
            "target": None, "created_at": e.get("created_at") or e.get("ts"), "session_id": e.get("session_id"),
            "parent_session_id": None, "task_id": None, "options": e.get("options") or ["once", "session", "always", "deny"]}


def list_approvals() -> dict:
    errors, items, seen = [], [], set()
    try:
        for r in gateway_approvals():
            it = _gw_item(r)
            if it["approval_id"] and it["approval_id"] not in seen:
                seen.add(it["approval_id"]); items.append(it)
    except Exception as exc:  # noqa: BLE001
        errors.append({"source": "gateway", "error": type(exc).__name__})
    try:
        for e in local_approvals():
            it = _local_item(e)
            if it["approval_id"] and it["approval_id"] not in seen:
                seen.add(it["approval_id"]); items.append(it)
    except Exception as exc:  # noqa: BLE001
        errors.append({"source": "webui", "error": type(exc).__name__})
    items.sort(key=lambda i: -(float(i.get("created_at") or 0)))
    return {"approvals": items, "count": len(items), "sources_unavailable": errors}


def _not_pending(aid: str) -> InboxError:
    return InboxError(409, "Approval is no longer pending (already resolved, expired or stale).",
                      code="approval_not_pending", approval_id=aid)


def act(handler, j, aid: str, action: str, body: dict) -> bool:
    if action == "deny":
        choice = "deny"
    else:
        choice = str(body.get("choice") or "once")
        if choice not in ("once", "session", "always"):
            raise InboxError(400, "choice must be once, session or always")
    listing = list_approvals()
    item = next((i for i in listing["approvals"] if i["approval_id"] == aid), None)
    if item is None:
        if listing["sources_unavailable"]:
            raise InboxError(503, "Could not confirm the approval is pending.", code="approvals_unavailable",
                             sources_unavailable=listing["sources_unavailable"])
        raise _not_pending(aid)
    if item["origin"] == "gateway":
        answer = respond_gateway(item["session_id"], aid, choice)
        if answer is None:
            raise _not_pending(aid)
        payload, status = answer
        if status >= 400 and not any(i["approval_id"] == aid for i in list_approvals()["approvals"]):
            raise _not_pending(aid)   # lost a race with another responder
        j(handler, {**payload, "inbox_item": item}, status=status)
        return True
    respond_local(handler, item["session_id"], aid, choice)
    return True


# ── notifications: storage ────────────────────────────────────────────
def _ndir() -> Path:
    d = state_root() / "notifications"
    d.mkdir(parents=True, exist_ok=True)
    os.chmod(d, 0o700)
    return d


def _read(name: str, default):
    try:
        return json.loads((_ndir() / name).read_text("utf-8"))
    except (OSError, ValueError):
        return default


def _write(name: str, data, private: bool = False) -> None:
    path = _ndir() / name
    tmp = path.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600 if private else 0o644)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=1)
    os.replace(tmp, path)


def settings() -> dict:
    s = _read("settings.json", {})
    out = json.loads(json.dumps(DEFAULT_SETTINGS))
    for k, v in (s.items() if isinstance(s, dict) else []):
        if k in out:
            out[k] = {**out[k], **v} if isinstance(out[k], dict) and isinstance(v, dict) else v
    return out


_HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def save_settings(body: dict) -> dict:
    cur = settings()
    if "timezone" in body:
        from zoneinfo import ZoneInfo
        try:
            ZoneInfo(str(body["timezone"]))
        except Exception as exc:  # noqa: BLE001
            raise InboxError(400, "unknown timezone") from exc
        cur["timezone"] = str(body["timezone"])
    qh = body.get("quiet_hours")
    if qh is not None:
        if not isinstance(qh, dict):
            raise InboxError(400, "quiet_hours must be an object")
        for k in ("start", "end"):
            if k in qh and not _HHMM.match(str(qh[k])):
                raise InboxError(400, f"quiet_hours.{k} must be HH:MM")
        cur["quiet_hours"] = {**cur["quiet_hours"], **{k: qh[k] for k in ("enabled", "start", "end") if k in qh}}
        cur["quiet_hours"]["enabled"] = bool(cur["quiet_hours"]["enabled"])
    for k in ("approvals_bypass_quiet", "deliver_push"):
        if k in body:
            cur[k] = bool(body[k])
    if isinstance(body.get("events"), dict):
        cur["events"] = {**cur["events"], **{k: bool(v) for k, v in body["events"].items() if k in cur["events"]}}
    if "vapid_subject" in body:
        sub = str(body["vapid_subject"])
        if not re.match(r"^(mailto:[^@\s]+@[^@\s]+|https://\S+)$", sub):
            raise InboxError(400, "vapid_subject must be mailto: or https:")
        cur["vapid_subject"] = sub
    _write("settings.json", cur)
    return cur


def in_quiet_hours(cfg: dict, at: float | None = None) -> bool:
    qh = cfg.get("quiet_hours") or {}
    if not qh.get("enabled"):
        return False
    from zoneinfo import ZoneInfo
    local = _dt.datetime.fromtimestamp(now() if at is None else at, ZoneInfo(cfg.get("timezone") or "America/Los_Angeles"))
    m = local.hour * 60 + local.minute
    sh, sm = map(int, qh["start"].split(":")); eh, em = map(int, qh["end"].split(":"))
    start, end = sh * 60 + sm, eh * 60 + em
    if start == end:
        return False
    return start <= m < end if start < end else (m >= start or m < end)


# ── Web Push: VAPID + aes128gcm (RFC 8291/8292) with `cryptography` only ──
def _b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _unb64u(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _vapid_key():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    path = _ndir() / "vapid.json"
    with _lock:
        if not path.exists():
            key = ec.generate_private_key(ec.SECP256R1())
            pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                    serialization.NoEncryption()).decode()
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w") as fh:
                json.dump({"private_key_pem": pem, "created_at": now()}, fh)
        os.chmod(path, 0o600)
        pem = json.loads(path.read_text())["private_key_pem"]
    return serialization.load_pem_private_key(pem.encode(), password=None)


def _raw_pub(pub) -> bytes:
    from cryptography.hazmat.primitives import serialization
    return pub.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)


def vapid_public_key() -> str:
    return _b64u(_raw_pub(_vapid_key().public_key()))


def vapid_header(endpoint: str, subject: str, ttl_s: int = 12 * 3600) -> str:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
    u = urlparse(endpoint)
    key = _vapid_key()
    head = _b64u(json.dumps({"typ": "JWT", "alg": "ES256"}, separators=(",", ":")).encode())
    claims = _b64u(json.dumps({"aud": f"{u.scheme}://{u.netloc}", "exp": int(now()) + ttl_s, "sub": subject},
                              separators=(",", ":")).encode())
    r, s = decode_dss_signature(key.sign(f"{head}.{claims}".encode(), ec.ECDSA(hashes.SHA256())))
    sig = _b64u(r.to_bytes(32, "big") + s.to_bytes(32, "big"))
    return f"vapid t={head}.{claims}.{sig}, k={_b64u(_raw_pub(key.public_key()))}"


def encrypt_payload(payload: bytes, p256dh: str, auth: str, *, salt: bytes | None = None, as_key=None) -> bytes:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    ua_pub_raw, auth_secret = _unb64u(p256dh), _unb64u(auth)
    ua_pub = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), ua_pub_raw)
    as_key = as_key or ec.generate_private_key(ec.SECP256R1())
    as_pub_raw = _raw_pub(as_key.public_key())
    shared = as_key.exchange(ec.ECDH(), ua_pub)
    ikm = HKDF(hashes.SHA256(), 32, auth_secret, b"WebPush: info\x00" + ua_pub_raw + as_pub_raw).derive(shared)
    salt = salt or os.urandom(16)
    cek = HKDF(hashes.SHA256(), 16, salt, b"Content-Encoding: aes128gcm\x00").derive(ikm)
    nonce = HKDF(hashes.SHA256(), 12, salt, b"Content-Encoding: nonce\x00").derive(ikm)
    body = AESGCM(cek).encrypt(nonce, payload + b"\x02", None)
    return salt + struct.pack("!IB", 4096, len(as_pub_raw)) + as_pub_raw + body


def _allowed_push_host(endpoint: str) -> bool:
    u = urlparse(endpoint)
    host = (u.hostname or "").lower()
    return u.scheme == "https" and (host in PUSH_HOSTS or host.endswith(PUSH_HOST_SUFFIXES))


def http_post(url: str, data: bytes, headers: dict) -> int:
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return int(resp.status)
    except urllib.error.HTTPError as exc:
        return int(exc.code)


def _sub_id(endpoint: str) -> str:
    return hashlib.sha256(endpoint.encode()).hexdigest()[:16]


def subscriptions() -> list[dict]:
    subs = _read("subscriptions.json", [])
    return subs if isinstance(subs, list) else []


def subscribe(body: dict) -> dict:
    sub = body.get("subscription") if isinstance(body.get("subscription"), dict) else body
    endpoint = str(sub.get("endpoint") or "")
    keys = sub.get("keys") if isinstance(sub.get("keys"), dict) else {}
    if not _allowed_push_host(endpoint):
        raise InboxError(400, "endpoint must be an https URL on a known push service")
    try:
        if len(_unb64u(str(keys.get("p256dh") or ""))) != 65 or len(_unb64u(str(keys.get("auth") or ""))) != 16:
            raise ValueError
    except Exception as exc:  # noqa: BLE001
        raise InboxError(400, "keys.p256dh (65 bytes) and keys.auth (16 bytes) are required, base64url") from exc
    rec = {"id": _sub_id(endpoint), "endpoint": endpoint, "keys": {"p256dh": keys["p256dh"], "auth": keys["auth"]},
           "label": str(body.get("label") or "")[:80], "created_at": now()}
    with _lock:
        subs = [s for s in subscriptions() if s.get("endpoint") != endpoint]
        subs.append(rec)
        _write("subscriptions.json", subs, private=True)
    return _public_sub(rec)


def unsubscribe(body: dict) -> dict:
    endpoint = str(body.get("endpoint") or (body.get("subscription") or {}).get("endpoint") or "")
    with _lock:
        subs = subscriptions()
        keep = [s for s in subs if s.get("endpoint") != endpoint]
        _write("subscriptions.json", keep, private=True)
    return {"removed": len(subs) - len(keep)}


def _public_sub(s: dict) -> dict:
    u = urlparse(s.get("endpoint", ""))
    return {"id": s.get("id"), "push_service": u.hostname, "label": s.get("label"), "created_at": s.get("created_at"),
            "last_status": s.get("last_status")}


def deliver(event: dict, cfg: dict) -> dict:
    """Send one event to every subscription. Expired subscriptions (404/410) are dropped."""
    if not cfg.get("deliver_push"):
        return {"push": "disabled"}
    payload = json.dumps({"title": event["title"], "body": event["body"], "kind": event["kind"],
                          "url": event.get("url", "/"), "id": event["id"], "tag": event.get("tag")}).encode()
    sent, dropped = 0, 0
    with _lock:
        subs = subscriptions()
        keep = []
        for s in subs:
            try:
                body = encrypt_payload(payload, s["keys"]["p256dh"], s["keys"]["auth"])
                status = http_post(s["endpoint"], body, {
                    "Content-Encoding": "aes128gcm", "Content-Type": "application/octet-stream", "TTL": "86400",
                    "Urgency": "high" if event["kind"] == "approval_needed" else "normal",
                    "Authorization": vapid_header(s["endpoint"], cfg.get("vapid_subject") or DEFAULT_SETTINGS["vapid_subject"])})
            except Exception as exc:  # noqa: BLE001
                status = f"error:{type(exc).__name__}"
            s["last_status"] = status
            if status in (404, 410):
                dropped += 1
                continue
            sent += 1 if isinstance(status, int) and 200 <= status < 300 else 0
            keep.append(s)
        _write("subscriptions.json", keep, private=True)
    return {"push": "sent", "delivered": sent, "dropped": dropped}


# ── events ────────────────────────────────────────────────────────────
def _emit(kind: str, title: str, body: str, ref: str, cfg: dict, **extra) -> dict | None:
    if not cfg["events"].get(kind, True):
        return None
    ev = {"id": hashlib.sha256(f"{kind}:{ref}:{now()}".encode()).hexdigest()[:16], "kind": kind, "title": title[:120],
          "body": body[:300], "ref": ref, "created_at": now(), "tag": f"{kind}:{ref}", **extra}
    quiet = in_quiet_hours(cfg)
    if quiet and not (kind == "approval_needed" and cfg.get("approvals_bypass_quiet")):
        ev["delivery"] = {"push": "suppressed_quiet_hours"}
    else:
        ev["delivery"] = deliver(ev, cfg)
    with _lock:
        feed = _read("feed.json", [])
        feed = ([ev] + (feed if isinstance(feed, list) else []))[:FEED_MAX]
        _write("feed.json", feed)
    return ev


def poll_once() -> dict:
    cfg = settings()
    seen = _read("seen.json", {})
    seen = seen if isinstance(seen, dict) else {}
    ap_seen, jobs_seen = set(seen.get("approvals", [])), dict(seen.get("jobs", {}))
    out, errors = [], []
    try:
        listing = list_approvals()
        current = {a["approval_id"]: a for a in listing["approvals"]}
        for aid, a in current.items():
            if aid not in ap_seen:
                ev = _emit("approval_needed", f"Approval needed: {a['tool'] or a['source']}",
                           f"{a['agent']}: {a['summary']}", aid, cfg, url=f"/?approval={quote(aid)}")
                out.append(ev)
        if not listing["sources_unavailable"]:
            ap_seen = set(current)          # forget resolved ids
        else:
            ap_seen |= set(current)
    except Exception as exc:  # noqa: BLE001
        errors.append({"source": "approvals", "error": type(exc).__name__})
    try:
        snap = jobs_snapshot()
        runner_down = snap.get("health") == "down"
        prev_down = bool(jobs_seen.get("__runner__", {}).get("down"))
        if runner_down and not prev_down and snap.get("jobs"):
            out.append(_emit("job_stuck", "Job runner is not responding",
                             f"No heartbeat for {snap.get('heartbeat_age_s')} s", "runner", cfg))
        jobs_seen["__runner__"] = {"down": runner_down}
        for job in snap.get("jobs") or []:
            tid = str(job.get("task_id") or "")
            if not tid:
                continue
            prev = jobs_seen.get(tid, {})
            state, stuck = job.get("state"), bool(job.get("stuck"))
            title = job.get("title") or tid
            if state in TERMINAL and prev.get("state") not in (None, state) and prev.get("state") not in TERMINAL:
                out.append(_emit("job_finished", f"Job {state.replace('_', ' ')}: {title}",
                                 f"{job.get('videos_done', 0)} analysed, {job.get('error_count', 0)} errors", tid, cfg))
            if stuck and not prev.get("stuck"):
                out.append(_emit("job_stuck", f"Job stuck: {title}",
                                 f"No progress for {round((job.get('last_progress_s') or 0) / 60)} min", tid, cfg))
            jobs_seen[tid] = {"state": state, "stuck": stuck}
    except Exception as exc:  # noqa: BLE001
        errors.append({"source": "jobs", "error": type(exc).__name__})
    _write("seen.json", {"approvals": sorted(ap_seen), "jobs": jobs_seen})
    return {"events": [e for e in out if e], "errors": errors}


def feed(query: str) -> dict:
    q = parse_qs(query or "")
    try:
        since = float((q.get("since") or ["0"])[0])
        limit = max(1, min(int((q.get("limit") or ["50"])[0]), FEED_MAX))
    except ValueError as exc:
        raise InboxError(400, "since and limit must be numbers") from exc
    items = [e for e in _read("feed.json", []) if float(e.get("created_at") or 0) > since]
    return {"items": items[:limit], "quiet_now": in_quiet_hours(settings())}


_poller: threading.Thread | None = None


def ensure_poller() -> None:
    """One daemon poller per process, started on first use of a notifications route."""
    global _poller
    if _poller is not None or os.environ.get("JAEGER_NOTIFY_POLLER") == "0":
        return

    def loop():
        while True:
            try:
                poll_once()
            except Exception:  # noqa: BLE001
                pass
            time.sleep(POLL_S)
    _poller = threading.Thread(target=loop, daemon=True, name="notify-poller")
    _poller.start()


# ── router ────────────────────────────────────────────────────────────
ROUTES = (
    ("GET", "/v1/inbox/approvals"), ("POST", "/v1/inbox/approvals/{id}/approve"), ("POST", "/v1/inbox/approvals/{id}/deny"),
    ("GET", "/v1/notifications/vapid-public-key"), ("POST", "/v1/notifications/subscribe"),
    ("POST", "/v1/notifications/unsubscribe"), ("GET", "/v1/notifications/subscriptions"),
    ("GET", "/v1/notifications/settings"), ("PUT", "/v1/notifications/settings"),
    ("GET", "/v1/notifications/feed"), ("POST", "/v1/notifications/poll"),
)


def handles(p: str) -> bool:
    return p.startswith("/v1/inbox/") or p.startswith("/v1/notifications/")


def route(handler, parsed, method: str, read_body, j) -> bool:
    p = parsed.path
    if not handles(p):
        return False
    try:
        body = read_body(handler) if method in ("POST", "PUT") else {}
        if not isinstance(body, dict):
            raise InboxError(400, "JSON object body required")
        if p.startswith("/v1/notifications/"):
            ensure_poller()
        m = re.match(r"^/v1/inbox/approvals/([A-Za-z0-9_:.\-]{1,200})/(approve|deny)$", p)
        if p == "/v1/inbox/approvals" and method == "GET":
            return j(handler, list_approvals()) or True
        if m and method == "POST":
            return act(handler, j, m.group(1), m.group(2), body)
        if p == "/v1/notifications/vapid-public-key" and method == "GET":
            return j(handler, {"public_key": vapid_public_key()}) or True
        if p == "/v1/notifications/subscribe" and method == "POST":
            return j(handler, subscribe(body), status=201) or True
        if p == "/v1/notifications/unsubscribe" and method == "POST":
            return j(handler, unsubscribe(body)) or True
        if p == "/v1/notifications/subscriptions" and method == "GET":
            return j(handler, {"subscriptions": [_public_sub(s) for s in subscriptions()]}) or True
        if p == "/v1/notifications/settings":
            if method == "GET":
                return j(handler, {**settings(), "quiet_now": in_quiet_hours(settings())}) or True
            if method == "PUT":
                return j(handler, save_settings(body)) or True
        if p == "/v1/notifications/feed" and method == "GET":
            return j(handler, feed(parsed.query)) or True
        if p == "/v1/notifications/poll" and method == "POST":
            return j(handler, poll_once()) or True
        raise InboxError(404, "not found")
    except InboxError as exc:
        return j(handler, exc.payload, status=exc.status) or True
