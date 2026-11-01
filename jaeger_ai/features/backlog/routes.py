"""Gateway routes for the backlog (loopback only).

GET  /v1/backlog                  -> {tasks, counts}  (?status=&priority=&worker=&q=)
POST /v1/backlog                  -> create {title, detail?, source?, status?, priority?, worker?}
POST /v1/backlog/{id}             -> update any of title/detail/status/priority/worker
POST /v1/backlog/{id}/assign      -> {worker}: a real hub handoff (agent-message ``task``) to the worker
POST /v1/backlog/import           -> {path?}: seed from ~/Documents/Jaeger-Backlog.md (owner only)

Only an owner surface (WebUI, menu bar, CLI) may approve a ``needs_ok`` task or
import. Worker replies on the handoff thread (status/result) move the task's
status through :func:`on_message`. Every change publishes a ``backlog.updated``
activity row so the UI updates live.
"""
from __future__ import annotations

import asyncio
import ipaddress
import logging
import time
import uuid
from pathlib import Path

from aiohttp import web

from .store import BacklogError, BacklogStore, status_from_message, sweep

logger = logging.getLogger(__name__)
ROUTES = frozenset({("POST", "/v1/backlog"), ("POST", "/v1/backlog/{id}"), ("POST", "/v1/backlog/{id}/assign"),
                    ("POST", "/v1/backlog/import")})


def _is_owner(name: str) -> bool:
    from jaeger_ai.core.gateway.caller_auth import CALLERS
    spec = CALLERS.get(name)
    return bool(spec and str(getattr(spec, "actor", "")).startswith("owner:"))


def _publish(gateway, caller: str, task: dict, action: str, **extra) -> None:
    try:
        gateway.event_bus.publish("*", "backlog.updated", {
            "caller": {"caller_id": caller, "caller_kind": "owner" if _is_owner(caller) else "mcp"},
            "task_id": task["id"], "title": task["title"][:200], "action": action, "status": task["status"],
            "priority": task["priority"], "worker": task["worker"], "handoff_id": task.get("handoff_id"), **extra})
    except Exception:  # noqa: BLE001
        logger.warning("backlog activity failed", exc_info=True)


def assign(gateway, store: BacklogStore, caller: str, task_id: str, worker: str) -> dict:
    """Hand the task to ``worker`` through the hub inbox and link the handoff."""
    from jaeger_ai.core.gateway.caller_auth import CALLERS
    from jaeger_ai.features.agent_bridge.service import AgentMessages, BridgeError

    task = store.get(task_id)
    worker = str(worker or "").strip().lower()
    if worker not in CALLERS or worker in ("jaegerd", "webui", "menubar", "cli", "bridge", "ide"):
        raise BacklogError(f"unknown worker {worker!r}")
    sender = caller if caller in CALLERS and caller != worker else "jaegerd"
    stamp = uuid.uuid4().hex[:8]
    msg = {"id": f"{task_id}-{stamp}", "thread": f"backlog-{task_id}-{stamp}", "to": worker, "kind": "task",
           "title": f"[Backlog {task['priority']}] {task['title']}"[:256],
           "body": (f"Backlog task {task_id} ({task['priority']}).\n\n{task['title']}\n\n{task['detail']}\n\n"
                    "Reply on this thread: kind=status while working (status_line 'needs ok' if Matthew must "
                    "approve something), kind=result with what you changed (commits, files, tests) when done.")[:16000],
           "refs": [f"backlog:{task_id}"], "status_line": "backlog assign"}
    try:
        message = AgentMessages(gateway.store).send(sender, msg)
    except BridgeError as exc:
        raise BacklogError(f"handoff failed: {exc}", getattr(exc, "status", 400)) from None
    task = store.update(task_id, worker=worker, status="in_progress", handoff_id=message["id"],
                        handoff_thread=message["thread"], last_note=f"assigned to {worker}")
    try:
        gateway.event_bus.publish("*", "handoff.sent", {
            "caller": {"caller_id": sender, "caller_kind": "owner" if _is_owner(sender) else "mcp"},
            "recipient": worker, "handoff_id": message["id"], "message_id": message["id"], "thread": message["thread"],
            "title": message["title"][:200], "status": "sent", "refs": message.get("refs", []),
            "at": message.get("created_at")})
    except Exception:  # noqa: BLE001
        logger.warning("backlog handoff activity failed", exc_info=True)
    if worker == "muse":
        _notify_muse(task, message)
    _publish(gateway, caller, task, "assigned")
    return {"task": task, "handoff": {"id": message["id"], "thread": message["thread"], "from": sender, "to": worker}}


def _notify_muse(task: dict, message: dict) -> None:
    """Muse can't read the hub inbox; its file bridge's inbox.md is the only way in."""
    try:
        from jaeger_ai.features.agent_bridge import muse_file_bridge as mfb
        if mfb.FOLDER.is_dir():
            mfb.append_inbox(f"BACKLOG TASK {task['id']} ({task['priority']}): {task['title'][:120]}",
                             f"{task['detail'][:4000]}\n\nWhen done, append to outbox.md:\n"
                             f"## TASK backlog-{task['id']}\nto: grokbot\ntitle: RESULT {task['id']}\n<what you did>")
    except Exception:  # noqa: BLE001
        logger.warning("muse inbox notice failed", exc_info=True)


