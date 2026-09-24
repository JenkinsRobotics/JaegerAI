"""Autonomous worker loop — keep going until complete_task, not prose."""

from __future__ import annotations

import pytest

from jaeger_ai.core.runtime import execution, work_ledger
from jaeger_ai.core.runtime.autonomous_runner import (
    ACCEPTANCE_GUIDANCE,
    HARNESS_PREFIX,
    ensure_autonomous_ledger,
    is_actionable_request,
    looks_like_batch,
    next_continuation_prompt,
    run_worker_goal,
    should_run_autonomous,
)
from jaeger_ai.core.runtime.work_ledger import (
    complete_task,
    work_ledger as ledger_tool,
)


@pytest.fixture(autouse=True)
def _clean():
    execution.reset()
    work_ledger.reset()
    yield
    execution.reset()
    work_ledger.reset()


def test_continuation_cannot_create_a_task_from_system_nudge():
    from jaeger_ai.core.runtime.continuation import continuation_prompt
    assert ensure_autonomous_ledger(continuation_prompt()) is None


def test_prepared_continuation_keeps_original_objective_and_skips_skill_routing(monkeypatch):
    from types import SimpleNamespace
    from jaeger_ai.features.dispatcher import router
    from jaeger_ai.core.runtime.continuation import continuation_prompt
    monkeypatch.setattr(router, "compact_agent", lambda agent: None)
    agent = SimpleNamespace(messages=[], system_prompt="", context_guard=None)
    original = "Repair the Web UI chats and verify each framework."
    router.prepare_turn_text(agent, original, domain=False)
    prepared = router.prepare_turn_text(agent, continuation_prompt(), domain=False)
    assert original in prepared
    assert agent._skill_route_query == ""
    assert work_ledger.active_ledger() is None


def test_skill_router_consumes_only_original_request(monkeypatch):
    from types import SimpleNamespace
    from jaeger_agent.loop.jaeger_agent import JaegerAgent
    from jaeger_agent.skill_registry import playbook_skills, toolset_scoping
    seen = []
    monkeypatch.setattr(toolset_scoping, "is_untrusted_content", lambda: False)
    monkeypatch.setattr(playbook_skills, "match_playbook",
                        lambda query, **kwargs: (seen.append(query) or (None, 0, "test")))
    monkeypatch.setenv("JAEGER_AUTO_SKILLS", "1")
    agent = SimpleNamespace(_skill_route_query="Repair chat routing", _all_tools=[])
    prepared = "[Work ledger] kanban\nRepair chat routing"
    assert JaegerAgent._auto_route_skill(agent, prepared) == prepared
    assert seen == ["Repair chat routing"]
    agent._skill_route_query = ""
    JaegerAgent._auto_route_skill(agent, "[Autonomous Harness] kanban")
    assert seen == ["Repair chat routing"]


def test_batch_phrasing_is_detected():
    positives = [
        "process all 50 items and do not stop until done",
        "consolidate every 20 notes",
        "process these 300 notes",
        "do not stop until done",
        "keep going until every file is finished",
        "batch-process the export",
        "/goal finish the notes",
        "go through all 14 folders",
        "sync my Safari and Chrome bookmarks with no duplicates",
        "audit and restructure the bookmarks into folders",
    ]
    for text in positives:
        assert looks_like_batch(text), text
    assert should_run_autonomous("process these 300 notes")


def test_batch_phrasing_rejects_casual_chat():
    """A false positive costs a 100-step loop. Extend this list before
    widening the regex."""
    negatives = [
        "what's the capital of France?",
        "I have 20 items in my backpack",
        "the 2020 notes from that trip",
        "remind me in 20 minutes",
        "keep going, I like this conversation",
        "wait until dinner is ready",
        "process all the logs in that folder quickly",
        "batch of cookies recipe",
        "every 20 seconds ping the host",
        "finish this sentence for me",
        "handle the exception in main.py",
        "go through the options with me",
        "audit this function",
        "sync the clock",
    ]
    for text in negatives:
        assert not looks_like_batch(text), text


def test_actionable_classifier_keeps_chat_lightweight():
    assert not is_actionable_request("What is the capital of Egypt?")
    assert not is_actionable_request("Explain this function.")
    assert is_actionable_request("Create calculator.py and verify it exists.")
    assert is_actionable_request("Use Codex to modify the repository and run tests.")


