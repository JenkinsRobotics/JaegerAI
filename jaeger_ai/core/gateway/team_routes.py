"""Helper roster on the Gateway: specialist cards, avatars, and recent delegations.

The roster is the AgentRegistry (``metadata.team`` marks imported helper
profiles) running on the existing specialist path: a helper turn is a real
Gateway turn on its own session with its own persona, notes namespace, skill
scope, tool allowlist, hooks and approvals. Jaeger stays the lead and uses
``delegate``. Team rooms and @Name hand-offs have been removed.

  GET  /v1/team                        helper cards + recent delegations
  GET  /v1/team/agents/{id}/avatar     the pack's avatar image (if it has one)

ChildMirror still copies a helper's tool events onto the asking chat as
``subagent.tool.*`` so the Process view can draw the helper's steps.
"""

from __future__ import annotations

import asyncio
import logging
import mimetypes
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from aiohttp import web

logger = logging.getLogger("jaeger.gateway.team")

LEAD_ID = "native:jaeger"
_MIRROR = {"tool.started": "subagent.tool.started", "tool.completed": "subagent.tool.finished",
           "tool.done": "subagent.tool.finished", "tool.failed": "subagent.tool.finished",
           "tool.error": "subagent.tool.finished"}


class ChildMirror:
    """Mirror a member/child session's tool steps onto the session watching it."""

    def __init__(self, gateway) -> None:
        self.gw = gateway
        self._lock = threading.Lock()
        self._bound: dict[str, dict[str, str]] = {}

    def bind(self, child_session: str, target_session: str, request_id: str, span: str) -> None:
        with self._lock:
            self._bound[child_session] = {"target": target_session, "request_id": request_id, "span": span}

    def unbind(self, child_session: str) -> None:
        with self._lock:
            self._bound.pop(child_session, None)

    def observe(self, evt) -> None:
        name = getattr(evt, "event", "")
        if name not in _MIRROR and name != "loop.iteration":
            return
        with self._lock:
            bound = self._bound.get(getattr(evt, "session_id", ""))
        if not bound:
            return
        data = dict(getattr(evt, "data", None) or {})
        if name == "loop.iteration":
            if data.get("subagent_id"):
                return
            payload = {k: data.get(k) for k in ("index", "max", "decision", "reason")}
        else:
            call = data.get("call_id") or data.get("activity_id")
            if not call:
                return
            payload = {"call_id": call, "tool": data.get("tool"), "elapsed_s": data.get("elapsed_s"),
                       "outcome": data.get("outcome")}
            if _MIRROR[name] == "subagent.tool.finished":
                payload["ok"] = name in {"tool.completed", "tool.done"} and data.get("ok") is not False
        payload.update({"request_id": bound["request_id"], "subagent_id": bound["span"],
                        "child_session_id": evt.session_id})
        try:
            self.gw.event_bus.publish(bound["target"], _MIRROR.get(name, name), payload)
        except Exception:  # noqa: BLE001 — mirroring never breaks the child turn
            logger.debug("team mirror failed", exc_info=True)


def _meta(record: Any) -> dict[str, Any]:
    meta = getattr(record, "metadata", None) or {}
    return meta if isinstance(meta, dict) else {}


def team_members(gateway) -> list[Any]:
    """Imported team agents (``metadata.team``) after the lead, in registry order."""
    agents = gateway._registry().list_agents()
    team = [a for a in agents if _meta(a).get("team") and not getattr(a, "disabled", False)]
    lead = [a for a in agents if a.id == LEAD_ID]
    return lead + team


def avatar_path(record: Any) -> Path | None:
    meta = _meta(record)
    pack, name = meta.get("pack_path"), meta.get("avatar_file")
    if not pack or not name:
        return None
    path = (Path(pack) / str(name)).resolve()
    return path if path.is_file() and path.is_relative_to(Path(pack).resolve()) else None


def _avatar_data_url(record: Any) -> str | None:
    """Small pack avatars inline as a data URL (no extra request per card)."""
    path = avatar_path(record)
    if path is None or path.stat().st_size > 300 * 1024:
        return None
    import base64
    mime = mimetypes.guess_type(path.name)[0] or "image/png"
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode('ascii')}"


