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
    """Run a user-requested background task through the Gateway after this turn ends.
    Include required output file paths when known, for outcome verification. The
    owner preserves workspace, model and authorization; results return to this chat.
    Do not queue the current task again from a background worker.
    """
    return _submit(description, artifact_paths)


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
