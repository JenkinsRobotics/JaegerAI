"""Owner-only routes for GB-031 (authority preview) and GB-032 (connector grants).

Mount with ``mount_blueprint_routes(gateway)``. Every route requires an owner
caller with ``admin`` scope and no session prefix (same rule as
``policy_status``). No route writes review rules; the preview is read-only.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from aiohttp import web

GRANTS_DB = "connector_grants.sqlite3"
_STORE_KEY = "blueprint_connector_grants"


def _require_owner(request: web.Request) -> str:
    caller = request.get("caller")
    actor = request.get("caller_actor", "") or ""
    if caller is None or caller.session_prefix or "admin" not in caller.scopes or not actor.startswith("owner:"):
        raise web.HTTPForbidden(text="Existing owner administration scope required")
    return actor


def _bad(msg: str, status: int = 400) -> web.Response:
    return web.json_response({"error": msg}, status=status)


async def _body(request: web.Request) -> dict[str, Any]:
    try:
        data = await request.json()
    except Exception:  # noqa: BLE001
        raise web.HTTPBadRequest(text='{"error":"invalid JSON body"}', content_type="application/json")
    if not isinstance(data, dict):
        raise web.HTTPBadRequest(text='{"error":"body must be an object"}', content_type="application/json")
    return data


def _instance_root():
    from jaeger_ai.core.entity.runtime import EntityRuntime
    runtime = EntityRuntime._instance  # never get_singleton(): must not start a resident
    return getattr(runtime, "layout", None)


def _publish(gateway, event: str, data: dict[str, Any]) -> None:
    bus = getattr(gateway, "event_bus", None)
    try:
        if bus is not None:
            bus.publish("*", event, data)
    except Exception:  # noqa: BLE001
        pass


def mount_blueprint_routes(gateway, *, grants_path: Path | str | None = None) -> None:
    from jaeger_ai.core.authority.kernel import (
        PolicyKernel, ProposedAction, ReviewRule, ReviewRuleError, ReviewRuleStore,
    )
    from jaeger_ai.core.gateway.connector_grants import ConnectorGrantStore, GrantError

    if grants_path is None:
        grants_path = Path(gateway.store.path).parent / GRANTS_DB
    grants = ConnectorGrantStore(grants_path)
    gateway.app[_STORE_KEY] = grants

    async def preview(request):
        _require_owner(request)
        data = await _body(request)
        tool = str(data.get("tool_name") or "").strip()
        if not tool:
            return _bad("tool_name is required")
        try:
            pending = [ReviewRule.build(r) for r in (data.get("pending_rules") or [])]
        except (ReviewRuleError, TypeError, ValueError) as exc:
            return _bad(f"invalid pending rule: {exc}")
        args = data.get("arguments") or {}
        ctx = data.get("context") or {}
        if not isinstance(args, dict) or not isinstance(ctx, dict):
            return _bad("arguments and context must be objects")
        kw = {k: data[k] for k in ("actor", "tier", "target_path", "action_type", "session_id") if data.get(k)}
        proposal = ProposedAction(tool_name=tool, arguments=args, context=ctx, **kw)
        return web.json_response(PolicyKernel().preview(proposal, instance_root=_instance_root(),
                                                       extra_rules=pending))

    async def review_rules(request):
        _require_owner(request)
        root = _instance_root()
        if root is None:
            return web.json_response({"bound": False, "revisions": None, "rules": [], "history_count": 0})
        store = ReviewRuleStore.for_instance(root)
        try:
            return web.json_response({"bound": True, "revisions": store.revisions(),
                                      "rules": [r.to_dict() for r in store.active_rules()],
                                      "history_count": len(store.history())})
        except ReviewRuleError as exc:
            return _bad(str(exc), 409)

    async def list_grants(request):
        _require_owner(request)
        q = request.query
        rows = grants.list(connector=q.get("connector", ""), account_id=q.get("account_id", ""),
                           include_inactive=q.get("include_inactive") in ("1", "true"))
        return web.json_response({"grants": [g.to_dict() for g in rows]})

    async def get_grant(request):
        _require_owner(request)
        g = grants.get(request.match_info["grant_id"])
        return web.json_response(g.to_dict()) if g else _bad("grant not found", 404)

    async def create_grant(request):
        actor = _require_owner(request)
        d = await _body(request)
        try:
            g, created = grants.create(connector=d.get("connector"), account_id=d.get("account_id"),
                                       tools=d.get("tools"), scopes=d.get("scopes") or [],
                                       callback_id=d.get("callback_id") or "", provenance=actor)
        except GrantError as exc:
            return _bad(str(exc))
        if created:
            _publish(gateway, "connector_grant.updated", {"grant_id": g.grant_id, "status": g.status,
                                                         "connector": g.connector, "account_id": g.account_id,
                                                         "revision": g.revision})
        return web.json_response({"grant": g.to_dict(), "created": created}, status=201 if created else 200)

    async def revoke_grant(request):
        _require_owner(request)
        gid = request.match_info["grant_id"]
        before = grants.get(gid)
        if before is None:
            return _bad("grant not found", 404)
        d = await _body(request) if request.can_read_body else {}
        g = grants.revoke(gid, reason=str(d.get("reason") or ""))
        if before.status != g.status:
            _publish(gateway, "connector_grant.updated", {"grant_id": g.grant_id, "status": g.status,
                                                         "connector": g.connector, "account_id": g.account_id,
                                                         "revision": g.revision})
        return web.json_response({"grant": g.to_dict(), "changed": before.status != g.status})

    async def check_grant(request):
        _require_owner(request)
        d = await _body(request)
        if not d.get("tool"):
            return _bad("tool is required")
        try:
            out = grants.authorize_call(request.match_info["grant_id"], tool=d["tool"],
                                        required_scopes=d.get("required_scopes") or [],
                                        expected_revision=d.get("expected_revision"))
        except (GrantError, TypeError, ValueError) as exc:
            return _bad(str(exc))
        return web.json_response(out)

    r = gateway.app.router
    r.add_post("/v1/authority/preview", preview)
    r.add_get("/v1/authority/review-rules", review_rules)
    r.add_get("/v1/connector-grants", list_grants)
    r.add_post("/v1/connector-grants", create_grant)
    r.add_get("/v1/connector-grants/{grant_id}", get_grant)
    r.add_post("/v1/connector-grants/{grant_id}/revoke", revoke_grant)
    r.add_post("/v1/connector-grants/{grant_id}/check", check_grant)
