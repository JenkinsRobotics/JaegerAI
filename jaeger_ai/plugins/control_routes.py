"""Installed extension metadata and managed-hook controls; never load plugin code."""

from __future__ import annotations
import asyncio
from aiohttp import web
from . import registry, startup


def register(gateway):
    from .package_routes import register as register_packages

    register_packages(gateway)

    async def listing(request):
        return web.json_response(
            await asyncio.to_thread(
                lambda: registry.catalog(policy=startup.read(gateway.store))
            )
        )

    async def mutate(request):
        identity = request.match_info["id"]
        action = request.match_info["action"]
        if action not in {"pause_hooks", "resume_hooks"}:
            raise web.HTTPNotFound()
        try:
            body = await request.json()
            if not isinstance(body, dict) or set(body) != {
                "operation_id",
                "expected_state",
            }:
                raise ValueError("Stable operation and expected state required")
            oid = body["operation_id"]
            if (
                not isinstance(oid, str)
                or not oid.strip()
                or len(oid) > 128
                or not isinstance(body["expected_state"], str)
            ):
                raise ValueError("Invalid control fields")
            if not gateway.store.reserve_scoped_control_operation(
                oid,
                {"action": "plugin." + action, "id": identity, "body": body},
                "plugin:" + identity,
            ):
                receipt = gateway.store.control_operation(oid)["receipt"]
                return web.json_response(
                    receipt
                    or {
                        "operation_id": oid,
                        "execution_unknown": True,
                        "error": "Original hook operation unresolved; do not retry",
                    },
                    status=receipt.get("http_status", 200) if receipt else 409,
                )
        except (TypeError, ValueError) as exc:
            return web.json_response({"error": str(exc)}, status=400)
        try:
            if action == "resume_hooks":
                from jaeger_ai.core.gateway.server import _control_plane_block

                if _control_plane_block():
                    raise ValueError(
                        "Global Stop or live-owner guard prevents resuming hooks"
                    )
            result = registry.control_hooks(identity, action, body["expected_state"])
            receipt = {
                "ok": True,
                "operation_id": oid,
                "http_status": 200,
                "result": result,
            }
        except ValueError as exc:
            receipt = {
                "ok": False,
                "operation_id": oid,
                "http_status": 409,
                "error": str(exc),
            }
        except Exception:
            return web.json_response(
                {
                    "operation_id": oid,
                    "execution_unknown": True,
                    "error": "Hook transition unknown; inspect without replay",
                },
                status=503,
            )
        gateway.store.finish_control_operation(oid, receipt)
        gateway.event_bus.publish(
            "*", "plugins.changed", {"id": identity, "confirmed": receipt["ok"]}
        )
        return web.json_response(receipt, status=receipt["http_status"])

    async def startup_policy(request):
        try:
            body = await request.json()
            if (
                not isinstance(body, dict)
                or set(body) != {"operation_id", "expected_revision", "enabled"}
                or type(body["enabled"]) is not bool
            ):
                raise ValueError("Exact startup policy fields required")
            oid = body["operation_id"]
            if not isinstance(oid, str) or not oid.strip() or len(oid) > 128:
                raise ValueError("Stable operation identity required")
            identity = request.match_info["id"]
            startup.assert_package_idle(gateway.store, startup.environment_id())
            if not gateway.store.reserve_scoped_control_operation(
                oid,
                {"action": "plugin.startup", "id": identity, "body": body},
                "plugin-startup:" + startup.environment_id(),
            ):
                receipt = gateway.store.control_operation(oid)["receipt"]
                return web.json_response(
                    receipt
                    or {
                        "operation_id": oid,
                        "execution_unknown": True,
                        "error": "Original policy command unresolved; inspect without replay",
                    },
                    status=receipt.get("http_status", 200) if receipt else 409,
                )
        except (ValueError, TypeError) as exc:
            return web.json_response({"error": str(exc)}, status=400)
        try:
            from jaeger_ai.core.gateway.server import _control_plane_block

            if _control_plane_block():
                raise ValueError(
                    "Global Stop/live owner guard prevents startup policy changes"
                )
            snapshot = registry.catalog(policy=startup.read(gateway.store))
            row = next(
                (
                    row
                    for row in snapshot["plugins"]
                    if row["id"] == identity and row["startup_editable"]
                ),
                None,
            )
            if row is None:
                raise ValueError("Installed exact plugin revision required")
            if body["enabled"] and not row["startup_approvable"]:
                raise ValueError(
                    "Exact installed file integrity is not verifiable; startup permission not changed"
                )
            receipt = startup.save(
                gateway.store,
                environment=startup.environment_id(),
                updates={
                    row["slot_id"]: row["startup_revision_id"]
                    if body["enabled"]
                    else "disabled"
                },
                expected_revision=body["expected_revision"],
                operation_id=oid,
                result={
                    "id": identity,
                    "startup_policy": "enabled_revision"
                    if body["enabled"]
                    else "disabled",
                    "scope": "future_discovery_only",
                    "retained_code": row["state"] != "installed_not_loaded",
                    "restart_required": row["state"] != "installed_not_loaded",
                },
            )
        except ValueError as exc:
            receipt = {
                "ok": False,
                "operation_id": oid,
                "http_status": 409,
                "error": str(exc),
            }
            gateway.store.finish_control_operation(oid, receipt)
        except Exception:
            return web.json_response(
                {
                    "operation_id": oid,
                    "execution_unknown": True,
                    "error": "Policy outcome unknown; inspect original receipt",
                },
                status=503,
            )
        gateway.event_bus.publish(
            "*", "plugins.changed", {"id": identity, "confirmed": receipt["ok"]}
        )
        return web.json_response(receipt, status=receipt["http_status"])

    gateway.app.router.add_get("/v1/runtime/plugins", listing)
    gateway.app.router.add_post("/v1/runtime/plugins/{id}/startup", startup_policy)
    gateway.app.router.add_post("/v1/runtime/plugins/{id}/{action}", mutate)
