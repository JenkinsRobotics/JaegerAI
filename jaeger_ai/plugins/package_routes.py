"""Owner-scoped package data review and explicit offline wheel transactions."""

from __future__ import annotations
import asyncio
from pathlib import Path
from aiohttp import web
from .packages import PackageOwner, digest


def owner(gateway):
    from jaeger_ai.core.gateway.server import _control_plane_block

    return PackageOwner(gateway.store, guard=_control_plane_block)


def register(gateway):
    def uploaded(body):
        if not isinstance(body.get("session_id"), str) or not (
            isinstance(body.get("attachment_id"), str)
            or isinstance(body.get("upload_key"), str)
        ):
            raise ValueError("Staged attachment and conversation identity required")
        rows = [
            r
            for r in gateway.store.list_attachments(body["session_id"])
            if r["attachment_id"] == body.get("attachment_id")
            or body.get("upload_key")
            and r.get("metadata", {}).get("idempotency_key") == body["upload_key"]
        ]
        if len(rows) != 1:
            raise ValueError(
                "Original upload receipt not found; no package operation performed"
            )
        row = rows[0]
        if not row or row["provenance"] != "upload_staged":
            raise ValueError("Only an explicitly uploaded wheel may be reviewed")
        path = Path(row["safe_path"])
        if (
            not gateway._staged_upload_dir(body["session_id"])
            .resolve()
            .is_relative_to(gateway.store.path.parent.resolve())
            or path.is_symlink()
            or not path.resolve().is_relative_to(
                gateway._staged_upload_dir(body["session_id"]).resolve()
            )
            or path.name != row["original_filename"]
            or not path.is_file()
        ):
            raise ValueError("Staged wheel ownership unavailable")
        if (
            path.stat().st_size != row["size_bytes"]
            or digest(path.read_bytes()) != row["sha256"]
        ):
            raise ValueError("Staged wheel content changed")
        return row, path

    async def listing(request):
        manager = owner(gateway)
        try:
            return web.json_response(
                {
                    "environment": manager.environment,
                    **manager.history(request.query.get("before")),
                    "scope": "current_python_environment",
                    "activation_performed": False,
                    "supported": "offline_portable_pure_wheels_existing_dependencies_only",
                }
            )
        except ValueError as exc:
            return web.json_response({"error": str(exc)}, status=400)

    async def preview(request):
        try:
            body = await request.json()
            manager = owner(gateway)
            if not isinstance(body, dict):
                raise ValueError("Package review body required")
            if (
                set(body)
                in (
                    {"action", "session_id", "attachment_id"},
                    {"action", "session_id", "upload_key"},
                )
                and body["action"] == "install"
            ):
                row, path = await asyncio.to_thread(uploaded, body)
                result = await asyncio.to_thread(manager.preview, path)
                result["attachment_id"] = row["attachment_id"]
            elif set(body) == {"action", "package"} and body["action"] == "remove":
                result = await asyncio.to_thread(
                    manager.removal_preview, body["package"]
                )
            elif (
                set(body) == {"action", "restore_from"} and body["action"] == "restore"
            ):
                _, _, result = await asyncio.to_thread(
                    manager.restore_preview, body["restore_from"]
                )
            else:
                raise ValueError("Invalid package review fields")
            return web.json_response(result)
        except (ValueError, TypeError) as exc:
            return web.json_response({"error": str(exc)}, status=400)
        except Exception:
            return web.json_response(
                {
                    "error": "Package review unavailable; no package or activation changed"
                },
                status=503,
            )

    async def inspect(request):
        try:
            result = await asyncio.to_thread(
                owner(gateway).inspect, request.match_info["id"]
            )
            if result and result.get("execution_unknown"):
                return web.json_response({"receipt": None, "pending": result})
            return web.json_response({"receipt": result})
        except Exception:
            return web.json_response(
                {
                    "receipt": None,
                    "error": "Package outcome remains unresolved; no command replay",
                },
                status=503,
            )

    async def mutate(request):
        manager = owner(gateway)
        try:
            body = await request.json()
            action = body.get("action") if isinstance(body, dict) else None
            fields = {
                "operation_id",
                "action",
                "expected_fingerprint",
                "expected_policy_revision",
            } | (
                {"session_id", "attachment_id", "sha256"}
                if action == "install"
                else {"package"}
                if action == "remove"
                else {"restore_from"}
                if action == "restore"
                else set()
            )
            if action not in {"install", "remove", "restore"} or set(body) != fields:
                raise ValueError("Exact package command fields required")
            oid = body["operation_id"]
            manager.directory(oid)
            if (
                not isinstance(body["expected_fingerprint"], str)
                or type(body["expected_policy_revision"]) is not int
            ):
                raise ValueError("Reviewed package and startup revisions required")
            command = {
                "action": "plugin.package",
                "body": body,
                "environment": manager.environment,
                "actor": request["caller_actor"],
            }
            try:
                reserved = gateway.store.reserve_scoped_control_operation(
                    oid, command, "plugin-packages:" + manager.environment
                )
            except ValueError:
                if action != "restore":
                    raise
                reserved = await asyncio.to_thread(
                    manager.reserve_restore, oid, command, body["restore_from"]
                )
            if not reserved:
                result = await asyncio.to_thread(manager.inspect, oid)
                return web.json_response(
                    result
                    or {
                        "operation_id": oid,
                        "execution_unknown": True,
                        "error": "Original command unresolved; no replay",
                    },
                    status=result.get("http_status", 200) if result else 409,
                )
        except (ValueError, TypeError) as exc:
            return web.json_response({"error": str(exc)}, status=400)
        try:
            args = {
                "expected_fingerprint": body["expected_fingerprint"],
                "expected_policy_revision": body["expected_policy_revision"],
            }
            if action == "install":
                _, path = await asyncio.to_thread(uploaded, body)
                result = await asyncio.to_thread(
                    manager.change,
                    oid,
                    action=action,
                    path=path,
                    expected_sha=body["sha256"],
                    **args,
                )
            elif action == "remove":
                result = await asyncio.to_thread(
                    manager.change, oid, action=action, package=body["package"], **args
                )
            else:
                result = await asyncio.to_thread(
                    manager.restore, oid, body["restore_from"], **args
                )
        except ValueError as exc:
            if manager.progress(oid):
                return web.json_response(
                    {
                        "operation_id": oid,
                        "execution_unknown": True,
                        "error": "Package progress exists; inspect original operation without replay",
                    },
                    status=409,
                )
            result = {
                "ok": False,
                "operation_id": oid,
                "http_status": 409,
                "error": str(exc),
            }
            gateway.store.finish_control_operation(oid, result)
        except Exception:
            if manager.progress(oid):
                return web.json_response(
                    {
                        "operation_id": oid,
                        "execution_unknown": True,
                        "error": "Package outcome unknown; inspect original operation without replay",
                    },
                    status=503,
                )
            result = {
                "ok": False,
                "operation_id": oid,
                "http_status": 409,
                "error": "Package preflight failed before environment changes; staged files retained",
            }
            gateway.store.finish_control_operation(oid, result)
        gateway.event_bus.publish(
            "*",
            "plugins.changed",
            {"package_operation_id": oid, "confirmed": result.get("ok", False)},
        )
        return web.json_response(result, status=result.get("http_status", 409))

    gateway.app.router.add_get("/v1/runtime/plugins/packages", listing)
    gateway.app.router.add_post("/v1/runtime/plugins/packages/preview", preview)
    gateway.app.router.add_post("/v1/runtime/plugins/packages/change", mutate)
    gateway.app.router.add_get("/v1/runtime/plugins/package-operations/{id}", inspect)