def on_message(gateway, caller: str, message: dict) -> dict | None:
    """A worker's reply on a backlog handoff thread moves the task. Never raises."""
    try:
        store = getattr(gateway, "backlog_store", None)
        if store is None or message.get("kind") not in ("status", "result", "answer", "question"):
            return None
        task = store.by_handoff(message.get("reply_to"), message.get("thread"))
        if not task or caller != task["worker"]:
            return None
        new = status_from_message(message["kind"], message.get("status_line", ""))
        if not new or task["status"] == "done":
            return None
        note = (message.get("status_line") or message.get("title") or message["kind"])[:500]
        task = store.update(task["id"], status=new, last_note=note)
        _publish(gateway, caller, task, f"handoff.{message['kind']}", note=note[:200])
        return task
    except Exception:  # noqa: BLE001
        logger.warning("backlog on_message failed", exc_info=True)
        return None


def register(gateway, store: BacklogStore | None = None):
    store = store or BacklogStore()
    gateway.backlog_store = store

    async def body_of(request):
        if not request.remote or not ipaddress.ip_address(request.remote).is_loopback:
            raise web.HTTPForbidden(text="Loopback required")
        if request.method == "GET":
            return {}
        if request.content_length and request.content_length > 65536:
            raise web.HTTPRequestEntityTooLarge(max_size=65536, actual_size=request.content_length)
        try:
            body = await request.json()
        except ValueError:
            body = None
        if not isinstance(body, dict):
            raise web.HTTPBadRequest(text="JSON object required")
        return body

    def guard(fn):
        async def handle(request):
            try:
                body = await body_of(request)
                return web.json_response(await fn(request, request["caller"].name, body))
            except BacklogError as exc:
                return web.json_response({"error": str(exc)}, status=exc.status)
        return handle

    @guard
    async def listing(request, caller, _body):
        q = request.query
        owner = getattr(gateway, "task_owner", None)
        if owner is not None:
            from .task_mirror import mirror_tasks
            try:
                tasks = [t.to_dict() for t in owner.store.list_tasks()]
                await asyncio.to_thread(mirror_tasks, store, tasks)
            except Exception:  # the Backlog still lists when the task store is unavailable
                pass
        tasks = await asyncio.to_thread(store.list, q.get("status", ""), q.get("priority", ""), q.get("worker", ""),
                                        q.get("q", ""), int(q.get("limit", "500") or 500))
        return {"tasks": tasks, "counts": store.counts(), "now": time.time()}

    @guard
    async def sweep_route(request, caller, _body):
        try:
            stale_after_s = float(request.query.get("stale_after_s", "86400"))
        except ValueError as exc:
            raise BacklogError("invalid stale_after_s") from exc
        return {"flagged": await asyncio.to_thread(sweep, store, time.time(), stale_after_s)}

    @guard
    async def create(request, caller, body):
        allowed = {"title", "detail", "source", "status", "priority", "worker"}
        if set(body) - allowed:
            raise BacklogError(f"unknown field(s): {', '.join(sorted(set(body) - allowed))}")
        body.setdefault("source", caller)
        task = store.add(**body)
        _publish(gateway, caller, task, "created")
        return {"task": task}

    @guard
    async def update(request, caller, body):
        task_id = request.match_info["id"]
        from .store import FIELDS
        if set(body) - set(FIELDS):
            raise BacklogError(f"unknown field(s): {', '.join(sorted(set(body) - set(FIELDS)))}")
        prior = store.get(task_id)
        if prior["status"] == "needs_ok" and "status" in body and body["status"] != "needs_ok" and not _is_owner(caller):
            raise BacklogError("only Matthew can approve a needs_ok task", 403)
        task = store.update(task_id, **body)
        action = "approved" if prior["status"] == "needs_ok" and task["status"] != "needs_ok" else "updated"
        _publish(gateway, caller, task, action, changed=sorted(body))
        return {"task": task}

    @guard
    async def assign_route(request, caller, body):
        return await asyncio.to_thread(assign, gateway, store, caller, request.match_info["id"], body.get("worker", ""))

    @guard
    async def import_route(request, caller, body):
        if not _is_owner(caller):
            raise BacklogError("import is owner only", 403)
        from .importer import DEFAULT_FILE, import_file
        path = Path(body.get("path") or DEFAULT_FILE).expanduser()
        if not path.resolve().is_relative_to((Path.home() / "Documents").resolve()):
            raise BacklogError("path must be under ~/Documents", 403)
        out = await asyncio.to_thread(import_file, store, path)
        if not out["ok"]:
            raise BacklogError(out["error"], 404)
        return out

    gateway.app.router.add_get("/v1/backlog", listing)
    gateway.app.router.add_get("/v1/backlog/sweep", sweep_route)
    gateway.app.router.add_post("/v1/backlog", create)
    gateway.app.router.add_post("/v1/backlog/import", import_route)
    gateway.app.router.add_post("/v1/backlog/{id}", update)
    gateway.app.router.add_post("/v1/backlog/{id}/assign", assign_route)
    return store
