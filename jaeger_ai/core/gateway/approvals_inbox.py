"""Approvals inbox (APPROVALS-NOTIFICATIONS-SPEC §2, §3, §9): item projection,
decisions with reasons, ask-for-changes, low-risk batch, audit trail and counts.

Builds on the existing ``approvals`` table and the gateway's one resolve path
(``JaegerGatewayApp.resolve_pending``), so futures, task owners, handoffs and
``approval.resolved`` behave exactly as for ``POST /v1/approvals/{id}``.

Routes (register before ``/v1/approvals/{id}``):
  GET  /v1/approvals?type=&risk=&agent_id=&sort=expiry|risk   (projected; existing route, additive fields)
  GET  /v1/approvals/counts
  POST /v1/approvals/batch            {ids[], decision: approve|deny, reason?, device?}
  POST /v1/approvals/{id}/decide      {decision: approve|deny|changes, reason?, scope?: once|session|always,
                                       expected_revision?, device?, reason_chips?[]}
  POST /v1/approvals/{id}/viewed      {device?}
  GET  /v1/approvals/{id}/events[?format=csv]
"""
from __future__ import annotations

import csv
import io
import json
import re
import time
from typing import Any

from aiohttp import web

TYPES = ("code_change", "spend", "send", "permission", "design_review", "tool_confirm")
RISKS = ("low", "medium", "high", "critical")
RANK = {r: i for i, r in enumerate(RISKS)}
ON_EXPIRE = ("deny", "escalate", "keep")
PAYLOAD_KEYS = {
    "code_change": ("repo", "branch", "base", "pr", "files", "checks"),
    "spend": ("amount", "currency", "payee", "method_last4", "month_to_date", "limit"),
    "send": ("channel", "to", "subject", "preview", "attachments"),
    "permission": ("capability", "target", "duration"),
    "design_review": ("artifacts", "comments"),
    "tool_confirm": ("tool", "arguments", "server"),
}
AUDIT_EVENTS = ("created", "viewed", "pushed", "decided", "changes_requested", "expired", "escalated", "undone")
DESTRUCTIVE = re.compile(r"(delete|remove|\brm\b|drop|truncate|push|deploy|merge|publish|send|pay|purchase|write|kill)", re.I)
MIN_REASON = 3


# ── projection ───────────────────────────────────────────────────────
def item_type(row: dict) -> str:
    meta = row.get("metadata") or {}
    if meta.get("type") in TYPES:
        return meta["type"]
    kind = str(row.get("kind") or "").lower()
    if kind in TYPES:
        return kind
    if any(k in kind for k in ("spend", "purchase", "pay")):
        return "spend"
    if any(k in kind for k in ("send", "email", "message")):
        return "send"
    if any(k in kind for k in ("design", "review")):
        return "design_review"
    if any(k in kind for k in ("code", "merge", "commit", "pr")):
        return "code_change"
    if any(k in kind for k in ("handoff", "task", "permission", "capability", "delegate")):
        return "permission"
    return "tool_confirm"


def assess_risk(row: dict, typ: str, payload: dict) -> tuple[str, list[str]]:
    """Policy floor by type; a bot self-assessment may raise it, never lower it.
    An explicit ``metadata.policy_risk`` (authority kernel) wins outright."""
    meta = row.get("metadata") or {}
    if meta.get("policy_risk") in RISKS:
        return meta["policy_risk"], [str(r) for r in meta.get("risk_reasons") or []] or ["Set by policy"]
    reasons: list[str] = []
    floor = {"spend": "high", "send": "high", "permission": "medium", "code_change": "medium",
             "design_review": "low"}.get(typ, "low")
    if typ in ("spend", "send"):
        reasons.append("Spends money" if typ == "spend" else "Sends on your behalf")
    if typ == "permission" and str(payload.get("duration") or meta.get("scope") or "") == "always":
        floor = "high"; reasons.append("Permanent permission")
    if typ == "tool_confirm":
        tool = str(payload.get("tool") or meta.get("tool") or row.get("prompt") or "")
        if meta.get("destructive") or DESTRUCTIVE.search(tool):
            floor = "high"; reasons.append("Destructive or outbound tool")
    if typ == "spend":
        try:
            if payload.get("limit") is not None and float(payload.get("month_to_date") or 0) + float(payload.get("amount") or 0) > float(payload["limit"]):
                floor = "critical"; reasons.append("Over monthly limit")
        except (TypeError, ValueError):
            pass
    bot = meta.get("risk") if meta.get("risk") in RISKS else None
    if bot and RANK[bot] > RANK[floor]:
        reasons.append("Raised by the agent's own assessment")
        floor = bot
    reasons += [str(r) for r in meta.get("risk_reasons") or [] if str(r) not in reasons]
    return floor, reasons


