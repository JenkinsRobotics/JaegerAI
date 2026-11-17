"""Deep Think is durable Gateway work, not a separate local execution queue."""
from __future__ import annotations
from typing import Any
from jaeger_os.core.tools.tool_registry import register_tool_from_function


def _submit(description: str, artifact_paths: list[str] | None = None) -> dict[str, Any]:
    from jaeger_agent.task_port import current_task_context
    ctx = current_task_context()
    if ctx is None:
        return {'ok': False, 'error': 'No execution-owner task context; submit through the Jaeger Gateway'}
    try:
        return ctx['owner'].submit(description, context=ctx, artifacts=artifact_paths, proposal=True)
    except ValueError as exc:
        return {'ok': False, 'error': str(exc)}


# Requests (lead turns) that already handed their job to a background worker.
# After the hand-off the lead only replies: re-checking, polling or redoing the
# work in the same turn is what made P2 slow and noisy (parity P2 follow-up).
_HANDED_OFF: dict[str, float] = {}
# After the hand-off every tool is refused except ones that only talk to Matthew.
_POST_HANDOFF_ALLOWED = frozenset({'share_file', 'notify', 'send_notification'})


def _request_id() -> str | None:
    from jaeger_agent.task_port import current_task_context
    ctx = current_task_context()
    return str(ctx.get('request_id') or '') or None if isinstance(ctx, dict) else None


def handed_off_this_request() -> bool:
    rid = _request_id()
    return bool(rid and rid in _HANDED_OFF)


def handoff_refusal(tool_name: str) -> dict | None:
    """Refuse redo/poll tools for the rest of a turn that already queued its job."""
    if tool_name in _POST_HANDOFF_ALLOWED:
        return None
    rid = _request_id()
    if not rid or rid not in _HANDED_OFF:
        return None
    return {'ok': False, 'error_type': 'already_handed_off', 'retryable': False,
            'error': ('Refused: this job was handed to a background worker, which will post the result to this chat. '
                      'No more tools this turn and no partial answer. Reply now with exactly one short line, e.g. '
                      '"It\'s running in the background; I\'ll post the result here when it finishes."')}


def propose_deep_think_task(description: str) -> dict[str, Any]:
    """Admit Deep Think work. Explicit user background requests retain their authorization.

    Unsolicited suggestions are proposals. A queued response proves admission,
    not completion; use background_task_status to inspect execution and evidence.
    """
    return _submit(description)


def list_deep_think_queue() -> dict[str, Any]:
    from jaeger_agent.task_port import current_task_context
    ctx = current_task_context()
    if ctx is None:
        return {'ok': False, 'error': 'Read tasks through the Gateway /v1/tasks endpoint'}
    tasks = ctx['owner'].store.list_tasks()
    return {'ok': True, 'tasks': [t.to_dict() for t in tasks],
            'summary': {state: sum(t.state.value == state for t in tasks)
                        for state in {t.state.value for t in tasks}}}


@register_tool_from_function(name='propose_deep_think_task')
def _t_propose_deep_think_task(description: str) -> dict:
    """Queue Deep Think work with the resident Gateway. Explicitly requested work
    starts independently of this chat turn; unsolicited suggestions require approval.
    Never add a second board card or claim that admission means completion.
    """
    return propose_deep_think_task(description)


@register_tool_from_function(name='queue_background_task')
def queue_background_task(description: str, artifact_paths: list[str] | None = None) -> dict:
    """USE THIS when the owner says "in the background", "report back", "let me know
    when it's done", or the work is long: it hands the job to a Gateway worker agent
    that posts the result to this chat (and the phone) when it finishes.
    Run a user-requested background task through the Gateway after this turn ends.
    Include required output file paths when known, for outcome verification. The
    owner preserves workspace, model and authorization; results return to this chat.
    Do not queue the current task again from a background worker.
    """
    result = _submit(description, artifact_paths)
    if isinstance(result, dict) and result.get('ok', True) and not result.get('error'):
        # Grok Bot-style hand-off (parity P2): the worker owns the job now.
        rid = _request_id()
        if rid:
            import time as _time
            _HANDED_OFF[rid] = _time.monotonic()
            for old in [k for k, t in _HANDED_OFF.items() if _time.monotonic() - t > 3600]:
                _HANDED_OFF.pop(old, None)
        result = {**result, 'next': ('Queued once. The worker does the whole job and posts the result here. '
                                     'Call no more tools this turn (they will be refused) and do not guess the answer. '
                                     'Reply now in one short line that it is running in the background and the '
                                     'result will be posted here when it finishes.')}
    return result


@register_tool_from_function(name='list_deep_think_queue', side_effect='read')
def _t_list_deep_think_queue() -> dict:
    """Read canonical Gateway background tasks, their actual status and results."""
    return list_deep_think_queue()


@register_tool_from_function(name='background_task_status', side_effect='read')
def background_task_status(task_id: str) -> dict:
    """Read a durable task's execution state, verification evidence, and output."""
    from jaeger_agent.task_port import current_task_context
    ctx = current_task_context()
    if ctx is None:
        return {'ok': False, 'error': 'No Gateway task context'}
    task = ctx['owner'].store.get_task(task_id)
    return {'ok': task is not None, 'task': task.to_dict() if task else None}
