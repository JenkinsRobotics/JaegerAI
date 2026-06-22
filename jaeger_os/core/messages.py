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
"""

from __future__ import annotations

from dataclasses import dataclass

from jaeger_os.app.bus.api import MessageRegistry
from jaeger_os.app.health import NodeHealth
from jaeger_os.app.logging import LogLine


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
class Transcript:
    """STT seam — what the voice path publishes. Reserved for the voice
    phase; the AgentBridge already routes it to the same inbox as chat."""
    text: str = ""
    topic: str = "/sense/transcript"


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
    topic: str = "/sense/tool"


# Registered for the ZMQ wire codec (the in-process bus passes objects
# through untouched and never consults the registry). NodeHealth + LogLine
# are chassis-standard ``/sys/*`` topics, registered so a surface can show
# ``/sys/log`` / node health later.
MESSAGES = MessageRegistry()
MESSAGES.register_all([
    ChatMessage, ChatReply, Transcript, AgentState, ToolEvent,
    AgentRequest, AgentResponse,
    NodeHealth, LogLine,
])

__all__ = [
    "MESSAGES", "ChatMessage", "ChatReply", "Transcript", "AgentState",
    "ToolEvent", "AgentRequest", "AgentResponse",
]