def project(row: dict) -> dict:
    meta = row.get("metadata") or {}
    typ = item_type(row)
    raw = meta.get("payload") if isinstance(meta.get("payload"), dict) else {}
    payload = {k: raw[k] for k in PAYLOAD_KEYS[typ] if k in raw}
    risk, reasons = assess_risk(row, typ, payload)
    if meta.get("escalated") and RANK[risk] < RANK["high"]:
        risk, reasons = "high", reasons + ["Escalated after expiry"]
    options = list(row.get("options") or [])
    if row.get("status") == "pending" and "changes" not in options:
        options.append("changes")
    expires = meta.get("expires_at")
    batch_group = meta.get("batch_group") if isinstance(meta.get("batch_group"), str) else None
    batchable = risk == "low" or (risk == "medium" and bool(batch_group))
    return {
        **row,
        "type": typ,
        "agent_id": meta.get("agent_id") or (row.get("origin") or {}).get("agent_id"),
        "task_id": meta.get("task_id"),
        "title": meta.get("title") or (row.get("prompt") or "")[:120],
        "summary": meta.get("summary") or row.get("prompt") or "",
        "why": meta.get("why"),
        "risk": risk,
        "risk_reasons": reasons,
        "expires_at": float(expires) if isinstance(expires, (int, float)) else None,
        "on_expire": meta.get("on_expire") if meta.get("on_expire") in ON_EXPIRE else "deny",
        "options": options,
        "reversible": bool(meta.get("reversible", typ in ("design_review", "tool_confirm"))),
        "scope": meta.get("scope"),
        "batch_group": batch_group,
        "batchable": batchable,
        "requires_step_up": typ in ("spend", "send") or risk == "critical"
                            or (typ == "permission" and payload.get("duration") == "always"),
        "approve_on_mac": typ in ("spend", "send") or risk == "critical"
                          or (typ == "permission" and payload.get("duration") == "always"),
        "payload": payload,
        "revision": int(meta.get("revision") or 1),
        "reason": meta.get("decision_reason"),
        "decided_by_device": meta.get("decided_by_device"),
    }


def filter_sort(items: list[dict], query) -> list[dict]:
    for key in ("type", "risk", "agent_id"):
        want = (query.get(key) or "").strip()
        if want:
            allowed = set(want.split(","))
            items = [i for i in items if str(i.get(key)) in allowed]
    sort = query.get("sort") or "created"
    if sort == "expiry":
        items.sort(key=lambda i: (i["expires_at"] is None, i["expires_at"] or 0, i["created_at"]))
    elif sort == "risk":
        items.sort(key=lambda i: (-RANK[i["risk"]], i["expires_at"] or float("inf"), i["created_at"]))
    return items


