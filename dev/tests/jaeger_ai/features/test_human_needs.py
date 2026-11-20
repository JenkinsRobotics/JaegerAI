"""Tests for the Human Needs & Flourishing Engine (policy, store, isolation, Gateway routes)."""
from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from jaeger_ai.features.human_needs import (
    FlourishingDimension,
    HumanNeedsStore,
    SignalKind,
    default_human_needs_db,
    evaluate_nudge,
    is_quiet_hours,
)
from jaeger_ai.features.human_needs.routes import register as register_human_needs


def test_quiet_hours_and_non_intrusive_nudge_policy():
    late = datetime(2026, 11, 19, 23, 15)
    morning = datetime(2026, 11, 19, 6, 30)
    daytime = datetime(2026, 11, 19, 14, 0)

    assert is_quiet_hours(late) is True
    assert is_quiet_hours(morning) is True
    assert is_quiet_hours(daytime) is False

    # Quiet hours defer to daily digest
    d_quiet = evaluate_nudge(FlourishingDimension.SECURITY, now=late)
    assert d_quiet.deliver == "daily_digest" and d_quiet.pause_active_task is False

    # Active task is never paused or interrupted
    d_busy = evaluate_nudge(FlourishingDimension.SECURITY, active_task_running=True, now=daytime)
    assert d_busy.deliver == "daily_digest" and d_busy.pause_active_task is False

    # Belonging and self-transcendence default to daily digest
    d_belong = evaluate_nudge(FlourishingDimension.BELONGING, now=daytime)
    assert d_belong.deliver == "daily_digest"

    # Unauthorized third-party contact is always suppressed
    d_contact = evaluate_nudge(FlourishingDimension.BELONGING, now=daytime, contacts_third_party=True)
    assert d_contact.deliver == "suppress" and d_contact.allow_third_party_contact is False

    # Daytime security nudge with no active task is permitted as gentle nudge
    d_ok = evaluate_nudge(FlourishingDimension.SECURITY, now=daytime)
    assert d_ok.deliver == "gentle_nudge" and d_ok.pause_active_task is False


def test_store_lifecycle_user_rejection_outcomes_and_export(tmp_path: Path):
    store = HumanNeedsStore(tmp_path / "human_needs.sqlite3")
    goal = store.add_goal(
        "Build sustainable revenue runway",
        FlourishingDimension.SECURITY,
        signal_kind=SignalKind.USER_PREFERENCE,
        priority=1,
        success_metric="Positive monthly net cashflow",
    )
    assert goal["dimension"] == "security" and goal["signal_kind"] == "user_preference"

    opp = store.propose_opportunity(
        "Draft budget & grant checklist",
        FlourishingDimension.SECURITY,
        "Links directly to runway goal",
        goal_id=goal["goal_id"],
        proposed_action="Prepare local budget sheet for user review",
    )
    assert opp["signal_kind"] == "inferred_opportunity" and opp["status"] == "proposed"

    # User can accept or reject any opportunity
    decided = store.decide_opportunity(opp["opportunity_id"], "accepted", user_feedback="Good starting step")
    assert decided["status"] == "accepted"

    opp_bad = store.propose_opportunity(
        "Unwanted suggestion",
        FlourishingDimension.BELONGING,
        "Inferred guess",
    )
    rejected = store.decide_opportunity(opp_bad["opportunity_id"], "rejected", user_feedback="Not relevant")
    assert rejected["status"] == "rejected"

    outcome = store.record_outcome(
        "Completed monthly expense audit",
        goal_id=goal["goal_id"],
        opportunity_id=opp["opportunity_id"],
        signal_kind=SignalKind.OBJECTIVE_MEASURE,
        metric_name="monthly_burn_usd",
        metric_before="4200",
        metric_after="3450",
        evidence_ref="sheet://budget-2026-11",
    )
    assert outcome["signal_kind"] == "objective_measure"

    exported = store.export_all()
    assert exported["schema"] == "jaeger.human_needs.export.v1"
    assert len(exported["goals"]) == 1
    assert len(exported["opportunities"]) == 2
    assert len(exported["outcomes"]) == 1


def test_store_respects_state_dir_and_gateway_routes(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("JAEGER_STATE_DIR", str(tmp_path))
    assert default_human_needs_db() == tmp_path / "human_needs.sqlite3"

    async def run():
        app = web.Application()
        register_human_needs(SimpleNamespace(app=app))
        async with TestClient(TestServer(app)) as cl:
            r = await cl.post("/v1/human-needs/goals", json={
                "title": "Ship JaegerAI v1",
                "dimension": "self_actualization",
                "priority": 1,
            })
            assert r.status == 201
            goal = await r.json()

            r = await cl.post("/v1/human-needs/opportunities", json={
                "title": "Verify vertical slice in isolation",
                "dimension": "competence_esteem",
                "rationale": "Unblocks reliable autonomy",
                "goal_id": goal["goal_id"],
            })
            assert r.status == 201
            opp = await r.json()

            r = await cl.post(f"/v1/human-needs/opportunities/{opp['opportunity_id']}/decide", json={
                "decision": "accepted",
                "user_feedback": "Proceed",
            })
            assert r.status == 200 and (await r.json())["status"] == "accepted"

            r = await cl.get("/v1/human-needs/summary")
            body = await r.json()
            assert r.status == 200 and len(body["goals"]) == 1 and len(body["opportunities"]) == 1

            r = await cl.get("/v1/human-needs/export")
            exp = await r.json()
            assert r.status == 200 and exp["schema"] == "jaeger.human_needs.export.v1"

    asyncio.run(run())
