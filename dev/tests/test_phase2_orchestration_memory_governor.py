"""Phase 2 tests: Durable SQLite Pregel + time-travel fork, safe_expr, Dry-Run, 32GB Governor, Memory 2.0, Gateway APIs."""

from __future__ import annotations

from pathlib import Path

import pytest
from aiohttp.test_utils import TestClient, TestServer

from jaeger_gateway import ModularGatewayRuntime
from jaeger_memory import (
    EPHEMERAL_MARKER,
    PersistentLearningStore,
    inject_ephemeral_status,
)
from jaeger_orchestration import (
    Command,
    DryRunSimulator,
    PregelGraph,
    PriorityTier,
    ResourceGovernor,
    SqlitePregelCheckpointer,
    UnsafeExpressionError,
    evaluate_condition,
    interrupt,
)


def test_durable_sqlite_pregel_survives_restart_and_forks(tmp_path: Path) -> None:
    db = tmp_path / "pregel.sqlite3"

    def build_graph() -> PregelGraph:
        g = PregelGraph(checkpointer=SqlitePregelCheckpointer(db))
        g.add_node("draft", lambda s: {"script": f"Draft for {s['topic']}"})
        g.add_node("review", lambda s: {"approved_note": interrupt({"ask": f"Approve {s['script']}?"})})
        g.add_node("publish", lambda s: {"published": True, "final": f"{s['script']} ({s['approved_note']})"})
        g.add_edge("draft", "review")
        g.add_edge("review", "publish")
        return g

    # Run 1 pauses for human approval
    g1 = build_graph()
    r1 = g1.invoke({"topic": "JP01 Droid"}, run_id="yt_ep1")
    assert r1.status == "interrupted"
    assert r1.interrupted_node == "review"

    # Simulate process restart: brand-new PregelGraph instance backed by same SQLite WAL db!
    g2 = build_graph()
    r2 = g2.invoke(Command(resume="Ship it!"), run_id="yt_ep1")
    assert r2.status == "completed"
    assert r2.state["published"] is True
    assert "Ship it!" in r2.state["final"]

    # Time-travel fork from the 'draft' step checkpoint with a different topic
    hist = g2.get_state_history("yt_ep1")
    draft_cp = next(c for c in hist if c.node == "draft")
    forked = g2.fork_from(
        draft_cp.checkpoint_id,
        update={"script": "Revised Script v2", "approved_note": "Fast-tracked"},
        goto="publish",
    )
    assert forked.status == "completed"
    assert "Revised Script v2" in forked.state["final"]


def test_safe_expr_evaluates_and_blocks_unsafe_code() -> None:
    assert evaluate_condition("state.score >= 8 and not state.dry_run", {"state": {"score": 9, "dry_run": False}}) is True
    assert evaluate_condition("contains(lower(title), 'youtube')", {"title": "My YouTube Launch"}) is True
    with pytest.raises(UnsafeExpressionError):
        evaluate_condition("__import__('os').system('echo pwn')", {})
    with pytest.raises(UnsafeExpressionError):
        evaluate_condition("x.__class__.__mro__", {"x": 1})


def test_dry_run_simulator_flags_side_effects() -> None:
    sim = DryRunSimulator()
    rep = sim.simulate_workflow(
        "YouTube Publish",
        [
            {"id": "s1", "name": "Research", "action": "web_search", "read_only": True},
            {"id": "s2", "name": "Upload Video", "action": "youtube_publish", "args": {"title": "Ep 1"}},
        ],
    )
    assert rep.estimated_ok is True
    assert rep.total_side_effect_steps == 1
    assert rep.steps[0].would_have_side_effects is False
    assert rep.steps[1].would_have_side_effects is True


