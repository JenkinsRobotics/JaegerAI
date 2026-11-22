"""Autonomous worker loop — keep going until complete_task, not prose."""

from __future__ import annotations

import pytest

from jaeger_ai.core.runtime import execution, work_ledger
from jaeger_ai.core.runtime.autonomous_runner import (
    ACCEPTANCE_GUIDANCE,
    HARNESS_PREFIX,
    ensure_autonomous_ledger,
    looks_like_batch,
    next_continuation_prompt,
    run_continued_turn,
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


def test_only_explicit_goal_phrasing_is_durable():
    assert looks_like_batch("/goal finish the notes")
    assert not looks_like_batch("process all 50 items and do not stop until done")
    assert not should_run_autonomous("process these 300 notes")
    assert should_run_autonomous("/goal process these 300 notes")


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
@pytest.mark.usefixtures("legacy_local_runtime")      # exercises the isolated in-process turn
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
    result = main._run_actionable_turn(
        None, "/goal Create a summary document from this diagram and verify it exists.",
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
    ledger = ensure_autonomous_ledger("/goal process these 436 records")
    assert ledger is not None
    assert ledger.total() == 436
    assert ledger.remaining() == 436


def test_uncounted_durable_request_uses_acceptance_phases():
    ledger = ensure_autonomous_ledger(
        "/goal sync my Safari and Chrome bookmarks with no duplicates"
    )
    assert ledger is not None
    assert ledger.remaining_ids == ["inspect", "execute", "verify"]
    assert ledger.remaining() == 3
    assert "prose claim" in ACCEPTANCE_GUIDANCE


def test_single_reply_does_not_inherit_or_destroy_unfinished_work():
    from jaeger_ai.features.dispatcher.router import prepare_turn_text
    from jaeger_ai.core.runtime.agent_controller import JaegerAgentController
    existing = ensure_autonomous_ledger("/goal process these 436 records")
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
    assert out["halt_reason"] is None
    assert out["controller_reason"] == "settled"
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
    assert out["halt_reason"] is None
    assert out["controller_reason"] == "complete_task"
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
    assert out["controller_reason"] == "question"
    assert out["halt_reason"] == "question"  # stopped short, not completed
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


def test_recalled_background_does_not_make_a_question_actionable(monkeypatch):
    """Intent comes from the operator's words, not the enriched prompt.

    Live regression (WebUI, 2026-09-22): "Use a tool to check the current
    date and time" answered correctly, then failed ``awaiting_approval:
    blocked`` because recalled history above it contained "run"/"fix" and
    the classifier promoted the whole prompt to a ledgered task.
    """
    import jaeger_ai.main as main
    from jaeger_ai.core.entity.cognition_router import with_background

    request = "Use a tool to check the current date and time, then tell me."
    enriched = with_background(
        request, {"durable_recall": "user: run the tests and fix the bug"}
    )
    assert main._run_actionable_turn(
        object(), enriched, session_key="test", allow_persona=False,
        request=request,
    ) is None
    assert work_ledger.active_ledger() is None


def test_prepare_turn_text_routes_on_the_request_not_the_background():
    """Skill routing and the ledger read the operator's words.

    Live capture (2026-09-22): routing on the enriched prompt picked an
    11 KB "Box" playbook and opened a ledger named "<background> …" for
    "My favorite color is teal".
    """
    from jaeger_ai.core.entity.cognition_router import with_background
    from jaeger_ai.features.dispatcher import router

    class Agent:
        messages: list = []

    request = "My favorite color is teal. Just acknowledge."
    enriched = with_background(
        request, {"durable_recall": "user: run the tests and fix the bug"}
    )
    agent = Agent()
    prepared = router.prepare_turn_text(
        agent, enriched, session_key="webui-x", domain=False, request=request,
    )
    assert agent._skill_route_query == request
    assert agent._task_objective == request
    assert work_ledger.active_ledger() is None
    assert ACCEPTANCE_GUIDANCE not in prepared
    assert prepared.endswith(enriched)


STALL = "Let me start by reading the notes and I'll process everything."


def test_run_continued_turn_refires_a_stall_without_concatenating_checkpoints():
    prompts: list[str] = []

    def turn(text):
        prompts.append(text)
        if "SYSTEM NUDGE" in text:
            return {"text": "All 14 folders processed.", "halt_reason": None}
        return {"text": STALL, "halt_reason": None}

    result = run_continued_turn(turn, "process every folder", max_steps=4)
    assert len(prompts) == 2
    assert prompts[0] == "process every folder"
    assert "SYSTEM NUDGE" in prompts[1]
    assert result["continuation_steps"] == 1
    assert result["text"] == "All 14 folders processed."
    assert result["checkpoints"][0]["text"] == STALL


def test_run_continued_turn_does_not_refire_an_interrupt():
    prompts: list[str] = []

    def turn(text):
        prompts.append(text)
        return {"text": STALL, "halt_reason": "interrupted"}

    result = run_continued_turn(turn, "process every folder", max_steps=4)
    assert prompts == ["process every folder"]
    assert result["halt_reason"] == "interrupted"
    assert result["continuation_steps"] == 0


def test_run_continued_turn_inner_cap_refires_settled_prose():
    prompts: list[str] = []

    def turn(text):
        prompts.append(text)
        if len(prompts) == 1:
            return {"text": "Here is a summary of the first batch.",
                    "halt_reason": "hit max_iterations=24 without a final answer"}
        return {"text": "The capital of France is Paris.", "halt_reason": None}

    result = run_continued_turn(turn, "process notes", max_steps=4)
    assert len(prompts) == 2
    assert result["continuation_steps"] == 1


def test_run_continued_turn_honours_cancel_between_steps(monkeypatch):
    cancelled = False
    prompts: list[str] = []

    def turn(text):
        nonlocal cancelled
        prompts.append(text)
        cancelled = True
        return {"text": STALL, "halt_reason": None}

    result = run_continued_turn(
        turn, "process every folder", max_steps=4, is_cancelled=lambda: cancelled,
    )
    assert prompts == ["process every folder"]
    assert result["halt_reason"] == "interrupted"
    assert result["continuation_steps"] == 0


def test_run_continued_turn_kill_switch_stops_stall_refire(monkeypatch):
    monkeypatch.setenv("JAEGER_AUTO_CONTINUE", "0")
    prompts: list[str] = []

    def turn(text):
        prompts.append(text)
        return {"text": STALL, "halt_reason": None}

    result = run_continued_turn(turn, "process every folder", max_steps=4)
    assert prompts == ["process every folder"]
    assert result["continuation_steps"] == 0


def test_requests_never_reuse_a_previous_continuation_objective():
    for objective in ('AUDIT_ALPHA', 'AUDIT_BETA'):
        prompts = []
        def turn(prompt):
            prompts.append(prompt)
            return {'text': 'More work remains.' if len(prompts) == 1 else 'Finished.',
                    'halt_reason': 'made 8 tool calls in a single turn' if len(prompts) == 1 else None}
        run_continued_turn(turn, objective, max_steps=2)
        assert len(prompts) == 2
        assert objective in prompts[1]
        assert ('AUDIT_BETA' if objective == 'AUDIT_ALPHA' else 'AUDIT_ALPHA') not in prompts[1]
        assert not execution.run_active()


def test_concurrent_request_objectives_and_stops_are_isolated():
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    barrier = Barrier(2)
    def run(name):
        prompts = []
        def turn(prompt):
            prompts.append(prompt)
            if len(prompts) == 1:
                if name == 'STOP_THIS':
                    execution.request_stop('test cancellation')
                barrier.wait(timeout=5)
                assert execution.run_progress()['objective'] == name
                assert execution.stop_requested() == (name == 'STOP_THIS')
                return {'text': 'More work remains.', 'halt_reason': 'made 8 tool calls in a single turn'}
            assert name in prompt and 'STOP_THIS' not in prompt
            return {'text': 'Finished.'}
        result = run_continued_turn(turn, name, max_steps=2)
        return len(prompts), result
    with ThreadPoolExecutor(2) as pool:
        stopped = pool.submit(run, 'STOP_THIS')
        continued = pool.submit(run, 'KEEP_THIS')
        assert stopped.result()[0] == 1
        assert continued.result()[0] == 2
    assert not execution.run_active() and not execution.stop_requested()


def test_request_scope_is_restored_after_exception():
    execution.begin_run('outer interactive objective')
    def fail(_):
        execution.request_stop('inner')
        raise RuntimeError('provider failed')
    with pytest.raises(RuntimeError, match='provider failed'):
        run_continued_turn(fail, 'inner request')
    assert execution.run_progress()['objective'] == 'outer interactive objective'
    assert execution.run_active() and not execution.stop_requested()


def test_exhausted_continuation_is_failed_with_partial_output():
    result = run_continued_turn(lambda p: {'text': 'partial work', 'halt_reason': 'max_iterations'},
                                'finish this task', max_steps=1)
    assert result['status'] == 'failed'
    assert result['halt_reason'] == 'continuation_budget_exhausted'
    assert result['text'] == 'partial work'
    assert result['error'] and result['continuation_steps'] == 1


def test_durable_budget_exhaustion_yields_for_existing_owner():
    result = run_continued_turn(lambda p: {'text': 'partial work', 'halt_reason': 'max_iterations'},
                                'finish this task', max_steps=1, durable=True)
    assert result['halt_reason'] == 'yielded'
    assert not result.get('error')


@pytest.mark.parametrize('name', ['brief.docx', 'slides.pptx', 'meeting.ics', 'art.png', 'clip.mp4'])
def test_multimodal_deliverables_are_checked_in_current_project(tmp_path, name):
    from jaeger_agent.core.workspace import project_scope
    from jaeger_ai.core.runtime.autonomous_runner import missing_deliverable_paths
    with project_scope(tmp_path):
        assert missing_deliverable_paths(f'Deliver {name}.') == [name]
        (tmp_path / name).write_bytes(b'fixture')
        assert missing_deliverable_paths(f'Deliver {name}.') == []


def test_blocked_explanation_at_inner_cap_is_not_success():
    result = run_continued_turn(lambda p: {'text': 'I cannot read the image; work remains incomplete.',
                                          'halt_reason': 'made 8 tool calls in a single turn'},
                                'Inspect the image and save observations.json', max_steps=10)
    assert result['status'] == 'failed' and result['error']
    assert result['continuation_steps'] == 0


def test_unverified_progress_at_tool_cap_continues_to_actual_tests():
    calls = []
    def turn(prompt):
        calls.append(prompt)
        return ({'text': 'The fix is written. I cannot yet claim the suite is green. What remains undone: running tests.',
                 'halt_reason': 'made 8 tool calls in a single turn'} if len(calls)==1 else
                {'text': 'All tests passed and the work is complete.'})
    result = run_continued_turn(turn, 'Repair the module and run the tests', max_steps=2)
    assert len(calls) == 2 and not result.get('error')
    assert 'Repair the module' in calls[1]


def test_unverified_claim_does_not_override_real_blocker():
    from jaeger_ai.core.runtime.continuation import classify
    assert classify('I cannot yet claim success because I cannot access the required provider.') == 'blocked'


def test_remaining_observations_at_tool_cap_continue_but_access_blockers_stop():
    calls = []
    def turn(prompt):
        calls.append(prompt)
        return ({'text': 'I cannot yet identify all scenes. The remaining frames need inspection.',
                 'halt_reason': 'made 8 tool calls in a single turn'} if len(calls) == 1 else
                {'text': 'The analysis is complete.'})
    assert not run_continued_turn(turn, 'Inspect the video', max_steps=2).get('error')
    assert len(calls) == 2
    from jaeger_ai.core.runtime.continuation import classify
    assert classify('I cannot yet identify the remaining scenes because permission denied.',
                    at_inner_cap=True) == 'blocked'
    assert classify('I cannot yet identify the remaining scenes.') == 'blocked'


@pytest.mark.parametrize('durable', [False, True])
def test_budget_failure_detaches_ledger_but_durable_yield_preserves_it(durable):
    ledger_tool(action='create', task_name='unfinished audit', total_items=8)
    ledger = work_ledger.active_ledger()
    result = run_continued_turn(lambda _: {'text': 'More remains.', 'halt_reason': 'max_iterations'},
                                'Finish audit', max_steps=1, durable=durable)
    if durable:
        assert result['halt_reason'] == 'yielded'
        assert work_ledger.active_ledger() is ledger
    else:
        assert result['status'] == 'failed'
        assert work_ledger.active_ledger() is None
        assert work_ledger.get_ledger(ledger.task_id) is not None


def test_provider_error_at_durable_budget_is_not_a_resumable_yield():
    calls = []
    def turn(prompt):
        calls.append(prompt)
        return ({'text': 'More remains.', 'halt_reason': 'max_iterations'} if len(calls) == 1 else
                {'text': '', 'error': 'Provider access denied', 'halt_reason': 'provider_error'})
    result = run_continued_turn(turn, 'Finish audit', max_steps=1, durable=True)
    assert result['error'] == 'Provider access denied'
    assert result['halt_reason'] == 'provider_error'
