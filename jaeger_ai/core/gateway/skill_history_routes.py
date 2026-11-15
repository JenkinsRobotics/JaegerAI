"""Skill revision history + rollback for the owner (Settings › Skills)."""
from __future__ import annotations

from dataclasses import asdict

from aiohttp import web


def register(gateway) -> None:
    from jaeger_agent.skill_improvement import skill_history as sh
    from jaeger_agent.skill_improvement import skill_revisions

    from jaeger_ai.core.instance.instance import InstanceLayout

    def layout():
        return InstanceLayout(root=gateway._instance_root())

    async def revisions(request):
        """Recent revisions across all skills (newest first)."""
        rows = [asdict(r) for r in skill_revisions._load(layout())]
        limit = max(1, min(500, int(request.query.get("limit") or 100)))
        return web.json_response({"revisions": rows[::-1][:limit], "counts": skill_revisions.counts(layout())})

    async def history(request):
        name = request.query.get("name", "")
        try:
            lay = layout()
            folder = sh.skill_folder(lay, sh._clean_name(name))
            return web.json_response({"skill": sh._clean_name(name), "mutable": folder is not None,
                                      "versions": sh.versions(lay, name)[::-1]})
        except sh.SkillHistoryError as exc:
            return web.json_response({"error": str(exc)}, status=400)

    async def version(request):
        try:
            text = sh.read_version(layout(), request.query.get("name", ""), request.query.get("version", ""))
            return web.json_response({"content": text})
        except sh.SkillHistoryError as exc:
            return web.json_response({"error": str(exc)}, status=404)

    async def rollback(request):
        try:
            body = await request.json()
            out = sh.rollback(layout(), str(body.get("name") or ""), str(body.get("version") or ""), origin="manual")
        except (ValueError, TypeError) as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=400)
        gateway.event_bus.publish("*", "skill.revised", {"skill": out.get("skill"), "version": out.get("version")})
        return web.json_response(out)

    gateway.app.router.add_get("/v1/runtime/skills/revisions", revisions)
    gateway.app.router.add_get("/v1/runtime/skills/history", history)
    gateway.app.router.add_get("/v1/runtime/skills/history/version", version)
    gateway.app.router.add_post("/v1/runtime/skills/history/rollback", rollback)
