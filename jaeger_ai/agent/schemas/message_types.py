"""Internal message format — plain ``TypedDict``s, OpenAI-shaped.

Every provider adapter converts to and from this shape, so the agent
loop only ever sees one message type regardless of which backend
(Anthropic / OpenAI-compatible / Hermes XML / in-process llama-cpp /
MLX / future ROS-bridged remote model) is active. Mirrors Hermes-
agent's run_agent.py message format exactly — that's the proven
lingua franca for multi-provider tool-calling agents.

Why TypedDict and not a Pydantic model: the spec is explicit about this
— validation runs *at trust boundaries* (tool argument decode from the
model's response, persistence to disk, ZMQ message ingress) and **not**
on every internal hop. A 30 Hz perception node piping into the agent
loop cannot afford a `BaseModel.model_validate` per message. TypedDict
gives us static type checking with zero runtime cost.
"""

from __future__ import annotations

from typing import Any, Literal, TypedDict


Role = Literal["system", "user", "assistant", "tool"]


class ToolCall(TypedDict):
    """One tool call emitted by the assistant. ``arguments`` is already
    a dict — adapter parsers JSON-decode (and repair) provider-native
    formats before we get here."""

    id: str
    name: str
    arguments: dict[str, Any]


class Message(TypedDict, total=False):
    """One turn in the conversation. ``total=False`` because the
    optional fields vary by role:

      • ``system``    — ``content``
      • ``user``      — ``content``
      • ``assistant`` — ``content`` (optional) AND/OR ``tool_calls``
      • ``tool``      — ``content``, ``tool_call_id``, optionally ``name``

    The agent loop appends to a ``list[Message]``; the adapter is
    responsible for shaping it into whatever the provider expects on
    the wire (Anthropic's separate ``system`` parameter, OpenAI's flat
    list, Hermes-XML's inline ``<tool_response>`` blocks).
    """

    role: Role
    content: str | None
    tool_calls: list[ToolCall] | None
    tool_call_id: str | None        # for role="tool"
    name: str | None                # for role="tool"
    # Optional metadata adapters may attach to the assistant turn. The
    # agent loop reads ``finish_reason`` to drive Phase-8 retry logic
    # (length-continue + truncated-tool-call retry).
    finish_reason: str | None       # "stop" / "length" / "tool_calls" / ...


__all__ = ["Role", "ToolCall", "Message"]
