"""What Jaeger is doing, as clients see it.

One definition, because the Gateway publishes these and every client (WebUI,
IDE, menu bar, a future avatar or phone) renders them. They are a projection of
Gateway events. A client that reads them owns no memory, identity, goal,
permission or task state.
"""
from __future__ import annotations

from typing import Final

ACTIVITY_STATES: Final = (
    "idle", "listening", "thinking", "planning", "working", "observing", "waiting",
    "needs_owner", "blocked", "verifying", "done", "failed", "stopped", "offline",
)

#: Coarse label a presentation layer can animate from. Not a second state machine.
DISPLAY: Final = {
    "idle": "idle", "listening": "listening", "thinking": "thinking", "planning": "thinking",
    "working": "focused", "observing": "focused", "verifying": "focused", "waiting": "waiting",
    "needs_owner": "ask_owner", "blocked": "blocked", "done": "complete", "failed": "blocked",
    "stopped": "safe_stopped", "offline": "offline",
}

#: Terminal task states mapped to the activity that reports them.
ACTIVITY_FOR_TASK_STATE: Final = {
    "completed_verified": "done", "needs_owner": "needs_owner", "blocked": "blocked",
    "failed": "failed", "cancelled": "stopped", "paused": "waiting",
}
