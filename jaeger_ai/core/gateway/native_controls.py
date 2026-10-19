"""Native controls over the existing schedule store and Gateway task owner.

A control receipt records submission identity, not successful agent execution.
Unsettled writes are never replayed automatically after a lost response/crash.
"""
from __future__ import annotations

import json
from aiohttp import web


def register(gateway):
    async def schedules(request):
        from jaeger_ai.core.runtime import schedules as owner
        from jaeger_agent.memory import sqlite_store
        try:
            sqlite_store.connection()  # Fail visibly if the instance has not bound.
            jobs = owner.list_jobs()["schedules"]
            return web.json_response({"jobs": [
                {**j, "id": j["name"], "schedule_display": j["cron"],
                 "enabled": not j["paused"], "state": j["status"]} for j in jobs],
                "scheduler": "jaeger"})
        except RuntimeError as exc:
            return web.json_response({"error": str(exc)}, status=503)

    async def operation(request):
        row = gateway.store.control_operation(request.match_info["id"])
        return web.json_response(row or {"error": "Operation not found"}, status=200 if row else 404)

    async def history(request):
        name = request.query.get("job_id", "")
        tasks = [t.to_dict() for t in gateway.task_owner.store.list_tasks()
                 if t.provenance.get("schedule_id") == name]
        requests = [r for r in gateway.store.list_requests() if r["session_id"] == "cron:" + name]
        return web.json_response({"tasks": tasks, "requests": requests})

    async def mutate(request):
        from jaeger_ai.core.runtime import schedules as owner
        from jaeger_agent.memory import sqlite_store
        action = request.match_info["action"]
        if action not in {"create", "update", "pause", "resume", "delete", "run"}:
            raise web.HTTPNotFound()
        try:
            body = await request.json()
            if not isinstance(body, dict):
                raise ValueError("Body must be an object")
            oid = body.get("operation_id")
            if not isinstance(oid, str) or not oid.strip() or len(oid) > 128:
                raise ValueError("A stable operation_id is required")
            sqlite_store.connection()
            payload = {"action": action, "body": body}
            fresh = gateway.store.reserve_control_operation(oid, payload)
        except (ValueError, TypeError) as exc:
            return web.json_response({"error": str(exc)}, status=400)
        except RuntimeError as exc:
            return web.json_response({"error": str(exc)}, status=503)
        if not fresh:
            row = gateway.store.control_operation(oid)
            if row["receipt"] is not None:
                return web.json_response(row["receipt"], status=row["receipt"].get("http_status", 200))
            return web.json_response({**row, "error": "Previous action outcome is unknown. Inspect current state; do not resubmit."}, status=409)
        try:
            name = str(body.get("job_id") or body.get("name") or "").strip()
            if action == "create":
                if not name:
                    name = "native-" + oid
                if any(j["name"] == name for j in owner.list_jobs()["schedules"]):
                    raise ValueError("A schedule with this name already exists")
                result = owner.create_job(name=name, prompt=str(body.get("prompt") or ""), schedule=str(body.get("schedule") or ""))
            elif action == "update":
                result = owner.update_job(name, prompt=str(body.get("prompt") or ""), schedule=str(body.get("schedule") or ""))
            elif action == "run":
                if gateway._current_tier() == "chat":
                    raise ValueError("Scheduled execution is disabled in Chat mode")
                job = next((j for j in owner.list_jobs()["schedules"] if j["name"] == name), None)
                if job is None:
                    raise ValueError("Schedule not found")
                parent = gateway.store.ensure_session("cron:" + name, title=name, profile="jaeger")
                result = gateway.task_owner.submit(job["prompt"], context={"session_id": parent["session_id"], "source": "client", "request_id": oid}, key=oid)
                gateway.task_owner.store.update_task(result["task_id"], lambda task: task.provenance.update(schedule_id=name))
            else:
                result = {"pause": owner.pause_job, "resume": owner.resume_job, "delete": owner.cancel_job}[action](name)
                if not any(result.get(k) for k in ("paused", "resumed", "cancelled")):
                    raise ValueError("Schedule not found")
            receipt = {"ok": True, "operation_id": oid, "result": result, "http_status": 200}
        except ValueError as exc:
            receipt = {"ok": False, "operation_id": oid, "error": str(exc), "http_status": 400}
        except Exception:
            # The reservation remains durable and uncertain; never repeat a possibly applied write.
            return web.json_response({"operation_id": oid, "execution_unknown": True,
                                      "error": "Action outcome unknown. Refresh and inspect before continuing."}, status=503)
        gateway.store.finish_control_operation(oid, receipt)
        gateway.event_bus.publish("*", "schedule.changed", {"operation_id": oid, "action": action})
        return web.json_response(receipt, status=receipt["http_status"])

    gateway.app.router.add_get("/v1/schedules", schedules)
    gateway.app.router.add_get("/v1/schedules/history", history)
    gateway.app.router.add_post("/v1/schedules/{action}", mutate)
    gateway.app.router.add_get("/v1/control-operations/{id}", operation)