# ── audit trail (append-only) ────────────────────────────────────────
def _ensure_audit(conn) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS approval_audit(
        id INTEGER PRIMARY KEY AUTOINCREMENT, approval_id TEXT NOT NULL, event TEXT NOT NULL,
        actor TEXT, device TEXT, reason TEXT, ts REAL NOT NULL, data_json TEXT NOT NULL DEFAULT '{}')""")
    conn.execute("CREATE INDEX IF NOT EXISTS approval_audit_by_id ON approval_audit(approval_id, id)")


def audit(store, approval_id: str, event: str, *, actor: str | None = None, device: str | None = None,
          reason: str | None = None, data: dict | None = None, once: bool = False) -> None:
    with store._immediate() as conn:
        _ensure_audit(conn)
        if once and conn.execute("SELECT 1 FROM approval_audit WHERE approval_id=? AND event=?",
                                 (approval_id, event)).fetchone():
            return
        conn.execute("INSERT INTO approval_audit(approval_id,event,actor,device,reason,ts,data_json) VALUES(?,?,?,?,?,?,?)",
                     (approval_id, event, actor, device, reason, time.time(), json.dumps(data or {})))


def audit_events(store, approval_id: str) -> list[dict]:
    row = store.get_approval(approval_id)
    if row is None:
        return []
    with store._immediate() as conn:
        _ensure_audit(conn)
        rows = conn.execute("SELECT * FROM approval_audit WHERE approval_id=? ORDER BY id", (approval_id,)).fetchall()
    meta = row.get("metadata") or {}
    out = [{"event": "created", "actor": meta.get("agent_id") or "agent", "device": None, "reason": None,
            "ts": row["created_at"], "data": {"kind": row.get("kind")}}]
    out += [{"event": r["event"], "actor": r["actor"], "device": r["device"], "reason": r["reason"], "ts": r["ts"],
             "data": json.loads(r["data_json"] or "{}")} for r in rows]
    return out


def _set_meta(store, approval_id: str, **values) -> None:
    with store._immediate() as conn:
        r = conn.execute("SELECT metadata_json FROM approvals WHERE approval_id=?", (approval_id,)).fetchone()
        if r is None:
            return
        meta = json.loads(r[0] or "{}")
        meta.update({k: v for k, v in values.items() if v is not None})
        conn.execute("UPDATE approvals SET metadata_json=? WHERE approval_id=?", (json.dumps(meta), approval_id))


# ── decisions ────────────────────────────────────────────────────────
class DecisionError(Exception):
    def __init__(self, status: int, code: str, message: str, item: dict | None = None):
        super().__init__(message)
        self.status, self.code, self.message, self.item = status, code, message, item

    def body(self) -> dict:
        out = {"error": self.message, "code": self.code}
        if self.item is not None:
            out["approval"] = self.item
        return out


def _clean_reason(body: dict) -> str:
    chips = [str(c).strip()[:40] for c in body.get("reason_chips") or [] if str(c).strip()]
    note = str(body.get("reason") or "").strip()[:2000]
    return "; ".join(chips + ([note] if note else []))


def decide(gateway, approval_id: str, body: dict, *, actor: str = "owner", batch: bool = False) -> dict:
    store = gateway.store
    decision = str(body.get("decision") or "").lower()
    if decision not in ("approve", "deny", "changes"):
        raise DecisionError(400, "bad_decision", "decision must be approve, deny or changes")
    reason = _clean_reason(body)
    if decision in ("deny", "changes") and len(reason) < MIN_REASON:
        raise DecisionError(400, "reason_required", "A reason (a chip or at least 3 characters) is required to "
                            + ("deny" if decision == "deny" else "ask for changes"))
    row = store.get_approval(approval_id)
    if row is None:
        raise DecisionError(404, "not_found", "Approval not found")
    item = project(gateway._with_origin(row))
    if row["status"] != "pending":
        raise DecisionError(409, "already_resolved", f"Already {row.get('decision') or 'resolved'}; reload", item)
    exp = body.get("expected_revision")
    if exp is not None and exp != item["revision"]:
        raise DecisionError(409, "stale", "Changed, reload", item)
    if item["expires_at"] is not None and item["expires_at"] <= time.time() and item["on_expire"] != "keep":
        raise DecisionError(409, "expired", "This approval has expired", item)
    if batch and decision == "approve" and not item["batchable"]:
        raise DecisionError(422, "not_batchable",
                            f"Not batchable: {item['risk']} risk" + ("" if item["risk"] != "medium" else " without a batch group"), item)
    if decision == "approve" and item["requires_step_up"]:
        # No server-side passkey verifier yet (supervisor decision): approve these in the Mac app.
        raise DecisionError(403, "step_up_required",
                            "This approval needs step-up; approve it in the Jaeger app on the Mac", item)
    if decision == "approve":
        scope = str(body.get("scope") or "once")
        options = [o for o in row.get("options") or []]
        if scope not in ("once", "session", "always"):
            raise DecisionError(400, "bad_scope", "scope must be once, session or always")
        positive = [o for o in options if o not in ("deny", "changes")]
        if scope in options or not options:
            choice = scope
        elif scope == "once" and positive:
            choice = positive[0]
        else:
            raise DecisionError(400, "scope_not_offered", f"This approval does not offer '{scope}'")
        approved = True
    else:
        choice, approved = ("deny" if decision == "deny" else "changes"), False
    device = str(body.get("device") or "")[:80] or None
    _set_meta(store, approval_id, decision_reason=reason or None, decided_by_device=device,
              changes_requested=reason if decision == "changes" else None)
    result = gateway.resolve_pending(approval_id, approved=approved, decision=choice,
                                     extra={"reason": reason or None, "device": device, "requested_changes": decision == "changes"})
    if result is None:
        fresh = store.get_approval(approval_id)
        raise DecisionError(409, "stale", "Changed, reload", project(gateway._with_origin(fresh)) if fresh else None)
    audit(store, approval_id, "changes_requested" if decision == "changes" else "decided", actor=actor, device=device,
          reason=reason or None, data={"decision": choice, "batch": batch})
    if decision == "changes":
        if row.get("session_id"):
            try:  # the existing session message path; the agent reads it as owner feedback
                store.append_message(row["session_id"], "user",
                                     f"Changes requested on '{item['title']}': {reason}",
                                     meta={"approval_id": approval_id, "changes_requested": True,
                                           "task_id": item["task_id"]})
            except Exception:  # noqa: BLE001 - the decision itself is already durable
                import logging
                logging.getLogger(__name__).warning("changes message not posted for %s", approval_id, exc_info=True)
        gateway.event_bus.publish(row.get("session_id") or "*", "approval.changes_requested", {
            "approval_id": approval_id, "session_id": row.get("session_id"), "reason": reason,
            "task_id": item["task_id"], "agent_id": item["agent_id"],
            "message": f"Changes requested on '{item['title']}': {reason}"})
    fresh = store.get_approval(approval_id)
    return {**result, "approval": project(gateway._with_origin(fresh)) if fresh else None}


def sweep_expired(gateway, now: float | None = None) -> list[str]:
    """Apply on_expire to overdue items: deny → resolved 'expired'; escalate → raise to high once; keep → nothing."""
    now = now or time.time()
    done = []
    for row in gateway.store.list_pending_approvals():
        item = project(row)
        if item["expires_at"] is None or item["expires_at"] > now:
            continue
        if item["on_expire"] == "deny":
            if gateway.resolve_pending(row["approval_id"], approved=False, decision="expired",
                                       extra={"reason": "expired"}) is not None:
                audit(gateway.store, row["approval_id"], "expired", actor="system")
                done.append(row["approval_id"])
        elif item["on_expire"] == "escalate" and not (row.get("metadata") or {}).get("escalated"):
            _set_meta(gateway.store, row["approval_id"], escalated=True)
            audit(gateway.store, row["approval_id"], "escalated", actor="system", once=True)
            done.append(row["approval_id"])
    return done


def pending_items(gateway) -> list[dict]:
    return [project(gateway._with_origin(r)) for r in gateway.store.list_pending_approvals()]


def counts(gateway) -> dict:
    items = pending_items(gateway)
    soon = time.time() + 3600
    return {
        "pending": len(items),
        "by_risk": {r: sum(i["risk"] == r for i in items) for r in RISKS},
        "by_type": {t: sum(i["type"] == t for i in items) for t in TYPES},
        "batchable": sum(i["batchable"] for i in items),
        "expiring_within_1h": sum(1 for i in items if i["expires_at"] is not None and i["expires_at"] <= soon),
    }


# ── routes ───────────────────────────────────────────────────────────
def _actor(request) -> str:
    caller = request.get("caller")
    return str(getattr(caller, "name", None) or getattr(caller, "kind", None) or "owner")


async def _json(request) -> dict:
    if not request.can_read_body:
        return {}
    body = await request.json()
    if not isinstance(body, dict):
        raise ValueError("object required")
    return body


def register(gateway) -> None:
    async def list_counts(request):
        sweep_expired(gateway)
        return web.json_response(counts(gateway))

    async def decide_one(request):
        try:
            body = await _json(request)
        except (ValueError, TypeError):
            return web.json_response({"error": "JSON object required"}, status=400)
        try:
            return web.json_response(decide(gateway, request.match_info["id"], body, actor=_actor(request)))
        except DecisionError as exc:
            return web.json_response(exc.body(), status=exc.status)

    async def batch(request):
        try:
            body = await _json(request)
            ids = body.get("ids")
            if not isinstance(ids, list) or not ids or len(ids) > 200 or any(not isinstance(i, str) for i in ids):
                raise ValueError
        except (ValueError, TypeError):
            return web.json_response({"error": "ids (1-200 strings) required"}, status=400)
        if body.get("decision") not in ("approve", "deny"):
            return web.json_response({"error": "batch decision must be approve or deny"}, status=400)
        results = []
        for aid in dict.fromkeys(ids):
            try:
                out = decide(gateway, aid, {k: body.get(k) for k in ("decision", "reason", "reason_chips", "device")},
                             actor=_actor(request), batch=True)
                results.append({"approval_id": aid, "ok": True, "decision": out.get("decision")})
            except DecisionError as exc:
                results.append({"approval_id": aid, "ok": False, "status": exc.status, "code": exc.code, "error": exc.message})
        ok = sum(r["ok"] for r in results)
        return web.json_response({"results": results, "approved" if body["decision"] == "approve" else "denied": ok,
                                  "rejected": len(results) - ok})

    async def viewed(request):
        aid = request.match_info["id"]
        if gateway.store.get_approval(aid) is None:
            return web.json_response({"error": "Approval not found"}, status=404)
        try:
            body = await _json(request)
        except (ValueError, TypeError):
            body = {}
        audit(gateway.store, aid, "viewed", actor=_actor(request), device=str(body.get("device") or "")[:80] or None)
        return web.json_response({"ok": True})

    async def events(request):
        aid = request.match_info["id"]
        caller = request.get("caller")
        prefix = getattr(caller, "session_prefix", None)
        row = gateway.store.get_approval(aid)
        if row is None or (prefix and not str(row.get("session_id") or "").startswith(prefix)):
            return web.json_response({"error": "Approval not found"}, status=404)
        evs = audit_events(gateway.store, aid)
        if request.query.get("format") == "csv":
            buf = io.StringIO()
            w = csv.writer(buf)
            w.writerow(["approval_id", "event", "actor", "device", "reason", "time_utc"])
            for e in evs:
                w.writerow([aid, e["event"], e["actor"] or "", e["device"] or "", e["reason"] or "",
                            time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(e["ts"]))])
            return web.Response(text=buf.getvalue(), content_type="text/csv",
                                headers={"Content-Disposition": f'attachment; filename="{aid}-audit.csv"'})
        return web.json_response({"approval_id": aid, "events": evs})

    async def create_request(request):
        """Owner-surface actions (widgets, automations) ask through the inbox.
        {source: widget|automation, title, summary?, type?, risk: low|medium|high|critical, payload?, action:{...}}"""
        try:
            body = await _json(request)
            source = body.get("source")
            title = str(body.get("title") or "").strip()[:160]
            if source not in ("widget", "automation") or not title or body.get("risk") not in RISKS:
                raise ValueError
        except (ValueError, TypeError):
            return web.json_response({"error": "source (widget|automation), title and risk are required"}, status=400)
        typ = body.get("type") if body.get("type") in TYPES else "permission"
        meta = {"type": typ, "title": title, "summary": str(body.get("summary") or title)[:500],
                "policy_risk": body["risk"], "risk_reasons": [f"{source} action"], "agent_id": source,
                "payload": body.get("payload") if isinstance(body.get("payload"), dict) else {},
                "source": source, "action": body.get("action") if isinstance(body.get("action"), dict) else {},
                "host": str(body.get("host") or "page")[:20], "batch_group": None,
                "expires_at": time.time() + 3600, "on_expire": "deny"}
        row = gateway.store.create_approval(kind=f"{source}_action", prompt=title, options=["once", "deny"], metadata=meta)
        gateway.event_bus.publish("*", "approval.request", {**row, "agent_id": source})
        return web.json_response({"approval": project(row)}, status=201)

    r = gateway.app.router
    r.add_post("/v1/approvals/requests", create_request)
    r.add_get("/v1/approvals/counts", list_counts)
    r.add_post("/v1/approvals/batch", batch)
    r.add_post("/v1/approvals/{id}/decide", decide_one)
    r.add_post("/v1/approvals/{id}/viewed", viewed)
    r.add_get("/v1/approvals/{id}/events", events)
