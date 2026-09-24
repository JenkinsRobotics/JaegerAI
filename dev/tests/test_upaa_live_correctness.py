"""Regression tests for live-validated UPAA correctness defects."""

from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from jaeger_ai.core.entity.events import EventType, JaegerEvent
from jaeger_ai.core.entity.executive import (
    CognitiveStrategy,
    ExecutiveStrategySelector,
    score_task_complexity,
)
from jaeger_ai.core.entity.identity import EntityIdentity
from jaeger_ai.core.entity.runtime import EntityRuntime
from jaeger_ai.core.entity.self_state import SelfState
from jaeger_ai.core.entity.verification import (
    VerificationRegistry,
    VerificationStatus,
    derive_verification_action,
)


@pytest.fixture
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("JAEGER_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("JAEGER_INSTANCE_NAME", "pinocchio-val")
    EntityRuntime.reset_singleton()
    yield tmp_path
    EntityRuntime.reset_singleton()


def test_direct_response_exposes_zero_tools():
    """P0-A: build_jaeger_agent(tools=[]) must not advertise a tool schema."""
    from jaeger_agent.loop.jaeger_agent import JaegerAgent
    from jaeger_agent.adapters.base import ProviderAdapter
    from jaeger_agent.schemas.message_types import Message
    import threading

    class FakeAdapter(ProviderAdapter):
        name = "fake"
        seen_tools: list = []

        def format_messages(self, messages, tools, system):
            type(self).seen_tools = list(tools or [])
            return {"messages": messages, "tools": tools}

        def call(self, formatted, interrupt_event, **kwargs):
            return {"text": "153"}

        def parse_response(self, raw):
            return Message(role="assistant", content=str(raw.get("text") or ""))

        def supports(self, feature: str) -> bool:
            return False

    FakeAdapter.seen_tools = ["sentinel"]
    agent = JaegerAgent(FakeAdapter(), tools=[])
    assert agent.tools == []
    agent.run_turn("What is 17 multiplied by 9?")
    assert FakeAdapter.seen_tools == []


def test_remember_routes_to_react():
    state = SelfState(identity=EntityIdentity.create_default("t"))
    dec = ExecutiveStrategySelector.select_strategy(
        JaegerEvent.human_message("Remember that the validation project codename is Blue Lantern."),
        state,
    )
    assert dec.strategy == CognitiveStrategy.REACT_LOOP


def test_complexity_score_selects_deliberate():
    text = (
        "Plan a safe migration of this dataset from schema v1 to v2. "
        "Compare multiple approaches, choose one, execute it in a sandbox, verify it."
    )
    scored = score_task_complexity(text)
    assert scored["compare_plans"] is True
    assert scored["score"] >= 0.35
    state = SelfState(identity=EntityIdentity.create_default("t"))
    dec = ExecutiveStrategySelector.select_strategy(JaegerEvent.human_message(text), state)
    assert dec.strategy == CognitiveStrategy.DELIBERATE_PLANNING


def test_derive_file_write_from_terminal_and_disk(tmp_path: Path):
    target = tmp_path / "sandbox" / "pinocchio.txt"
    target.parent.mkdir(parents=True)
    target.write_text("Pinocchio validation", encoding="utf-8")
    evt = JaegerEvent.tool_completed(
        "terminal",
        {"ok": True, "stdout": "Pinocchio validation"},
        call_id="c1",
        duration_s=0.1,
    )
    # inject arguments onto payload via a custom event
    evt = JaegerEvent(
        event_id="t1",
        event_type=EventType.TOOL_COMPLETED.value,
        actor="agent:jaeger",
        source="runtime.tool_executor",
        timestamp=1.0,
        payload={
            "tool": "terminal",
            "arguments": {
                "command": f"printf 'Pinocchio validation' > {target}"
            },
            "result": {"ok": True},
        },
    )
    action = derive_verification_action(
        f"Create a text file at {target} containing exactly the words Pinocchio validation",
        {},
        [evt],
        strategy="react_loop",
        context={"workspace": str(tmp_path)},
    )
    assert action["action_type"] == "file_write"
    registry = VerificationRegistry()
    ver = registry.verify(
        f"Create a text file at {target} containing Pinocchio validation",
        action,
        {},
        context={"workspace": str(tmp_path)},
    )
    assert ver.status == VerificationStatus.OBJECTIVE_VERIFIED, ver.evidence


def test_derive_file_delete(tmp_path: Path):
    gone = tmp_path / "gone.txt"
    evt = JaegerEvent(
        event_id="t2",
        event_type=EventType.TOOL_COMPLETED.value,
        actor="a",
        source="s",
        timestamp=1.0,
        payload={"tool": "terminal", "arguments": {"command": f"rm {gone}"}, "result": {"ok": True}},
    )
    action = derive_verification_action(
        f"Delete the file {gone}",
        {},
        [evt],
        strategy="react_loop",
    )
    assert action["action_type"] == "file_delete"
    ver = VerificationRegistry().verify(f"Delete {gone}", action, {})
    assert ver.status == VerificationStatus.OBJECTIVE_VERIFIED, ver.evidence


def test_derive_git_commit(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    (repo / "data.txt").write_text("v2", encoding="utf-8")
    subprocess.run(["git", "add", "data.txt"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.email=v@t", "-c", "user.name=V", "commit", "-m", "pinocchio-git-validation"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    evt = JaegerEvent(
        event_id="t3",
        event_type=EventType.TOOL_COMPLETED.value,
        actor="a",
        source="s",
        timestamp=1.0,
        payload={
            "tool": "terminal",
            "arguments": {
                "command": f'git -C {repo} commit -m "pinocchio-git-validation"'
            },
            "result": {"ok": True},
        },
    )
    action = derive_verification_action(
        f"make a git commit with message pinocchio-git-validation in {repo}",
        {},
        [evt],
        strategy="react_loop",
    )
    assert action["action_type"] == "git_commit"
    ver = VerificationRegistry().verify("git commit", action, {})
    assert ver.status == VerificationStatus.OBJECTIVE_VERIFIED, ver.evidence


def test_single_agent_response_event(isolated: Path):
    runtime = EntityRuntime(state_root=isolated)

    def runner(text, session_key="cli"):
        return {"text": "153.", "tool_activity": []}

    runtime.execute_turn(
        "What is 17 multiplied by 9? Do not use tools.",
        session_id="cli",
        context={"model_runner": lambda t: "153.", "react_runner": runner},
    )
    responses = [
        e for e in runtime.event_store.query_events()
        if e.event_type == EventType.AGENT_RESPONSE.value
    ]
    assert len(responses) == 1, [e.source for e in responses]


def test_execute_turn_verifies_write_from_tool_events(isolated: Path):
    runtime = EntityRuntime(state_root=isolated)
    target = isolated / "out.txt"

    def react(text, session_key="cli"):
        runtime.record_tool_result(
            "write_file",
            {"written": True, "path": str(target)},
            call_id="c-write",
            duration_s=0.01,
        )
        # arguments live on tool.started; also emit a completed with args
        runtime.event_store.append(
            JaegerEvent(
                event_id="w1",
                event_type=EventType.TOOL_COMPLETED.value,
                actor="agent:jaeger",
                source="runtime.tool_executor",
                timestamp=runtime.current_state.last_event_timestamp + 0.001,
                payload={
                    "tool": "write_file",
                    "arguments": {"path": str(target), "content": "hello"},
                    "result": {"ok": True, "path": str(target)},
                },
            )
        )
        target.write_text("hello", encoding="utf-8")
        return {"text": "wrote it", "tool_activity": ["write_file"]}

    runtime.execute_turn(
        f"Write a file at {target} containing hello",
        session_id="cli",
        context={"react_runner": react},
    )
    ver = [
        e for e in runtime.event_store.query_events(event_type=EventType.VERIFICATION_COMPLETED.value)
        if True
    ]
    assert ver
    assert ver[-1].payload.get("status") == "objective_verified", ver[-1].payload


def test_formulate_extracts_tool_from_objective_text():
    from jaeger_ai.core.entity.reflection import formulate_reflection_from_failure
    from jaeger_ai.core.entity.verification import VerificationResult, VerificationStatus

    event = JaegerEvent.human_message(
        "Use the read_file tool to open /tmp/missing-round3.txt"
    )
    ver = VerificationResult(
        status=VerificationStatus.OBJECTIVE_FAILED,
        target_objective="Use the read_file tool to open /tmp/missing-round3.txt",
        evidence="Tool failure (read_file): not found",
        verifier="tool_failure_override",
        error="not found",
    )
    refl = formulate_reflection_from_failure(event, ver)
    assert "read_file" in refl.applicability_conditions
    assert "filesystem" in refl.applicability_conditions
    assert refl.supporting_episode_ids
    assert refl.hypothesis


def test_get_relevant_reflections_alias(isolated: Path):
    from jaeger_ai.core.entity.reflection import StructuredReflection

    runtime = EntityRuntime(state_root=isolated)
    runtime.reflexion_store.add_reflection(
        StructuredReflection(
            reflection_id="refl-alias",
            hypothesis="read_file missing path must be checked first",
            confidence=0.8,
            failure_conditions="read_file:not found",
            applicability_conditions=["read_file", "filesystem"],
            supporting_episode_ids=["msg-1"],
        )
    )
    via_alias = runtime.reflexion_store.get_relevant_reflections(
        "Use the read_file tool to open another missing file"
    )
    via_retrieve = runtime.reflexion_store.retrieve_applicable(
        "Use the read_file tool to open another missing file"
    )
    assert via_alias
    assert [r.reflection_id for r in via_alias] == [r.reflection_id for r in via_retrieve]


def test_skill_pipeline_reloads_from_disk_and_skill_used(isolated: Path):
    from jaeger_ai.core.entity.skills.promotion import SkillPromotionPipeline

    skills_dir = isolated / "skills"
    pipeline = SkillPromotionPipeline(skills_dir=skills_dir)
    cand = pipeline.extract_candidate(
        name="learned_write_file",
        description="Repeated successful write_file procedure observed 3 times",
        code="# verified write_file playbook\n",
    )
    ver = pipeline.verify_candidate(cand, lambda code: "playbook" in code)
    assert pipeline.promote(cand, ver)

    restarted = SkillPromotionPipeline(skills_dir=skills_dir)
    assert "learned_write_file" in restarted.list_promoted_skills()
    assert restarted.get_skill("learned_write_file") is not None
    matched = restarted.matching_skills("Write a file at sandbox/orpheus.txt containing ok")
    assert matched and matched[0]["name"] == "learned_write_file"

    runtime = EntityRuntime(state_root=isolated)
    runtime.sleep_time_processor.skill_pipeline = restarted

    def react(text, session_key="cli"):
        assert "learned_write_file" in text
        return {"text": "wrote via learned skill", "tool_activity": []}

    runtime.execute_turn(
        "Write a file at sandbox/orpheus.txt containing ok",
        session_id="cli",
        context={"react_runner": react},
    )
    used = [
        e
        for e in runtime.event_store.query_events()
        if e.event_type == EventType.SKILL_USED.value
    ]
    assert used
    assert used[-1].payload.get("skill_name") == "learned_write_file"


def test_reflection_enters_react_prompt(isolated: Path):
    from jaeger_ai.core.entity.reflection import StructuredReflection

    runtime = EntityRuntime(state_root=isolated)
    runtime.reflexion_store.add_reflection(
        StructuredReflection(
            reflection_id="refl-react",
            hypothesis="read_file failed because the path was missing; verify existence first",
            confidence=0.8,
            failure_conditions="read_file:not found",
            applicability_conditions=["read_file", "filesystem", "not_found"],
            supporting_episode_ids=["msg-fail"],
        )
    )
    seen = {}

    def react(text, session_key="cli"):
        seen["text"] = text
        return {"text": "will list directory first", "tool_activity": []}

    runtime.execute_turn(
        "Use the read_file tool to open /tmp/another-missing-round3.txt",
        session_id="cli",
        context={"react_runner": react},
    )
    retrieved = [
        e
        for e in runtime.event_store.query_events()
        if e.event_type == EventType.REFLECTION_RETRIEVED.value
    ]
    assert retrieved
    assert "Retrieved Failure Hypotheses" in seen.get("text", "")


def test_direct_response_does_not_use_file_verifier(isolated: Path):
    runtime = EntityRuntime(state_root=isolated)
    runtime.execute_turn(
        "Hello. What are you working on right now?",
        session_id="cli",
        context={"model_runner": lambda t: "Nothing in progress."},
    )
    ver = [
        e for e in runtime.event_store.query_events()
        if e.event_type == EventType.VERIFICATION_COMPLETED.value
    ]
    assert ver
    assert ver[-1].payload.get("status") == "objective_unverified"
    assert ver[-1].payload.get("verifier") != "file_write_verifier"


def test_write_verification_uses_artifact_not_objective_workspace(tmp_path):
    project = tmp_path / 'project'
    project.mkdir()
    artifact = project / 'calculator.py'
    artifact.write_text('return sum(values)')
    action = derive_verification_action(
        f'Implement and write tests in {project}',
        {'tool_records': [{'tool': 'write_file', 'arguments': {'path': str(artifact), 'content': 'return sum(values)'}, 'result': {'path': str(artifact)}}]},
    )
    assert action['path'] == str(artifact)


def test_last_read_does_not_verify_unclassified_mutating_turn():
    objective = "Run code to create a report, then read it"
    action = derive_verification_action(objective, {"tool_records": [
        {"tool": "execute_code", "arguments": {}, "result": {"ok": True}},
        {"tool": "read_file", "arguments": {}, "result": {"ok": True}},
    ]})
    result = VerificationRegistry().verify(objective, action, {"ok": True})
    assert result.status == VerificationStatus.OBJECTIVE_UNVERIFIED
    assert result.verifier != "read_only_verifier"


def test_memory_mutation_is_not_classified_as_read_only():
    action = derive_verification_action("Remember a value", {"tool_records": [
        {"tool": "memory", "arguments": {"operation": "write"}, "result": {"ok": True}},
    ]})
    assert action["action_type"] == "unknown"