def _avatar_url(record: Any) -> str | None:
    """Small avatars inline; larger ones by the avatar route (relayed by the WebUI on 8790)."""
    inline = _avatar_data_url(record)
    if inline or avatar_path(record) is None:
        return inline
    from urllib.parse import quote
    return f"/v1/team/agents/{quote(str(record.id), safe='')}/avatar"


def agent_card(record: Any, *, live: dict[str, dict[str, Any]], statuses: dict[str, str]) -> dict[str, Any]:
    meta = _meta(record)
    role = getattr(getattr(record, "role", None), "value", getattr(record, "role", ""))
    from jaeger_ai.core.agent_registry.specialists import specialist_skills, specialist_tools
    activity = live.get(record.id) or {}
    return {
        "id": record.id, "name": record.name, "display_name": record.display_name,
        "role": "lead" if record.id == LEAD_ID else role,
        "team": meta.get("team"), "description": meta.get("summary") or meta.get("specialty") or "",
        "persona": meta.get("operator_instructions") or "",
        "skills": specialist_skills(record) or [], "tools": specialist_tools(record) or [],
        "avatar": {"seed": meta.get("avatar_seed") or record.id, "url": _avatar_url(record)},
        "pack": "character/v1" if meta.get("character_schema") else None,
        "status": activity.get("status") or statuses.get(record.id) or "idle",
        "activity": activity or None,
    }


def _handoff_row(h: dict[str, Any]) -> dict[str, Any]:
    """A /v1/team handoff row: a team hand-off (``call_agent``) or an inner
    helper run (``delegate``), with the helper's usage when it finished."""
    meta = h.get("metadata") or {}
    result = h.get("result") or {}
    rmeta = result.get("metadata") or {}
    row = {"kind": "delegate" if meta.get("collaboration") == "delegate" else "call_agent",
           **{k: h.get(k) for k in ("id", "from_agent_id", "to_agent_id", "status", "task",
                                    "session_id", "created_at", "updated_at")}}
    if row["kind"] == "delegate":
        row.update({"tokens": rmeta.get("tokens"), "result_path": rmeta.get("result_path"),
                    "summary": str(result.get("summary") or "")[:400] or None,
                    "via": meta.get("via")})
    return row


def register(gateway) -> None:
    mirror = ChildMirror(gateway)
    gateway.team_mirror = mirror
    gateway._team_live: dict[str, dict[str, Any]] = {}
    add = getattr(gateway.event_bus, "add_observer", None)
    if add:
        add(mirror.observe)

    def registry_member(agent_id: str) -> Any | None:
        rec = gateway._registry().get_agent(agent_id)
        return rec if rec is not None and not getattr(rec, "disabled", False) else None

    async def team(request: web.Request) -> web.Response:
        try:
            from .agents_tab_routes import agent_statuses
            statuses = await asyncio.to_thread(agent_statuses, gateway)
        except Exception:  # noqa: BLE001
            statuses = {}
        members = await asyncio.to_thread(team_members, gateway)
        # Delegations that involve a helper profile (not the lead's other specialists).
        ids = {m.id for m in members if m.id != LEAD_ID}
        handoffs = [h for h in gateway.store.list_handoffs(limit=200)
                    if h.get("to_agent_id") in ids or h.get("from_agent_id") in ids][:20]
        return web.json_response({
            "agents": [agent_card(m, live=gateway._team_live, statuses=statuses) for m in members],
            "handoffs": [_handoff_row(h) for h in handoffs],
        })

    async def avatar(request: web.Request) -> web.StreamResponse:
        rec = gateway._registry().get_agent(request.match_info["id"])
        path = avatar_path(rec) if rec is not None else None
        if path is None:
            return web.json_response({"error": "no avatar"}, status=404)
        return web.FileResponse(path, headers={"Content-Type": mimetypes.guess_type(path.name)[0] or "application/octet-stream",
                                               "Cache-Control": "max-age=300"})

    app = gateway.app
    app.router.add_get("/v1/team", team)
    app.router.add_get("/v1/team/agents/{id}/avatar", avatar)
