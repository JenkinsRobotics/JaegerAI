"""Bus messages owned by the reusable agent boundary.

The messages intentionally remain simple dataclasses for compatibility with
JaegerAI's existing in-process surfaces.  Their topic strings are the stable
interface; moving them into the JaegerOS wire-schema registry is a later
cross-process transport milestone.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict

CHAT_INPUT_TOPIC = "/act/chat"
CHAT_REPLY_TOPIC = "/sense/chat"
AGENT_STATE_TOPIC = "/sense/agent_state"
AGENT_REQUEST_TOPIC = "/sense/request"
AGENT_RESPONSE_TOPIC = "/act/response"
TOOL_EVENT_TOPIC = "/sense/tool"
AGENT_ACTIVITY_TOPIC = "/sense/activity"
MODE_STATE_TOPIC = "/sense/mode"


@dataclass
class ChatMessage:
    text: str = ""
    source: str = "gui"
    session: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    topic: str = CHAT_INPUT_TOPIC


@dataclass
class ChatReply:
    text: str = ""
    session: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    topic: str = CHAT_REPLY_TOPIC


@dataclass
class AgentState:
    state: str = "idle"
    detail: str = ""
    session: str = ""
    topic: str = AGENT_STATE_TOPIC


@dataclass
class AgentRequest:
    id: str = ""
    kind: str = "approval"
    prompt: str = ""
    options: tuple[str, ...] = ()
    tool: str = ""
    session: str = ""
    topic: str = AGENT_REQUEST_TOPIC


@dataclass
class AgentResponse:
    id: str = ""
    answer: str = ""
    session: str = ""
    topic: str = AGENT_RESPONSE_TOPIC


@dataclass
class ToolEvent:
    name: str = ""
    phase: str = "start"
    elapsed_s: float = 0.0
    session: str = ""
    detail: str = ""
    topic: str = TOOL_EVENT_TOPIC


@dataclass
class AgentActivity:
    kind: str = "status"
    text: str = ""
    session: str = ""
    topic: str = AGENT_ACTIVITY_TOPIC


@dataclass
class ModeState:
    mode: str = "normal"
    autonomy: str = "scoped"
    topic: str = MODE_STATE_TOPIC


__all__ = [
    "AGENT_ACTIVITY_TOPIC",
    "AGENT_REQUEST_TOPIC",
    "AGENT_RESPONSE_TOPIC",
    "AGENT_STATE_TOPIC",
    "CHAT_INPUT_TOPIC",
    "CHAT_REPLY_TOPIC",
    "MODE_STATE_TOPIC",
    "TOOL_EVENT_TOPIC",
    "AgentActivity",
    "AgentRequest",
    "AgentResponse",
    "AgentState",
    "ChatMessage",
    "ChatReply",
    "ModeState",
    "ToolEvent",
]