def test_controller_step_cannot_spawn_nested_top_level_controller(monkeypatch):
    import jaeger_ai.main as main
    token = main._actionable_controller_depth.set(1)
    try:
        assert main._run_actionable_turn(
            object(), "Run pytest and fix failures", session_key="test",
            allow_persona=False,
        ) is None
    finally:
        main._actionable_controller_depth.reset(token)


@pytest.mark.parametrize("media", [
    [{"type": "image_url", "image_url": {"url": "data:image/png;base64,test"}}],
    "Use write_file to create workspace/report.txt containing READY; read it back.",
])
def test_actionable_multimodal_request_keeps_media_and_output_policy(monkeypatch, media):
    """The completion controller must not drop a camera input or voice policy."""
    import jaeger_ai.main as main
    from jaeger_ai.core.runtime import agent_controller

    calls = []

    def run(client, prompt, **kwargs):
        calls.append((prompt, kwargs))
        assert main._actionable_controller_depth.get() == 1
        return {"text": "done", "error": None}

    class Controller:
        def __init__(self, client, *, turn_fn, **kwargs):
            self.turn = turn_fn

        def run_to_completion(self, text, session, **kwargs):
            self.turn(None, "Inspect the supplied diagram", session_key=session)
            result = self.turn(None, "Verify the summary", session_key=session)
            return {"status": "COMPLETED", "reason": "verified", "output": result}

    monkeypatch.setattr(agent_controller, "JaegerAgentController", Controller)
    monkeypatch.setattr(main, "_run_turn_via_jaeger_agent", run)
    result = main._run_turn(
        None, "Create a summary document from this diagram and verify it exists.",
        session_key="media-task", allow_persona=False, content=media,
        system_prompt_addon="Use spoken output.",
    )
    assert result["actionable"] and result["controller_state"] == "COMPLETED"
    expected = (media + [{"type": "text", "text": "Inspect the supplied diagram"}]
                if isinstance(media, list) else f"{media}\n\nInspect the supplied diagram")
    assert calls[0][1]["content"] == expected
    assert "content" not in calls[1][1]
    assert all(kwargs["system_prompt_addon"] == "Use spoken output."
               for _, kwargs in calls)
    if isinstance(media, list):
        assert len(media) == 1
    assert main._actionable_controller_depth.get() == 0


def test_durable_request_opens_counted_ledger_automatically():
    ledger = ensure_autonomous_ledger("process these 436 records")
    assert ledger is not None
    assert ledger.total() == 436
    assert ledger.remaining() == 436


def test_uncounted_durable_request_uses_acceptance_phases():
    ledger = ensure_autonomous_ledger(
        "sync my Safari and Chrome bookmarks with no duplicates"
    )
    assert ledger is not None
    assert ledger.remaining_ids == ["inspect", "execute", "verify"]
    assert ledger.remaining() == 3
    assert "prose claim" in ACCEPTANCE_GUIDANCE


def test_single_reply_does_not_inherit_or_destroy_unfinished_work():
    from jaeger_ai.features.dispatcher.router import prepare_turn_text
    from jaeger_ai.core.runtime.agent_controller import JaegerAgentController
    existing = ensure_autonomous_ledger("process these 436 records")
    class Agent:
        messages = []
        system_prompt = ""
        context_guard = None
    prompt = "Reply exactly AUDIT-PONG. Do not use tools."
    assert ensure_autonomous_ledger(prompt) is None
    assert not should_run_autonomous(prompt)
    prepared = prepare_turn_text(Agent(), prompt, session_key="dispatcher")
    assert prepared == prompt
    calls = []
    def turn(client, text, **kwargs):
        calls.append(text)
        return {"text": "AUDIT-PONG", "tool_activity": []}
    result = JaegerAgentController(None, turn_fn=turn, max_steps=4).run_to_completion(prompt, "dispatcher")
    assert len(calls) == 1
    assert existing.remaining() == 436
    assert not existing.completed
    assert result["output"]["steps"] == 1


def test_inner_cap_forces_continuation_on_settled_prose():
    """Wind-down summaries look finished. The fuse is not a job end."""
    nxt = next_continuation_prompt(
        "Here is a summary of the first batch.",
        isolated=True,
        halt_reason="hit max_iterations=24 without a final answer",
        steps_left=5,
        objective="process notes",
    )
    assert nxt is not None
    assert next_continuation_prompt(
        "Here is a summary of the first batch.",
        isolated=True,
        steps_left=5,
    ) is None


