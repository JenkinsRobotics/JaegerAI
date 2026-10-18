"""Loopback REST adapters. Execution always enters normal Gateway admission."""

from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import json
import os
from pathlib import Path

from aiohttp import web

from jaeger_ai.core.agent_registry.specialists import REA_READ_ONLY_TOOLS
from jaeger_ai.core.redaction import redact_value

from .outcomes import project_goal
from .service import AgentMessages, BridgeError, enabled, key


class TurnRequest(dict):
    """Carry the already authenticated request into the canonical turn handler."""

    can_read_body = True

    def __init__(self, original, session_id, body):
        super().__init__(original)
        self.match_info = {"id": session_id}
        self.body = body

    async def json(self):
        return self.body


def workspace(caller, raw):
    if (
        not isinstance(raw, str)
        or not Path(raw).is_absolute()
        or not Path(raw).is_dir()
    ):
        raise BridgeError("Existing absolute workspace required")
    target = Path(raw).resolve()
    try:
        grants = json.loads(os.environ.get("JAEGER_AGENT_WORKSPACES", "{}"))
        roots = grants.get(caller, [])
        if not isinstance(roots, list) or any(
            not isinstance(root, str) for root in roots
        ):
            raise ValueError
        allowed = any(
            Path(root).is_absolute()
            and Path(root).resolve() not in (Path("/"), Path.home())
            and target.is_relative_to(Path(root).resolve())
            for root in roots
        )
    except (ValueError, TypeError, AttributeError):
        allowed = False
    if not allowed or target in (Path("/"), Path.home()):
        raise BridgeError("Workspace not authorized for caller", 403)
    return str(target)


async def read_json(request):
    data = bytearray()
    async for chunk in request.content.iter_chunked(8192):
        data.extend(chunk)
        if len(data) > 32768:
            raise BridgeError("Payload too large", 413)
    return json.loads(data)


def register(gateway):
    service = AgentMessages(gateway.store)
    goal_lock = asyncio.Lock()

    def wrap(action):
        def decorate(fn):
            async def handle(request):
                caller = request["caller"].name
                try:
                    enabled()
                    if (
                        not request.remote
                        or not ipaddress.ip_address(request.remote).is_loopback
                    ):
                        raise BridgeError("Loopback required", 403)
                    service.gate(caller, action)
                    if request.content_length and request.content_length > 32768:
                        raise BridgeError("Payload too large", 413)
                    response = await fn(request, caller)
                    if response.status >= 400:
                        service.audit_failure(caller, action, response.status)
                    return response
                except BridgeError as exc:
                    service.audit_failure(caller, action, exc.status)
                    return web.json_response({"error": str(exc)}, status=exc.status)
                except (ValueError, TypeError, KeyError):
                    service.audit_failure(caller, action, 400)
                    return web.json_response(
                        {"error": "Invalid agent bridge request"}, status=400
                    )

            return handle

        return decorate

    @wrap("send_message")
    async def send(request, caller):
        return web.json_response(service.send(caller, await read_json(request)))

    @wrap("list_messages")
    async def listing(request, caller):
        return web.json_response(
            service.list(
                caller,
                thread=request.match_info.get("thread"),
                after=int(request.query.get("after", "0")),
                limit=int(request.query.get("limit", "50")),
            )
        )

    @wrap("start_goal")
    async def start(request, caller):
        body = await read_json(request)
        if not isinstance(body, dict) or set(body) - {
            "id",
            "thread",
            "goal",
            "workspace_folder",
            "rea_tools",
        }:
            raise BridgeError("Invalid goal fields")
        goal_id, thread = key(body.get("id")), key(body.get("thread"))
        goal = body.get("goal")
        if not isinstance(goal, str) or not goal.strip() or len(goal.encode()) > 16384:
            raise BridgeError("Goal must contain 1..16384 bytes")
        folder = workspace(caller, body.get("workspace_folder"))
        tools = body.get("rea_tools", [])
        if (
            not isinstance(tools, list)
            or len(tools) > 50
            or any(
                not isinstance(tool, str) or tool not in REA_READ_ONLY_TOOLS
                for tool in tools
            )
        ):
            raise BridgeError(
                "Only the explicit REA read-only allowlist may be granted", 403
            )
        if tools:
            # The existing MCP permission check does not confine REA's opaque
            # handles to a workspace/thread. Do not turn an allowlist into a
            # new execution authority while that acceptance item is incomplete.
            raise BridgeError(
                "REA pass-through incomplete: caller/thread/workspace handle confinement unavailable",
                501,
            )
        # Ordinary goals keep the normal authority path and an empty tool grant.
        turn = {
            "text": redact_value(goal),
            "request_id": f"agent-{caller}-{goal_id}",
            "workspace": folder,
            "allowed_tools": [f"mcp__rea__{tool}" for tool in tools],
        }
        digest = hashlib.sha256(
            json.dumps({**turn, "text": goal}, sort_keys=True).encode()
        ).hexdigest()
        session = (
            request["caller"].session_prefix or f"agent:{caller}:"
        ) + f"bridge-{thread}"
        async with goal_lock:
            with gateway.store._get_conn() as conn:
                service.access(conn, caller, thread)
                prior = conn.execute(
                    "SELECT * FROM agent_goals WHERE caller=? AND id=?",
                    (caller, goal_id),
                ).fetchone()
                if prior and (prior["digest"] != digest or prior["thread"] != thread):
                    raise BridgeError("Goal id reused with different content", 409)
                conn.execute(
                    "INSERT OR IGNORE INTO agent_goals VALUES(?,?,?,?,?,?)",
                    (caller, goal_id, thread, session, turn["request_id"], digest),
                )
            gateway.store.ensure_session(session, title="Agent goal", workspace=folder)
            response = await gateway.handle_send_turn(
                TurnRequest(request, session, turn)
            )
        if response.status != 200:
            return response
        return web.json_response(
            project_goal(goal_id, thread, json.loads(response.body))
        )

    def goal_row(caller, goal_id):
        with gateway.store._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM agent_goals WHERE caller=? AND id=?",
                (caller, key(goal_id)),
            ).fetchone()
            if row is None:
                raise BridgeError("Goal unavailable", 404)
            service.access(conn, caller, row["thread"])
            return dict(row)

    @wrap("goal_status")
    async def status(request, caller):
        row = goal_row(caller, request.match_info["goal_id"])
        receipt = gateway.store.get_request(row["request_id"])
        return web.json_response(project_goal(row["id"], row["thread"], receipt))

    @wrap("cancel_goal")
    async def cancel(request, caller):
        row = goal_row(caller, request.match_info["goal_id"])
        response = await gateway.handle_cancel_turn(
            TurnRequest(request, row["session"], {"request_id": row["request_id"]})
        )
        if response.status != 200:
            return response
        canonical = json.loads(response.body)
        return web.json_response(
            {
                **project_goal(row["id"], row["thread"], canonical),
                **{
                    name: canonical[name]
                    for name in (
                        "cancel_requested",
                        "already_terminal",
                        "cancellation_confirmed",
                    )
                    if name in canonical
                },
            }
        )

    gateway.app.router.add_post("/v1/agent-messages", send)
    gateway.app.router.add_get("/v1/agent-messages", listing)
    gateway.app.router.add_get("/v1/agent-threads/{thread}", listing)
    gateway.app.router.add_post("/v1/agent-goals", start)
    gateway.app.router.add_get("/v1/agent-goals/{goal_id}", status)
    gateway.app.router.add_post("/v1/agent-goals/{goal_id}/cancel", cancel)
