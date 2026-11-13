"""Team runtime on the Gateway: roster, group rooms, and live agent lanes.

The team is the AgentRegistry (``metadata.team`` marks imported team agents)
running on the existing specialist path: every member turn is a real Gateway
turn on its own session (``_specialist_chat``) with its own persona, notes
namespace, skill scope, tool allowlist, hooks and approvals. Nothing here is a
second execution stack.

  GET  /v1/team                        roster cards + rooms + recent handoffs
  GET  /v1/team/agents/{id}/avatar     the pack's avatar image (if it has one)
  POST /v1/team/rooms                  {title, members[], probe?} -> room session
  GET  /v1/team/rooms/{id}             room + transcript (oldest first)
  POST /v1/team/rooms/{id}/messages    {text} -> members take turns (202)

Events (contract/trace.py): ``room.started`` / ``room.finished`` bracket one
person message (a run); ``room.turn`` is one member's turn (an agent span,
nested under the turn that @-handed it); ``agent.message`` is what a member
said. A member's own tool calls are mirrored onto the room (and a handoff's
child steps onto the asking chat) as ``subagent.tool.*`` under that agent span,
so the Process view draws each agent as a lane with its real steps.

Room rules: OpenBot group rooms (MIT; @Name hands the room to a peer, depth and
fan-out caps refuse rather than truncate, refusals are recorded) and the
OpenMausBot/Hermes "(pass)" rule. See jaeger_ai/core/team/mentions.py.
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

ROOM_MAX_TURNS = 6        # member turns one person message may cause
ROOM_MAX_DEPTH = 2        # @-hand-off chain depth (person message = 0)
ROOM_MAX_PER_REPLY = 3    # peers one reply may address
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
    """Small pack avatars inline as a data URL (the WebUI relay is JSON-only)."""
    path = avatar_path(record)
    if path is None or path.stat().st_size > 300 * 1024:
        return None
    import base64
    mime = mimetypes.guess_type(path.name)[0] or "image/png"
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode('ascii')}"


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
        "avatar": {"seed": meta.get("avatar_seed") or record.id, "url": _avatar_data_url(record)},
        "pack": "character/v1" if meta.get("character_schema") else None,
        "status": activity.get("status") or statuses.get(record.id) or "idle",
        "activity": activity or None,
    }


def _session_rows(gateway) -> list[dict[str, Any]]:
    try:
        return gateway.store.list_sessions()
    except Exception:  # noqa: BLE001
        return []


def _rooms(gateway) -> list[dict[str, Any]]:
    out = []
    for row in _session_rows(gateway):
        meta = row.get("metadata") or {}
        if meta.get("room") is True:
            out.append({"session_id": row["session_id"], "title": row.get("title"), "members": meta.get("room_members") or [],
                        "updated_at": row.get("updated_at"), "probe": bool(meta.get("probe")), "status": row.get("status")})
    return sorted(out, key=lambda r: r.get("updated_at") or 0, reverse=True)


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
        ids = {m.id for m in members}
        handoffs = [h for h in gateway.store.list_handoffs(limit=60)
                    if h.get("to_agent_id") in ids or h.get("from_agent_id") in ids][:20]
        return web.json_response({
            "agents": [agent_card(m, live=gateway._team_live, statuses=statuses) for m in members],
            "rooms": _rooms(gateway),
            "handoffs": [{k: h.get(k) for k in ("id", "from_agent_id", "to_agent_id", "status", "task", "session_id",
                                                "created_at", "updated_at")} for h in handoffs],
            "limits": {"room_max_turns": ROOM_MAX_TURNS, "room_max_depth": ROOM_MAX_DEPTH,
                       "room_max_per_reply": ROOM_MAX_PER_REPLY},
        })

    async def avatar(request: web.Request) -> web.StreamResponse:
        rec = gateway._registry().get_agent(request.match_info["id"])
        path = avatar_path(rec) if rec is not None else None
        if path is None:
            return web.json_response({"error": "no avatar"}, status=404)
        return web.FileResponse(path, headers={"Content-Type": mimetypes.guess_type(path.name)[0] or "application/octet-stream",
                                               "Cache-Control": "max-age=300"})

    async def create_room(request: web.Request) -> web.Response:
        body = await request.json() if request.can_read_body else {}
        if not isinstance(body, dict):
            return web.json_response({"error": "body must be an object"}, status=400)
        members = [str(m) for m in (body.get("members") or []) if isinstance(m, str)]
        if not 2 <= len(members) <= 8:
            return web.json_response({"error": "a room needs 2 to 8 members"}, status=400)
        missing = [m for m in members if registry_member(m) is None]
        if missing:
            return web.json_response({"error": f"unknown or disabled agents: {', '.join(missing)}"}, status=404)
        sid = f"room-{uuid.uuid4().hex[:16]}"
        title = str(body.get("title") or "Team room").strip()[:120] or "Team room"
        meta = {"room": True, "room_members": members, "agent_id": members[0], "route_checked": True,
                **({"probe": True} if body.get("probe") else {})}
        gateway.store.ensure_session(sid, title=title, profile="jaeger", metadata=meta)
        return web.json_response({"session_id": sid, "title": title, "members": members}, status=201)

    async def get_room(request: web.Request) -> web.Response:
        sid = request.match_info["id"]
        row = gateway.store.get_session(sid)
        if row is None or not (row.get("metadata") or {}).get("room"):
            return web.json_response({"error": "Room not found"}, status=404)
        page = gateway.store.list_messages(sid, limit=200)
        return web.json_response({"room": {"session_id": sid, "title": row.get("title"),
                                           "members": (row.get("metadata") or {}).get("room_members") or [],
                                           "probe": bool((row.get("metadata") or {}).get("probe"))},
                                  "messages": list(reversed(page["messages"]))})

    async def post_room_message(request: web.Request) -> web.Response:
        sid = request.match_info["id"]
        row = gateway.store.get_session(sid)
        if row is None or not (row.get("metadata") or {}).get("room"):
            return web.json_response({"error": "Room not found"}, status=404)
        body = await request.json() if request.can_read_body else {}
        text = str((body or {}).get("text") or "").strip()
        if not text:
            return web.json_response({"error": "text is required"}, status=400)
        if getattr(gateway, "_room_busy", None) is None:
            gateway._room_busy = set()
        if sid in gateway._room_busy:
            return web.json_response({"error": "This room is still answering the last message"}, status=409)
        run_id = f"room_{uuid.uuid4().hex[:16]}"
        gateway._room_busy.add(sid)
        task = asyncio.create_task(run_room(sid, text, run_id))
        gateway._running_tasks[run_id] = task
        return web.json_response({"request_id": run_id, "session_id": sid}, status=202)

    def _names(members: list[Any]) -> dict[str, str]:
        return {m.id: m.display_name for m in members}

    async def run_room(sid: str, text: str, run_id: str) -> None:
        from jaeger_ai.core.team.mentions import Peer, is_pass, mentioned_peers, room_transcript, room_turn_message
        bus = gateway.event_bus
        started = time.time()
        turns = 0
        status = "succeeded"
        try:
            row = gateway.store.get_session(sid) or {}
            meta = row.get("metadata") or {}
            members = [m for m in (registry_member(a) for a in meta.get("room_members") or []) if m is not None]
            roster = [Peer(m.id, m.display_name) for m in members]
            by_id = {m.id: m for m in members}
            gateway.store.append_message(sid, "user", text, kind="room_message", links={"room_run_id": run_id})
            bus.publish(sid, "room.started", {"request_id": run_id, "session_id": sid, "title": row.get("title"),
                                              "members": [m.id for m in members], "text": text[:500]})
            addressed = mentioned_peers(text, roster) or roster
            queue: list[tuple[Any, int, str | None, str | None]] = [(by_id[p.id], 0, None, None) for p in addressed]
            while queue:
                member, depth, from_id, from_span = queue.pop(0)
                if turns >= ROOM_MAX_TURNS:
                    bus.publish(sid, "policy.decision", {"request_id": run_id, "decision": "deny", "tool": "@mention",
                                                         "policy": "room turn cap",
                                                         "reason": f"{member.display_name} not run: {ROOM_MAX_TURNS} turns already"})
                    continue
                turns += 1
                turn_id = f"rt_{uuid.uuid4().hex[:12]}"
                await member_turn(sid, run_id, turn_id, member, depth, from_id, from_span, members, roster, by_id,
                                  queue, room_title=str(row.get("title") or "Team room"))
        except Exception as exc:  # noqa: BLE001 — a room failure is reported, never kills the Gateway
            status = "failed"
            logger.exception("room %s failed", sid)
            bus.publish(sid, "turn.failed", {"request_id": run_id, "error": f"{type(exc).__name__}: {exc}"})
        finally:
            bus.publish(sid, "room.finished", {"request_id": run_id, "session_id": sid, "status": status, "turns": turns,
                                               "elapsed_s": round(time.time() - started, 3)})
            getattr(gateway, "_room_busy", set()).discard(sid)
            gateway._running_tasks.pop(run_id, None)

    async def member_turn(sid, run_id, turn_id, member, depth, from_id, from_span, members, roster, by_id, queue,
                          *, room_title: str) -> None:
        from jaeger_ai.core.team.mentions import is_pass, mentioned_peers, room_transcript, room_turn_message
        bus = gateway.event_bus
        names = _names(members)
        common = {"request_id": run_id, "turn_id": turn_id, "agent_id": member.id, "agent_name": member.display_name,
                  "avatar_seed": _meta(member).get("avatar_seed") or member.id, "depth": depth,
                  "from_agent_id": from_id, "parent_turn_id": from_span}
        bus.publish(sid, "room.turn", {**common, "status": "running"})
        gateway._team_live[member.id] = {"status": "working", "room": sid, "turn_id": turn_id, "since": time.time()}
        rows = list(reversed(gateway.store.list_messages(sid, limit=80)["messages"]))
        others = ", ".join(n for i, n in names.items() if i != member.id)
        asked_by = (f"{names.get(from_id, from_id)} handed the room to you with @{member.display_name}."
                    if from_id else "The person wrote to the room.")
        ask = (f"[Team room: {room_title}] You are {member.display_name}; the other members are {others}. {asked_by}\n"
               f"Reply to the room in a few short lines from your own role. If you have nothing useful to add, reply "
               f"exactly (pass). To hand part of the work to a teammate, name them as @Name in your reply.\n\n"
               f"Latest message:\n{rows[-1]['content'] if rows else ''}")
        prompt = room_turn_message(ask, room_transcript(rows[:-1], names))
        child = f"specialist:{member.id}:{sid}"  # one persistent thread per member per room (OpenBot group_bot_threads)
        mirror.bind(child, sid, run_id, turn_id)
        started = time.time()
        try:
            reply, backend = await gateway._specialist_chat(child, prompt, request_id=turn_id, agent_id=member.id,
                                                            parent_session_id=sid)
            try:
                gateway.store.update_metadata(child, {"room_id": sid, **({"probe": True} if (gateway.store.get_session(sid) or {}).get("metadata", {}).get("probe") else {})})
            except Exception:  # noqa: BLE001
                pass
        except Exception as exc:  # noqa: BLE001
            bus.publish(sid, "room.turn", {**common, "status": "failed", "error": f"{type(exc).__name__}: {exc}"[:400],
                                           "elapsed_s": round(time.time() - started, 3)})
            gateway._team_live.pop(member.id, None)
            return
        finally:
            mirror.unbind(child)
        gateway._team_live.pop(member.id, None)
        if is_pass(reply):
            bus.publish(sid, "room.turn", {**common, "status": "passed", "elapsed_s": round(time.time() - started, 3)})
            return
        mid = gateway.store.append_message(sid, "assistant", reply, kind="room_reply", sender_agent_id=member.id,
                                           links={"room_run_id": run_id, "turn_id": turn_id, "child_session_id": child})
        bus.publish(sid, "agent.message", {**common, "text": reply[:4000], "message_id": mid, "backend": backend})
        bus.publish(sid, "room.turn", {**common, "status": "succeeded", "elapsed_s": round(time.time() - started, 3),
                                       "summary": reply[:200]})
        peers = mentioned_peers(reply, roster, member.id)
        for index, peer in enumerate(peers):
            reason = None
            if depth + 1 > ROOM_MAX_DEPTH:
                reason = f"hand-off depth cap {ROOM_MAX_DEPTH}"
            elif index >= ROOM_MAX_PER_REPLY:
                reason = f"{ROOM_MAX_PER_REPLY} peers per reply"
            if reason:
                bus.publish(sid, "policy.decision", {"request_id": run_id, "decision": "deny", "tool": "@mention",
                                                     "policy": "room hand-off cap",
                                                     "reason": f"{member.display_name} → {peer.name} refused: {reason}"})
                continue
            bus.publish(sid, "policy.decision", {"request_id": run_id, "decision": "allow", "tool": "@mention",
                                                 "policy": "room hand-off", "reason": f"{member.display_name} → {peer.name}"})
            queue.append((by_id[peer.id], depth + 1, member.id, turn_id))

    app = gateway.app
    app.router.add_get("/v1/team", team)
    app.router.add_get("/v1/team/agents/{id}/avatar", avatar)
    app.router.add_post("/v1/team/rooms", create_room)
    app.router.add_get("/v1/team/rooms/{id}", get_room)
    app.router.add_post("/v1/team/rooms/{id}/messages", post_room_message)