@pytest.mark.parametrize("halt", [
    "made 24 tool calls in a single turn",
    "hit max_iterations=24 without a final answer",
])
def test_recoverable_halt_forces_outer_continuation(halt):
    nxt = next_continuation_prompt(
        "Here is the progress so far.", isolated=True,
        halt_reason=halt, steps_left=5, objective="finish the audit",
    )
    assert nxt is not None
    assert "finish the audit" in nxt


def test_short_worker_task_exits_after_one_settled_turn():
    calls: list[str] = []

    def _turn(client, text, *, session_key, allow_persona=True):
        calls.append(text)
        return {
            "text": "The capital of France is Paris.",
            "error": None, "tool_activity": [],
        }

    out = run_worker_goal(
        object(), "what's the capital of France?", turn_fn=_turn, max_steps=10,
    )
    assert len(calls) == 1
    assert out["halt_reason"] == "settled"
    assert out["steps"] == 1


def test_worker_loops_fifty_items_without_a_reprompt():
    """The original batch acceptance case: 50 items, no user in the loop."""
    total = 50
    batch = 10

    def _turn(client, text, *, session_key, allow_persona=True):
        current = work_ledger.active_ledger()
        if current is None:
            ledger_tool(
                action="create", task_name="fifty", total_items=total,
                remaining_count=total,
            )
            current = work_ledger.active_ledger()
        done = list(current.completed_ids)
        nxt = [str(i) for i in range(len(done), min(len(done) + batch, total))]
        done.extend(nxt)
        leftover = total - len(done)
        ledger_tool(
            action="update",
            completed_ids=done,
            remaining_count=leftover,
            in_progress_ids=[],
        )
        if leftover == 0:
            complete_task(
                task_id=current.task_id,
                summary=f"processed {total} items",
                evidence="ids 0-49 on disk",
            )
            return {
                "text": "all done",
                "error": None,
                "tool_activity": ["  ▸ complete_task(evidence='ids 0-49')"],
            }
        return {
            "text": f"processed {len(done)}/{total}",
            "error": None,
            "tool_activity": ["  ▸ work_ledger(action='update')"],
        }

    out = run_worker_goal(
        object(),
        "process all 50 items. do not stop until done.",
        turn_fn=_turn,
        max_steps=20,
    )
    assert out["halt_reason"] == "complete_task"
    assert out["steps"] == 5  # 10 items per turn × 5
    assert out["summary"] == "processed 50 items"
    assert out["text"] == "processed 50 items"
    assert work_ledger.active_ledger().completed is True


def test_isolated_worker_does_not_flip_main_execution_mode():
    assert execution.current_mode() == "interactive"

    def _turn(client, text, *, session_key, allow_persona=True):
        return {"text": "ok", "error": None, "tool_activity": []}

    run_worker_goal(object(), "hello", turn_fn=_turn, max_steps=3)
    assert execution.current_mode() == "interactive"
    assert execution.run_active() is False


def test_question_stops_the_worker():
    def _turn(client, text, *, session_key, allow_persona=True):
        return {
            "text": "Which folder should I start with?",
            "error": None, "tool_activity": [],
        }

    out = run_worker_goal(
        object(), "process all 20 items", turn_fn=_turn, max_steps=10,
    )
    assert out["halt_reason"] == "settled" or out["steps"] == 1
    assert out["steps"] == 1


def test_harness_prompt_carries_progress():
    ledger_tool(action="create", task_name="x", total_items=8)
    ledger_tool(action="update", completed_ids=["1", "2"], remaining_count=6)
    from jaeger_ai.core.runtime.autonomous_runner import harness_prompt
    prompt = harness_prompt()
    assert HARNESS_PREFIX in prompt
    assert "2/8" in prompt


@pytest.mark.parametrize('halt', ['empty_response', 'thinking_exhausted', 'context_overflow', 'interrupted'])
def test_terminal_native_failure_cannot_restart_through_open_ledger(halt):
    assert next_continuation_prompt('', force_ledger=True, halt_reason=halt, steps_left=10) is None
    assert next_continuation_prompt('', isolated=True, batch=True, halt_reason=halt, steps_left=10) is None
