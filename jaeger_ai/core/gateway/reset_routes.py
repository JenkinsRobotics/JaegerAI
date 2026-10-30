"""App-reset route (Jenkins Robotics, 2026-10-30, original).

``POST /v1/app-reset`` — "Reset app to default" for the Settings page.

Deletes every gateway conversation (sessions + messages + queue + attachments;
SQLite cascades the children) with an archive taken first, so the operator's
history is recoverable from disk afterwards. Optionally (``wipe_memory: true``)
also clears the instance memory directory contents — facts, notes, events —
which is opt-in because memory is the entity's continuity, not chat debris.

Never touched (and never deletable through this route):
  caller tokens, credentials/, identity.yaml, config.yaml, manifest.json,
  mcp.json, agents/registry.json, the database schema/lease tables, skills and
  workspace files the agent authored.

Implemented through GatewaySessionStore's own APIs (list + delete per session
plus one backup), never raw SQL from the route: the daemon's connection owns
the WAL, so a store-API loop is safe while serving.
"""
from __future__ import annotations

import asyncio
import logging
import shutil
import time
from typing import Any

from aiohttp import web

logger = logging.getLogger(__name__)


def register(gateway: Any) -> None:
    """Register POST /v1/app-reset on the running gateway (register(gateway) convention)."""

    async def reset(request: web.Request) -> web.Response:
        store = gateway.store

        body: dict[str, Any] = {}
        if request.can_read_body:
            try:
                body = await request.json()
            except Exception:
                return web.json_response({"error": "Body must be JSON"}, status=400)
        if not isinstance(body, dict):
            return web.json_response({"error": "Body must be a JSON object"}, status=400)
        wipe_memory = body.get("wipe_memory") is True

        # 1) Archive first — the operator's history is recoverable either way.
        db_path = store.path
        archive_path: str | None = None
        try:
            if db_path and db_path.exists():
                stamp = time.strftime("%Y%m%d-%H%M%S")
                dest = db_path.parent / "archive" / f"app-reset-{stamp}.sqlite3"
                store.backup(dest)
                archive_path = str(dest)
        except Exception as exc:  # noqa: BLE001 — refuse to delete without an archive
            logger.warning("app-reset: archive failed: %s", type(exc).__name__)
            return web.json_response(
                {"error": "Could not archive history before deleting; nothing was deleted."},
                status=503,
            )

        # 2) Durable tasks: paused/running ones are cancelled first through the
        #    owner (durable receipts, approvals denied, in-flight turns marked),
        #    then every row is deleted from the tasks table.
        tasks_cancelled = 0
        tasks_deleted = 0
        task_store = None
        owner = getattr(gateway, "task_owner", None)
        if owner is not None and getattr(owner, "store", None) is not None:
            task_store = owner.store
            from jaeger_ai.core.tasks.models import TaskState
            for task in task_store.list_tasks():
                state = str(task.state.value if hasattr(task.state, "value") else task.state)
                if state in ("paused", "running", "queued", "needs_owner"):
                    try:
                        if asyncio.iscoroutinefunction(owner.cancel):
                            await owner.cancel(task.task_id)
                        else:
                            owner.cancel(task.task_id)
                        tasks_cancelled += 1
                    except Exception:  # noqa: BLE001 — keep clearing the rest
                        pass
        if task_store is not None:
            try:
                with task_store._get_conn() as conn, conn:
                    tasks_deleted = conn.execute("DELETE FROM durable_tasks").rowcount
            except Exception:  # noqa: BLE001
                pass

        # 3b) Orphaned pending approvals: after every session is gone no client
        # can resolve these through the normal flow, so the reset denies them.
        approvals_denied = 0
        try:
            for approval in store.list_pending_approvals():
                try:
                    store.resolve_approval(approval["approval_id"], approved=False, decision="deny")
                    approvals_denied += 1
                except Exception:  # noqa: BLE001
                    pass
        except Exception:  # noqa: BLE001
            pass

        # 3) Delete every conversation through the store (cascades children,
        #    publishes session.deleted per id so live clients clear).
        deleted = 0
        failed: list[str] = []
        ids = [row["session_id"] for row in store.list_sessions()]
        for session_id in ids:
            try:
                if store.delete_session(session_id):
                    deleted += 1
                else:
                    failed.append(session_id)
            except Exception:  # noqa: BLE001 — collect and keep going
                failed.append(session_id)

        # 4) Optional, explicit memory wipe (instance memory dir contents only).
        memory_cleared: list[str] = []
        memory_failed: list[str] = []
        if wipe_memory:
            from jaeger_ai.core.instance.instance import InstanceLayout, resolve_instance_dir

            layout = InstanceLayout(resolve_instance_dir())
            memory_dir = layout.memory_dir
            if memory_dir.is_dir():
                for child in sorted(memory_dir.iterdir()):
                    try:
                        if child.is_dir() and not child.is_symlink():
                            shutil.rmtree(child)
                        else:
                            child.unlink()
                        memory_cleared.append(child.name)
                    except Exception:  # noqa: BLE001
                        memory_failed.append(child.name)

        return web.json_response(
            {
                "reset": True,
                "deleted_sessions": deleted,
                "failed_sessions": failed,
                "tasks_cancelled": tasks_cancelled,
                "tasks_deleted": tasks_deleted,
                "approvals_denied": approvals_denied,
                "archive": archive_path,
                "memory_cleared": memory_cleared,
                "memory_failed": memory_failed,
            },
            status=200,
        )

    gateway.app.router.add_post("/v1/app-reset", reset)
    logger.info("App reset route registered: POST /v1/app-reset")