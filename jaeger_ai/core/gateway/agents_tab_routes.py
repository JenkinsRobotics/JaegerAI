"""Agents tab Gateway routes (shapes: /workspace/jaeger-agents-tab-api-shapes.md).

  GET  /v1/activity                 G1 durable, paged activity history
  POST /v1/handoffs/{id}/check      G2 owner check of a terminal handoff
"""
from __future__ import annotations

import logging
import threading
import time

from aiohttp import web

TRIGGERS = ("agent.handoff", "agent.handoff.finished", "agent.handoff.checked", "task.created", "task.updated",
            "approval.request", "approval.resolved")


def agent_statuses(gateway) -> dict[str, str]:
    """Same computation as GET /v1/agents/summary (agent_summary.summarize_agents)."""
    from jaeger_ai.core.gateway.agent_summary import summarize_agents
    registry = gateway._registry()
    agents = [a.to_dict() for a in registry.list_agents() if a.role.value in {"lead", "specialist"}]
    tasks = [t.to_dict() for t in gateway.task_owner.store.list_tasks()] if gateway.task_owner else []
    out = summarize_agents(agents, tasks=tasks, handoffs=gateway.store.list_handoffs(limit=500),
                           sessions=gateway.store.list_sessions(), seen={},
                           requests=[r for st in ("admitted", "queued", "running", "awaiting_approval", "cancelling")
                                     for r in gateway.store.list_requests(status=st)])
    return {row["id"] if "id" in row else row.get("agent_id"): row.get("status") for row in out["agents"]}


class StatusWatcher:
    """G6: publish agent.status.changed on a real change after handoff/task/approval events."""
    def __init__(self, gateway):
        self.gw, self.cache, self._busy = gateway, None, threading.local()

    def observe(self, evt) -> None:
        if getattr(evt, "event", None) not in TRIGGERS or getattr(self._busy, "on", False):
            return
        self._busy.on = True
        try:
            now = agent_statuses(self.gw)
            if self.cache is None:
                self.cache = now
                return
            data = evt.data or {}
            h = data.get("handoff") if isinstance(data.get("handoff"), dict) else {}
            t = data.get("task") if isinstance(data.get("task"), dict) else {}
            for aid, status in now.items():
                prev = self.cache.get(aid)
                if prev is not None and status != prev:
                    self.gw.event_bus.publish("*", "agent.status.changed", {
                        "agent_id": aid, "status": status, "previous": prev, "reason": evt.event,
                        "handoff_id": h.get("id") or data.get("handoff_id"),
                        "task_id": t.get("task_id") or h.get("task_id") or data.get("task_id"), "at": time.time()})
            self.cache = {**self.cache, **now}
        except Exception:  # noqa: BLE001 - status events never break publishing
            logging.getLogger(__name__).debug("agent status watch failed", exc_info=True)
        finally:
            self._busy.on = False


def register(gateway) -> None:
    watcher = StatusWatcher(gateway)
    gateway.agent_status_watcher = watcher
    add = getattr(gateway.event_bus, "add_observer", None)
    if add:
        add(watcher.observe)

    async def _prime(_app):  # baseline so the first real change is evented
        try:
            watcher.cache = agent_statuses(gateway)
        except Exception:  # noqa: BLE001
            pass
    gateway.app.on_startup.append(_prime)

    async def activity(request):
        q = request.query
        try:
            before = int(q["before"]) if q.get("before") else None
            since = float(q["since"]) if q.get("since") else None
            limit = int(q.get("limit") or 50)
            if not 1 <= limit <= 200 or (before is not None and before < 1):
                raise ValueError
        except ValueError:
            return web.json_response({"error": "before must be a positive integer, since epoch seconds, limit 1-200"},
                                     status=400)
        kinds = [k.strip() for k in (q.get("kind") or "").split(",") if k.strip()] or None
        needs_me = q.get("needs_me") in ("1", "true")
        pending = {a["approval_id"] for a in gateway.store.list_pending_approvals()}
        return web.json_response(gateway.store.agent_activity(
            before=before, since=since, agent_id=q.get("agent_id") or None, kinds=kinds,
            needs_me=needs_me, limit=limit, pending_approvals=pending))

    async def check(request):
        import time
        from .handoff_outputs import EVIDENCE_REF
        try:
            body = await request.json()
            if not isinstance(body, dict):
                raise ValueError
        except (ValueError, TypeError):
            return web.json_response({"error": "JSON object required"}, status=400)
        state, ref = body.get("state"), body.get("evidence_ref")
        if state not in ("passed", "failed"):
            return web.json_response({"error": "state must be passed or failed"}, status=400)
        if ref is not None and (not isinstance(ref, str) or not EVIDENCE_REF.match(ref)):
            return web.json_response({"error": "evidence_ref must be task:|handoff:|url:http(s)|file:"}, status=400)
        note = body.get("note")
        if note is not None and (not isinstance(note, str) or len(note) > 500):
            return web.json_response({"error": "note must be text of at most 500 characters"}, status=400)
        caller = request.get("caller_actor") or request.get("caller")
        who = str(getattr(caller, "name", None) or caller or "owner")
        record, err = gateway.store.set_handoff_check(request.match_info["id"], {
            "state": state, "evidence_ref": ref, "checked_by": f"owner:{who}" if not who.startswith("owner") else who,
            "checked_at": time.time(), "note": note}, expected_state=body.get("expected_state"))
        if err == "not_found":
            return web.json_response({"error": "Handoff not found"}, status=404)
        if err:
            return web.json_response({"error": "Handoff is not finished yet" if err == "not_terminal"
                                      else "Check changed; reload", "check": record["check"]}, status=409)
        gateway._publish_handoff("agent.handoff.checked", record)
        return web.json_response(record)

    def task_exists(tid):
        try:
            return gateway.task_owner.store.get_task(tid) is not None
        except Exception:  # noqa: BLE001
            return False
    gateway.store.task_lookup = task_exists

    gateway.app.router.add_get("/v1/activity", activity)
    gateway.app.router.add_post("/v1/handoffs/{id}/check", check)
