"""Authenticated Gateway routes for the Human Needs & Flourishing Engine."""
from __future__ import annotations

import asyncio
from aiohttp import web

from .policy import (
    DEFAULT_QUIET_END_HOUR,
    DEFAULT_QUIET_START_HOUR,
    FlourishingDimension,
    is_quiet_hours,
)
from .store import HumanNeedsStore, default_human_needs_db


def register(gateway) -> None:
    def _store() -> HumanNeedsStore:
        return HumanNeedsStore(default_human_needs_db())

    async def summary(request: web.Request) -> web.Response:
        include_inactive = request.query.get("include_inactive") == "true"
        st = _store()
        prefs = await asyncio.to_thread(st.get_preferences)
        goals = await asyncio.to_thread(st.list_goals, include_inactive=include_inactive)
        opportunities = await asyncio.to_thread(st.list_opportunities)
        outcomes = await asyncio.to_thread(st.list_outcomes, limit=25)
        interventions = await asyncio.to_thread(st.list_interventions, limit=25)
        qs = int(prefs.get("quiet_start_hour", DEFAULT_QUIET_START_HOUR))
        qe = int(prefs.get("quiet_end_hour", DEFAULT_QUIET_END_HOUR))
        return web.json_response({
            "dimensions": [d.value for d in FlourishingDimension],
            "preferences": prefs,
            "policy": {
                "quiet_hours": f"{qs:02d}:00-{qe:02d}:00",
                "in_quiet_hours": is_quiet_hours(quiet_start_hour=qs, quiet_end_hour=qe),
                "never_pauses_active_tasks": True,
                "third_party_contact_requires_authorization": True,
            },
            "goals": goals,
            "opportunities": opportunities,
            "outcomes": outcomes,
            "interventions": interventions,
        })

    async def create_goal(request: web.Request) -> web.Response:
        try:
            body = await request.json()
            if not isinstance(body, dict):
                raise ValueError("JSON object required")
            created = await asyncio.to_thread(
                _store().add_goal,
                str(body.get("title") or ""),
                str(body.get("dimension") or ""),
                signal_kind=str(body.get("signal_kind") or "user_preference"),
                priority=int(body.get("priority", 3)),
                notes=str(body.get("notes") or ""),
                success_metric=str(body.get("success_metric") or ""),
            )
            return web.json_response(created, status=201)
        except (ValueError, TypeError) as exc:
            return web.json_response({"error": str(exc)}, status=400)

    async def patch_goal(request: web.Request) -> web.Response:
        try:
            body = await request.json()
            if not isinstance(body, dict):
                raise ValueError("JSON object required")
            updated = await asyncio.to_thread(
                _store().update_goal,
                request.match_info["id"],
                title=body.get("title"),
                status=body.get("status"),
                priority=body.get("priority"),
                notes=body.get("notes"),
                success_metric=body.get("success_metric"),
            )
            return web.json_response(updated)
        except (ValueError, TypeError) as exc:
            return web.json_response({"error": str(exc)}, status=400)

    async def create_opportunity(request: web.Request) -> web.Response:
        try:
            body = await request.json()
            if not isinstance(body, dict):
                raise ValueError("JSON object required")
            created = await asyncio.to_thread(
                _store().propose_opportunity,
                str(body.get("title") or ""),
                str(body.get("dimension") or ""),
                str(body.get("rationale") or ""),
                goal_id=body.get("goal_id"),
                proposed_action=str(body.get("proposed_action") or ""),
                requires_authorization=bool(body.get("requires_authorization", True)),
            )
            return web.json_response(created, status=201)
        except (ValueError, TypeError) as exc:
            return web.json_response({"error": str(exc)}, status=400)

    async def decide_opportunity(request: web.Request) -> web.Response:
        try:
            body = await request.json()
            if not isinstance(body, dict):
                raise ValueError("JSON object required")
            updated = await asyncio.to_thread(
                _store().decide_opportunity,
                request.match_info["id"],
                str(body.get("decision") or ""),
                user_feedback=str(body.get("user_feedback") or ""),
            )
            return web.json_response(updated)
        except (ValueError, TypeError) as exc:
            return web.json_response({"error": str(exc)}, status=400)

    async def create_outcome(request: web.Request) -> web.Response:
        try:
            body = await request.json()
            if not isinstance(body, dict):
                raise ValueError("JSON object required")
            created = await asyncio.to_thread(
                _store().record_outcome,
                str(body.get("summary") or ""),
                goal_id=body.get("goal_id"),
                opportunity_id=body.get("opportunity_id"),
                signal_kind=str(body.get("signal_kind") or "objective_measure"),
                metric_name=str(body.get("metric_name") or ""),
                metric_before=str(body.get("metric_before") or ""),
                metric_after=str(body.get("metric_after") or ""),
                evidence_ref=str(body.get("evidence_ref") or ""),
            )
            return web.json_response(created, status=201)
        except (ValueError, TypeError) as exc:
            return web.json_response({"error": str(exc)}, status=400)

    async def get_preferences(_request: web.Request) -> web.Response:
        prefs = await asyncio.to_thread(_store().get_preferences)
        return web.json_response(prefs)

    async def patch_preferences(request: web.Request) -> web.Response:
        try:
            body = await request.json()
            if not isinstance(body, dict):
                raise ValueError("JSON object required")
            updated = await asyncio.to_thread(_store().update_preferences, body)
            return web.json_response(updated)
        except (ValueError, TypeError) as exc:
            return web.json_response({"error": str(exc)}, status=400)

    async def patch_opportunity(request: web.Request) -> web.Response:
        try:
            body = await request.json()
            if not isinstance(body, dict):
                raise ValueError("JSON object required")
            updated = await asyncio.to_thread(
                _store().correct_opportunity,
                request.match_info["id"],
                title=body.get("title"),
                rationale=body.get("rationale"),
                dimension=body.get("dimension"),
                user_feedback=body.get("user_feedback"),
            )
            return web.json_response(updated)
        except (ValueError, TypeError) as exc:
            return web.json_response({"error": str(exc)}, status=400)

    async def run_heartbeat_now(_request: web.Request) -> web.Response:
        from .heartbeat_loop import run_human_needs_heartbeat
        report = await asyncio.to_thread(run_human_needs_heartbeat)
        return web.json_response(report.to_dict())

    async def export_data(_request: web.Request) -> web.Response:
        data = await asyncio.to_thread(_store().export_all)
        return web.json_response(data)

    gateway.app.router.add_get("/v1/human-needs/summary", summary)
    gateway.app.router.add_get("/v1/human-needs/preferences", get_preferences)
    gateway.app.router.add_patch("/v1/human-needs/preferences", patch_preferences)
    gateway.app.router.add_post("/v1/human-needs/goals", create_goal)
    gateway.app.router.add_patch("/v1/human-needs/goals/{id}", patch_goal)
    gateway.app.router.add_post("/v1/human-needs/opportunities", create_opportunity)
    gateway.app.router.add_patch("/v1/human-needs/opportunities/{id}", patch_opportunity)
    gateway.app.router.add_post("/v1/human-needs/opportunities/{id}/decide", decide_opportunity)
    gateway.app.router.add_post("/v1/human-needs/outcomes", create_outcome)
    gateway.app.router.add_post("/v1/human-needs/heartbeat/run", run_heartbeat_now)
    gateway.app.router.add_get("/v1/human-needs/export", export_data)
