"""JROS bus message vocabulary — the chat path.

The windowed-app surfaces (and later voice/avatar) talk to the
agent **only over the bus**, never importing agent logic — so the GUI
toolkit stays disposable (PySide6 today, maybe Swift tomorrow). A message
is any dataclass with a ``topic: str`` field; the chassis bus delivers it.

Topic convention (chassis spec): ``/act/*`` = do, ``/sense/*`` = happened,
``/sys/*`` = chassis. Mirrors
``jaeger_app_framework/demos/jros-demo/core/messages.py``, scoped to the
chat surfaces for now — hardware/avatar messages arrive when those nodes
migrate onto the chassis bus.

``Transcript`` used to live here as a plain dataclass shadow of
``transport.topics.Transcript`` (the msgspec type the real audio_session
node publishes on ``/sense/transcript``) — two types on one topic, and
the dataclass had no ``is_final`` field, so :class:`~jaeger_os.agent.loop
.bridge.AgentBridge` treated every voice partial as a finished chat turn.
0.8 U3 deleted the dataclass; ``AgentBridge`` subscribes to
``transport.topics.SENSE_TRANSCRIPT`` directly and ignores non-final
transcripts.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ChatMessage:
    """Operator → agent — the window (and voice) input seam.

    ``session`` scopes the conversation (rolling history) so multiple
    chat windows / new conversations share one app-agent but keep their
    own context — the Hermes session model. Empty = the default session."""
    text: str = ""
    source: str = "gui"      # gui | voice
    session: str = ""
    topic: str = "/act/chat"


@dataclass
class ChatReply:
    """Agent → surfaces. Tier-1 rule: only the agent publishes this.

    ``session`` echoes the originating ``ChatMessage.session`` so a client
    renders only its own conversation's replies (events are routed by
    session, the way Hermes tags every event with its ``session_id``)."""
    text: str = ""
    session: str = ""
    topic: str = "/sense/chat"


@dataclass
class AgentState:
    """Agent lifecycle for the UI to render (idle | thinking | error).

    ``detail`` carries the live sub-status the CLI status bar shows —
    e.g. ``waiting on model 12.4s`` or a tool name — so windowed clients
    render the same "what is it doing" readout."""
    state: str = "idle"
    detail: str = ""
    session: str = ""
    topic: str = "/sense/agent_state"


@dataclass
class AgentRequest:
    """Agent → surface: a mid-turn prompt the operator must answer before
    the turn continues (approval | clarify | secret). The turn blocks until
    a matching :class:`AgentResponse` arrives — the Hermes interactive
    request/response pattern, carried over the bus so windowed/voice/remote
    surfaces can answer (not just the console)."""
    id: str = ""
    kind: str = "approval"          # approval | clarify | secret
    prompt: str = ""
    options: tuple[str, ...] = ()   # choices (approval/clarify); empty = free text
    tool: str = ""
    session: str = ""
    topic: str = "/sense/request"


@dataclass
class AgentResponse:
    """Surface → agent: the operator's answer to an :class:`AgentRequest`,
    correlated by ``id``. ``answer`` is the chosen option or free text."""
    id: str = ""
    answer: str = ""
    session: str = ""
    topic: str = "/act/response"


@dataclass
class ToolEvent:
    """Agent → surfaces: one tool dispatch, for live tool-activity lines.

    ``phase`` ∈ ``start`` | ``done`` | ``error``. Mirrors the agent loop's
    ``tool_progress`` callback (the same signal the terminal TUI's ``┊``
    lines render from), so every client shows tool use identically."""
    name: str = ""
    phase: str = "start"
    elapsed_s: float = 0.0
    session: str = ""
    # Short human context for the chip/line — today only skill calls set
    # it ("view scheduling"), so surfaces can show WHICH skill loaded.
    detail: str = ""
    topic: str = "/sense/tool"


@dataclass
class AgentActivity:
    """Agent → surfaces: one live progress line during a turn — a thought /
    status transition or a tool action — for the dimmed activity stream the
    windowed chat renders DISTINCT from the final reply, so a multi-minute turn
    shows what it's thinking/doing instead of a bare spinner. ``kind`` ∈
    ``thinking`` | ``tool`` | ``status``. Low-frequency (status transitions +
    tool calls), not per-token spam."""
    kind: str = "status"
    text: str = ""
    session: str = ""
    topic: str = "/sense/activity"


@dataclass
class ModeState:
    """Agent → surfaces: the active runtime mode (normal | high | deep-sleep)
    + autonomy mode (ask | scoped | auto) so the tray + chat header can show
    which model/voice profile is live and how autonomously it's executing."""
    mode: str = "normal"
    autonomy: str = "scoped"
    topic: str = "/sense/mode"


__all__ = [
    "ChatMessage", "ChatReply", "AgentState",
    "ToolEvent", "AgentActivity", "ModeState", "AgentRequest", "AgentResponse",
]
