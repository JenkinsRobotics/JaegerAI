"""Agents tab Gateway routes (shapes: /workspace/jaeger-agents-tab-api-shapes.md).

  GET  /v1/activity                 G1 durable, paged activity history
  POST /v1/handoffs/{id}/check      G2 owner check of a terminal handoff
"""
from __future__ import annotations

from aiohttp import web


def register(gateway) -> None:
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
