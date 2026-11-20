"""Tests for Truth's epistemic, Human Needs, and Character Council agent tools."""
from __future__ import annotations

from pathlib import Path
import pytest

from jaeger_ai.core.authority.kernel import AuthorityDecisionType, PolicyKernel, ProposedAction
from jaeger_ai.core.world.tools import (
    knowledge_contradictions,
    knowledge_query,
    knowledge_record_claim,
    knowledge_verify_claim,
)
from jaeger_ai.features.human_needs.tools import (
    human_needs_add_goal,
    human_needs_propose_opportunity,
    human_needs_record_outcome,
    human_needs_summary,
)
from jaeger_ai.features.personality.companion import CompanionMemory
from jaeger_ai.features.personality.tools import summon_council


def test_knowledge_tools_record_contradict_and_verify(tmp_path: Path):
    db = tmp_path / "knowledge.sqlite3"
    r1 = knowledge_record_claim(
        "MacStudio", "ram_gb", "32", provenance="observed", confidence=0.9,
        evidence_snippet="sysctl hw.memsize=34359738368", db_path=db,
    )
    assert r1["ok"] is True
    assert r1["evidence_id"] is not None
    assert r1["contradictions"] == []

    r2 = knowledge_record_claim(
        "MacStudio", "ram_gb", "64", provenance="hypothesis", confidence=0.4, db_path=db,
    )
    assert r2["ok"] is True
    assert len(r2["contradictions"]) == 1

    ctr = knowledge_contradictions(subject="MacStudio", db_path=db)
    assert ctr["ok"] is True and ctr["count"] == 1

    ver = knowledge_verify_claim(
        r1["claim_id"], source_type="command", source_id="sysctl",
        snippet="hw.memsize: 34359738368", confidence=1.0, db_path=db,
    )
    assert ver["ok"] is True and ver["provenance"] == "verified"

    qry = knowledge_query(subject="MacStudio", db_path=db)
    assert qry["ok"] is True and qry["count"] == 2
    by_id = {c["claim_id"]: c for c in qry["claims"]}
    assert by_id[r1["claim_id"]]["provenance"] == "verified"
    assert by_id[r2["claim_id"]]["provenance"] == "hypothesis"


def test_human_needs_tools_enforce_policy_guardrails(tmp_path: Path):
    db = tmp_path / "human_needs.sqlite3"
    g = human_needs_add_goal(
        "Sleep 8 hours", "physical_wellbeing", priority=1,
        success_metric="7-day average >= 8h", db_path=db,
    )
    assert g["ok"] is True
    gid = g["goal"]["goal_id"]

    # Third-party contact without authorization must be suppressed
    sup = human_needs_propose_opportunity(
        "Text a friend", "belonging", "Catch up this week",
        goal_id=gid, contacts_third_party=True, db_path=db,
    )
    assert sup["ok"] is False and sup["suppressed"] is True
    assert sup["nudge_policy"]["deliver"] == "suppress"

    # Active task or digest-only dimension routes to daily_digest, never pauses task
    opp = human_needs_propose_opportunity(
        "Review weekly community meetup", "belonging", "Supports belonging without interrupting work",
        goal_id=gid, active_task_running=True, db_path=db,
    )
    assert opp["ok"] is True
    assert opp["nudge_policy"]["deliver"] == "daily_digest"
    assert opp["nudge_policy"]["pause_active_task"] is False

    out = human_needs_record_outcome(
        "Averaged 8.1h across 7 nights", goal_id=gid,
        metric_name="sleep_hours", metric_before="6.8", metric_after="8.1", db_path=db,
    )
    assert out["ok"] is True

    summary = human_needs_summary(db_path=db)
    assert summary["ok"] is True
    assert len(summary["goals"]) == 1
    assert len(summary["opportunities"]) == 1
    assert len(summary["outcomes"]) == 1


def test_summon_council_tool_scoped_memory_and_truth_synthesis(tmp_path: Path):
    mem = CompanionMemory(path=tmp_path / "companion.sqlite3", embedder=lambda texts: [[1.0, 0.0] for _ in texts])

    def fake_post(url: str, payload: dict, timeout: float):
        sys_msg = payload["messages"][0]["content"]
        if "You are Truth." in sys_msg:
            return {"message": {"content": "Synthesis: verify claims empirically before deciding."}}
        return {"message": {"content": f"Voice reply ({len(payload['messages'])} msgs)"}}

    bad = summon_council(["truth"], "Need at least two", memory=mem, post=fake_post)
    assert bad["ok"] is False

    res = summon_council(
        ["glados", "jarvis"],
        "Should we migrate to a local-first memory layout?",
        include_truth_synthesis=True,
        memory=mem,
        post=fake_post,
    )
    assert res["ok"] is True
    assert res["mode"] == "council"
    assert len(res["turns"]) == 2
    assert res["truth_synthesis"] is not None
    assert "verify" in res["truth_synthesis"]["reply"].lower()


@pytest.mark.parametrize(
    "tool",
    [
        "knowledge_record_claim",
        "knowledge_verify_claim",
        "human_needs_add_goal",
        "human_needs_propose_opportunity",
        "human_needs_record_outcome",
    ],
)
def test_untrusted_callers_cannot_write_epistemic_or_human_needs_stores(tmp_path: Path, tool: str):
    decision = PolicyKernel().evaluate(
        ProposedAction(tool_name=tool, arguments={}, actor="mcp:external"),
        dry_run=True,
    )
    assert decision.decision == AuthorityDecisionType.DENY
    assert decision.policy_name == "memory_authority"


def test_verify_gate_recognizes_truth_management_and_patch_tools():
    from jaeger_agent.loop.verify_gate import verify_final

    assert verify_final(
        "I have deleted the disposable session and added your goal.",
        tool_successes=["apply_patch", "exec_command", "session_manage", "human_needs_add_goal", "knowledge_record_claim"],
        tool_names=["apply_patch", "exec_command", "session_manage", "human_needs_add_goal", "knowledge_record_claim"],
        user_prompt="Fix the file, record a claim, add a goal, and delete the session.",
    ) is None