def test_resource_governor_single_heavy_model_and_owner_preempts_minecraft() -> None:
    gov = ResourceGovernor(memory_cap_gb=24.0, idle_cooldown_s=10.0)
    preempted_reasons: list[str] = []
    gov.register_idle_preempt_hook(preempted_reasons.append)

    # Idle Minecraft can run initially
    ok, _ = gov.acquire_heavy_model("gemma4:12b", tier=PriorityTier.IDLE_LIFE, owner_tag="minecraft", estimated_gb=10.0)
    assert ok is True

    # Owner work arrives -> immediately preempts Minecraft + takes heavy model slot!
    gov.begin_owner_work("youtube_script")
    assert preempted_reasons == ["youtube_script"]
    allowed_idle, why = gov.can_run_idle_life()
    assert allowed_idle is False and why == "owner_work_active"

    ok2, status2 = gov.acquire_heavy_model("qwen3-vl:8b", tier=PriorityTier.OWNER_WORK, owner_tag="owner", estimated_gb=8.0)
    assert ok2 is True and status2 == "acquired"

    # E-Stop latches and disables idle autonomy immediately
    gov.trigger_estop("motor_limit")
    assert gov.snapshot()["estop_active"] is True
    assert gov.can_run_idle_life() == (False, "estop_active")
    gov.release_estop()
    assert gov.snapshot()["estop_active"] is False


def test_memory2_learning_recall_cascading_forget_goals_and_statusbar(tmp_path: Path) -> None:
    store = PersistentLearningStore(tmp_path)
    src = store.add(scope="business", subject="youtube", content="Target audience loves robotics engineering builds", importance=0.9, tags=["youtube", "robotics"])
    derived = store.add(
        scope="learned_knowledge",
        subject="youtube",
        content="Opening hooks should show the JP01 droid moving in the first 3 seconds",
        importance=0.85,
        parent_ids=[src.entry_id],
    )
    hits = store.recall("JP01 droid youtube hooks")
    assert hits and hits[0].entry_id == derived.entry_id

    # Cascading forget removes source AND derived memory together!
    removed = store.forget(src.entry_id, cascade=True)
    assert set(removed) == {src.entry_id, derived.entry_id}
    assert store.list_entries() == []

    # Persistent multi-day goals for both YouTube business and idle Minecraft life
    g_biz = store.upsert_goal(domain="youtube", title="Ship Episode 1", priority=1, checkpoint={"stage": "script"})
    g_mc = store.upsert_goal(domain="minecraft", title="Build iron farm", priority=3, checkpoint={"x": 120, "y": 64, "z": -40})
    assert len(store.list_goals()) == 2
    assert store.list_goals(domain="minecraft")[0].checkpoint["x"] == 120
    assert g_biz.goal_id != g_mc.goal_id

    # Ephemeral statusbar strips old status and appends fresh live context
    msgs = inject_ephemeral_status(
        [{"role": "user", "content": "status?"}, {"role": "system", "content": f"{EPHEMERAL_MARKER}\nstale"}],
        [lambda: {"mode": "OWNER_WORK", "ram_free_gb": 14.2}],
    )
    assert len(msgs) == 2
    assert "14.2" in msgs[-1]["content"]
    assert "stale" not in msgs[-1]["content"]


@pytest.mark.asyncio
async def test_gateway_phase2_endpoints(tmp_path: Path) -> None:
    rt = ModularGatewayRuntime(state_dir=tmp_path / "state", workspace=tmp_path)
    try:
        app = rt.build_app(serve_ui=False)
        async with TestClient(TestServer(app)) as client:
            r_res = await client.get("/v1/system/resources")
            assert r_res.status == 200
            d_res = await r_res.json()
            assert d_res["ok"] is True and d_res["resources"]["memory_cap_gb"] == 24.0

            r_dry = await client.post("/v1/workflows/dry-run", json={"name": "YT", "steps": [{"action": "youtube_publish"}]})
            assert r_dry.status == 200
            assert (await r_dry.json())["dry_run"]["total_side_effect_steps"] == 1

            r_add = await client.post("/v1/memory/learning", json={"scope": "business", "content": "Upload every Tuesday"})
            assert r_add.status == 201
            eid = (await r_add.json())["entry"]["entry_id"]

            r_goal = await client.post("/v1/memory/goals", json={"domain": "minecraft", "title": "Build castle", "checkpoint": {"x": 10}})
            assert r_goal.status == 201

            r_del = await client.delete(f"/v1/memory/learning/{eid}?cascade=true")
            assert r_del.status == 200 and (await r_del.json())["count"] == 1
    finally:
        rt.close()
