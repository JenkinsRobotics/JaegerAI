"""Loopback REST adapters. Execution always enters normal Gateway admission."""

from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import json
import os
from pathlib import Path

from aiohttp import web

from jaeger_ai.core.agent_registry.specialists import LEAD_AGENT_ID, REA_READ_ONLY_TOOLS
from jaeger_ai.core.redaction import redact_value

from .outcomes import project_goal
from .service import AgentMessages, BridgeError, enabled, key
from .tool_scope import supported_tools


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
        from .responses import deliver_responses
        deliver_responses(gateway, caller=caller)
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
            "source_message_id",
        }:
            raise BridgeError("Invalid goal fields")
        goal_id, thread = key(body.get("id")), key(body.get("thread"))
        source = key(body["source_message_id"]) if "source_message_id" in body else None
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
        # Use existing native tools through ordinary authority/approval dispatch.
        # Tools without a bounded resource contract remain unsupported.
        turn = {
            "text": redact_value(goal),
            "request_id": f"agent-{caller}-{goal_id}",
            "workspace": folder,
            "allowed_tools": supported_tools(),
        }
        digest = hashlib.sha256(
            json.dumps({**turn, "text": goal, **({"source_message_id": source} if source else {})}, sort_keys=True).encode()
        ).hexdigest()
        session = (
            request["caller"].session_prefix or f"agent:{caller}:"
        ) + f"bridge-{thread}"
        async with goal_lock:
            with gateway.store._get_conn() as conn:
                service.access(conn, caller, thread)
                if source:
                    message = conn.execute(
                        "SELECT payload FROM agent_messages WHERE sender=? AND id=? AND thread=? AND recipient='jaegerd'",
                        (caller, source, thread),
                    ).fetchone()
                    if not message or json.loads(message["payload"])["kind"] not in {"task", "question"}:
                        raise BridgeError("Only an owned task/question to jaegerd can admit a reply goal", 409)
                    binding = conn.execute("SELECT id FROM agent_goals WHERE caller=? AND source_message_id=?", (caller, source)).fetchone()
                    if binding and binding["id"] != goal_id:
                        raise BridgeError("Message already bound to a goal", 409)
                prior = conn.execute(
                    "SELECT * FROM agent_goals WHERE caller=? AND id=?",
                    (caller, goal_id),
                ).fetchone()
                if prior:
                    # A catalog upgrade must not widen or conflict with an
                    # already admitted retry. Its original grant stays frozen.
                    receipt = gateway.store.get_request(prior["request_id"])
                    if receipt is not None:
                        turn["allowed_tools"] = (receipt.get("execution") or {}).get(
                            "allowed_tools"
                        )
                        digest = hashlib.sha256(
                            json.dumps({**turn, "text": goal, **({"source_message_id": source} if source else {})}, sort_keys=True).encode()
                        ).hexdigest()
                if prior and (prior["digest"] != digest or prior["thread"] != thread):
                    raise BridgeError("Goal id reused with different content", 409)
                conn.execute(
                    "INSERT OR IGNORE INTO agent_goals(caller,id,thread,session,request_id,digest,source_message_id) VALUES(?,?,?,?,?,?,?)",
                    (caller, goal_id, thread, session, turn["request_id"], digest, source),
                )
            # Bridge delegation requests the lead's tools, not keyword-based
            # triage into a narrower specialist catalog.
            gateway.store.ensure_session(
                session,
                title="Agent goal",
                workspace=folder,
                metadata={
                    "agent_id": LEAD_AGENT_ID,
                    "agent_pinned": True,
                    "route_checked": True,
                },
            )
            response = await gateway.handle_send_turn(
                TurnRequest(request, session, turn)
            )
        if response.status != 200:
            return response
        return web.json_response(
            project_goal(
                goal_id,
                thread,
                gateway.store.get_request(turn["request_id"])
                or json.loads(response.body),
                gateway=gateway,
            )
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
        from .responses import deliver_responses
        deliver_responses(gateway, request_id=row["request_id"])
        receipt = gateway.store.get_request(row["request_id"])
        return web.json_response(
            project_goal(row["id"], row["thread"], receipt, gateway=gateway)
        )

    @wrap("cancel_goal")
    async def cancel(request, caller):
        row = goal_row(caller, request.match_info["goal_id"])
        response = await gateway.handle_cancel_turn(
            TurnRequest(request, row["session"], {"request_id": row["request_id"]})
        )
        if response.status != 200:
            return response
        from .delegation import cancel_handoffs

        await cancel_handoffs(
            gateway,
            {
                "caller": caller,
                "session": row["session"],
                "request_id": row["request_id"],
            },
        )
        canonical = json.loads(response.body)
        return web.json_response(
            {
                **project_goal(row["id"], row["thread"], canonical, gateway=gateway),
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
