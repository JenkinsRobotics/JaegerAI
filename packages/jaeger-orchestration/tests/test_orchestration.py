"""Standalone & full-stack E2E tests for jaeger-orchestration + all 9 Jaeger modules together."""

from __future__ import annotations

from pathlib import Path

import pytest

from jaeger_authority import PolicyEngine, UnconfinedSandbox
from jaeger_contracts import EventBusPort, OrchestrationPort, PolicyPort, SandboxPort, SandboxProfile
from jaeger_events import EventBus
from jaeger_loop import AgentLoop
from jaeger_memory import SqliteStateMemory
from jaeger_models import ReplayModel
from jaeger_orchestration import (
    CronScheduler,
    DurableMailbox,
    SubagentOrchestrator,
    intersect_sandbox_profiles,
)
from jaeger_reliability import ReliabilityEngine
from jaeger_tools import ToolRegistry


def test_spawn_permission_intersection_never_widens_authority(tmp_path: Path) -> None:
    parent_ws = tmp_path / "repo"
    sub_ws = parent_ws / "subpkg"
    outside_ws = tmp_path / "outside"
    sub_ws.mkdir(parents=True)
    outside_ws.mkdir()

    parent = SandboxProfile(
        workspace=parent_ws,
        denied_read_paths=(tmp_path / "secret",),
        allow_network=False,
        read_only_default=True,
    )
    # Child tries to widen network=True and escape to outside_ws
    greedy_child = SandboxProfile(
        workspace=outside_ws,
        writable_roots=(outside_ws,),
        allow_network=True,
        read_only_default=False,
    )
    eff = intersect_sandbox_profiles(parent, greedy_child)
    assert eff.workspace == parent_ws.resolve()
    assert eff.writable_roots == ()
    assert eff.allow_network is False
    assert eff.read_only_default is True
    assert (tmp_path / "secret") in eff.denied_read_paths

    # Child staying inside a subdirectory of parent IS allowed to narrow workspace
    narrow_child = SandboxProfile(workspace=sub_ws, allow_network=False)
    eff_narrow = intersect_sandbox_profiles(parent, narrow_child)
    assert eff_narrow.workspace == sub_ws.resolve()


def test_full_9_module_end_to_end_orchestration_and_mailbox_arbiter(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    bus = EventBus()
    completed_events: list[dict] = []
    bus.subscribe("subagent.completed", lambda ev: completed_events.append(dict(ev.payload)))

    mailbox = DurableMailbox(
        tmp_path / "state",
        arbiter=lambda sender, _rcpt, _payload: sender != "rogue_agent",
    )
    with pytest.raises(PermissionError):
        mailbox.send("rogue_agent", "coordinator", {"msg": "blocked"})

    def make_loop(agent_id: str, role: str, _profile: SandboxProfile | None) -> AgentLoop:
        tools = ToolRegistry(workspace=ws, policy=PolicyEngine(), sandbox=UnconfinedSandbox())
        tools.register_shell_tool()
        model = ReplayModel([
            {"content": "", "tool_calls": [{"id": "t1", "name": "shell", "arguments": {"command": f"echo {role}_OK"}}]},
            {"content": f"Worker {role} finished."},
        ])
        return AgentLoop(
            model=model,
            tools=tools,
            memory=SqliteStateMemory(tmp_path / "state" / agent_id),
            reliability=ReliabilityEngine(),
            events=bus,
            session_id=agent_id,
        )

    orch = SubagentOrchestrator(loop_factory=make_loop, events=bus, mailbox=mailbox, max_depth=2)
    assert isinstance(orch, OrchestrationPort)

    # Verify protocol conformance across all participating standalone modules
    assert isinstance(bus, EventBusPort)
    assert isinstance(PolicyEngine(), PolicyPort)
    assert isinstance(UnconfinedSandbox(), SandboxPort)
    assert isinstance(orch, OrchestrationPort)

    try:
        parent_prof = SandboxProfile(workspace=ws, allow_network=False)
        child_id = orch.spawn("Run checks", role="builder", parent_profile=parent_prof, depth=1)
        res = orch.await_result(child_id)
        assert res["verdict"] == "complete"
        assert res["content"] == "Worker builder finished."

        # Depth cap enforced
        with pytest.raises(RecursionError):
            orch.spawn("Too deep", role="x", depth=3)

        # Push delivery landed in both EventBus and eviction-safe DurableMailbox
        assert len(completed_events) == 1 and completed_events[0]["agent_id"] == child_id
        inbox = mailbox.drain("coordinator")
        assert len(inbox) == 1 and inbox[0]["sender"] == child_id
    finally:
        orch.close()


def test_cron_scheduler_ticks_and_isolates_errors() -> None:
    now = [1000.0]
    ran: list[float] = []
    sched = CronScheduler(clock=lambda: now[0])
    sched.register("health", 60.0, lambda: ran.append(now[0]))
    sched.register("flaky", 60.0, lambda: (_ for _ in ()).throw(RuntimeError("err")))

    assert sched.tick() == ["health"]
    assert sched.tick() == []  # interval not elapsed yet
    now[0] += 61.0
    assert sched.tick() == ["health"]
    assert len(ran) == 2


def test_deep_research_engine_and_ssrf_guard(tmp_path: Path) -> None:
    from jaeger_orchestration import DeepResearchEngine, list_research_reports, safe_fetch_text

    # SSRF guard MUST block localhost/private targets
    with pytest.raises(ValueError, match="non-public"):
        safe_fetch_text("http://127.0.0.1:8790/secret")
    with pytest.raises(ValueError, match="non-public"):
        safe_fetch_text("http://localhost:11434/api/tags")

    def fake_search(q: str, limit: int) -> dict:
        return {
            "provider": "mock",
            "query": q,
            "results": [
                {
                    "title": f"Guide for {q}",
                    "url": "https://example.org/robotics-guide",
                    "snippet": "BLDC actuators achieve high torque density.",
                },
                {
                    "title": "Benchmarks",
                    "url": "https://example.org/benchmarks",
                    "snippet": "Thermal limits govern continuous torque.",
                },
            ][:limit],
        }

    def fake_fetch(url: str) -> str:
        return f"Full extracted text from {url}: harmonic drives reduce backlash."

    model = ReplayModel(
        [
            {"content": "BLDC robotics actuators\nHarmonic drive tradeoffs"},
            {"content": "## Executive Summary\nHarmonic drives reduce backlash [1].\n\n## Key Findings\n- Thermal limits matter [2]."},
        ],
        model_id="local/test",
    )
    engine = DeepResearchEngine(
        search_fn=fake_search,
        fetch_fn=fake_fetch,
        model=model,
        reports_dir=tmp_path / "reports",
    )
    rep = engine.run("BLDC robot actuators", max_queries=2, max_sources=4)
    assert rep.report_id.startswith("res_")
    assert len(rep.sources) == 2
    assert all(s.fetched for s in rep.sources)
    assert "Harmonic drives" in rep.markdown
    assert '<nav class="toc">' in rep.html_report
    assert Path(rep.saved_dir, "report.html").is_file()
    saved = list_research_reports(tmp_path / "reports")
    assert len(saved) == 1 and saved[0]["report_id"] == rep.report_id
