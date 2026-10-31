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

    gateway.app.router.add_get("/v1/activity", activity)
