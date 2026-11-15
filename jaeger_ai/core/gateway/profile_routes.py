"""Owner profile (memory/USER.md) + nightly memory upkeep controls."""
from __future__ import annotations

from aiohttp import web


def register(gateway) -> None:
    from jaeger_agent.memory import user_profile as up

    from jaeger_ai.core.instance.instance import InstanceLayout
    from jaeger_ai.core.runtime import memory_upkeep as mu

    def layout():
        return InstanceLayout(root=gateway._instance_root())

    async def get_profile(request):
        lay = layout()
        text = up.load(lay)
        return web.json_response({"profile": text, "chars": len(text), "limit": up.MAX_CHARS,
                                  "sections": list(up.SECTIONS), "changes": up.changes(lay, 30)})

    async def put_profile(request):
        try:
            body = await request.json()
            out = up.save(layout(), str(body.get("profile") or ""), origin="owner",
                          summary=str(body.get("summary") or "edited in Settings"))
        except (ValueError, TypeError) as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=400)
        gateway.event_bus.publish("*", "profile.changed", {"origin": "owner"})
        return web.json_response(out)

    async def revert_profile(request):
        try:
            body = await request.json()
            name = str(body.get("previous") or "")
            if not name.endswith(".md") or "/" in name or ".." in name:
                raise ValueError("Unknown profile version")
            snap = up.history_dir(layout()) / name
            if not snap.is_file():
                raise ValueError("Unknown profile version")
            out = up.save(layout(), snap.read_text(encoding="utf-8"), origin="owner", summary=f"restored {name}")
        except (ValueError, TypeError) as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=400)
        return web.json_response(out)

    async def get_upkeep(request):
        return web.json_response(mu.status(layout()))

    async def patch_upkeep(request):
        try:
            body = await request.json()
            out = mu.configure(layout(), enabled=body.get("enabled"), hour=body.get("hour"))
        except (ValueError, TypeError) as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=400)
        return web.json_response(out)

    gateway.app.router.add_get("/v1/memory/profile", get_profile)
    gateway.app.router.add_put("/v1/memory/profile", put_profile)
    gateway.app.router.add_post("/v1/memory/profile/revert", revert_profile)
    gateway.app.router.add_get("/v1/memory/upkeep", get_upkeep)
    gateway.app.router.add_patch("/v1/memory/upkeep", patch_upkeep)
