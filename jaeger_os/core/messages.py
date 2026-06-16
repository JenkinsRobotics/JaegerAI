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
    """Operator → agent — the window (and voice) input seam."""
    text: str = ""
    source: str = "gui"      # gui | voice
    topic: str = "/act/chat"


@dataclass
class ChatReply:
    """Agent → surfaces. Tier-1 rule: only the agent publishes this."""
    text: str = ""
    topic: str = "/sense/chat"


@dataclass
class Transcript:
    """STT seam — what the voice path publishes. Reserved for the voice
    phase; the AgentBridge already routes it to the same inbox as chat."""
    text: str = ""
    topic: str = "/sense/transcript"


@dataclass
class AgentState:
    """Agent lifecycle for the UI to render (idle | thinking | error)."""
    state: str = "idle"
    topic: str = "/sense/agent_state"


# Registered for the ZMQ wire codec (the in-process bus passes objects
# through untouched and never consults the registry). NodeHealth + LogLine
# are chassis-standard ``/sys/*`` topics, registered so a surface can show
# ``/sys/log`` / node health later.
MESSAGES = MessageRegistry()
MESSAGES.register_all([
    ChatMessage, ChatReply, Transcript, AgentState,
    NodeHealth, LogLine,
])

__all__ = [
    "MESSAGES", "ChatMessage", "ChatReply", "Transcript", "AgentState",
]
