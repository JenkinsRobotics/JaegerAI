"""Synthetic user messages — the prompts the framework itself sends.

Distinct from the system prompt (rules) and the user's typed prompts:
these are user-role messages the framework injects into the turn
queue when it wants the agent to do something on its own initiative.

Three kinds today:

  * ``AUTO_BOARD_PROMPT``     — fired by the TUI idle-tick when the
    kanban board has actionable work and the user has been quiet
  * ``deep_think_directive``  — built per-task, wraps the queued task
    description into a Deep Think entry message
  * ``CRON_PROMPT_FRAME``     — frames a scheduled prompt so the
    agent knows it came from cron, not a live user (the wrapping
    is optional; ``cron_runner`` can also pass the raw prompt)

Why a separate module: each injection site used to inline its own
string. That made it hard to (a) see the full set, (b) keep the
voice consistent, and (c) test that the synthetic message paired
correctly with the system-prompt rules.
"""

from __future__ import annotations


AUTO_BOARD_PROMPT = (
    "(Idle pickup) You have free time and the kanban board has "
    "actionable work. Use kanban(action='view') to look at the cards, then "
    "pick the highest-priority card from in_progress (resume), "
    "ready, or backlog and work it through: kanban(action='move') it to "
    "in_progress if it isn't already, do the real work with tool calls, then "
    "kanban(action='complete') and kanban(action='update', note=…) with a "
    "short result. If the work needs the user, mark it blocked and explain what's "
    "needed. Just one card per idle tick — quality over volume."
)


_DEEP_THINK_PREAMBLE = (
    "You are in Deep Think mode — autonomous skill development. "
    "Complete this task fully, writing all needed files into the "
    "skills/ directory and installing any dependencies with "
    "install_package:"
)


def deep_think_directive(task_description: str) -> str:
    """The user-role message that enters Deep Think with one task.
    Pairs the framework preamble (mode + completion contract) with
    the queued task description. Caller is responsible for picking
    the task off the queue first."""
    body = (task_description or "").strip()
    return f"{_DEEP_THINK_PREAMBLE}\n\n{body}"


_CRON_PREAMBLE = (
    "(Scheduled) This prompt was fired by cron, not a live user. "
    "Work it through as you normally would; if it asks a question "
    "back, leave the answer in the logs / a board card — there's "
    "no one to read free-text right now."
)


def cron_prompt(prompt: str, *, frame: bool = False) -> str:
    """The user-role message for a cron-fired prompt. Default is
    pass-through (matches today's ``cron_runner._invoke`` behaviour);
    set ``frame=True`` to wrap with the cron preamble. Callers can
    opt in per schedule once we add the right plumbing."""
    body = (prompt or "").strip()
    if not frame:
        return body
    return f"{_CRON_PREAMBLE}\n\n{body}"


__all__ = [
    "AUTO_BOARD_PROMPT",
    "cron_prompt",
    "deep_think_directive",
]
