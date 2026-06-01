"""``AnthropicAdapter`` — Claude via the official ``anthropic`` SDK.

Direct SDK calls, no pydantic-ai indirection. The adapter owns:

  • internal ``Message`` ↔ Anthropic content-block translation
  • the actual ``client.messages.create(...)`` round-trip, wrapped in
    :func:`jaeger_os.agent.loop.interrupt.interruptible_call` so Ctrl-C lands
  • response decode back to a single internal ``Message``
  • capability declaration + a lightweight health probe

Prompt caching: Anthropic's ``cache_control`` markers are applied to the
system prompt and the *last* user turn — the two highest-value cache
points for an agentic loop with growing history. The pre-refactor
external-model code did the same; the heuristic moves here so the agent
loop doesn't have to know the provider.
"""

from __future__ import annotations

import threading
import time
from typing import Any

from jaeger_os.agent.loop.interrupt import interruptible_call
from jaeger_os.agent.schemas.message_types import Message, ToolCall
from jaeger_os.agent.schemas.tool_schema import ToolDef
from .base import ProviderAdapter

# Features Anthropic supports. Streaming is off-by-default for v1 (the
# agent loop uses callbacks for live updates); flip it on when the TUI's
# voice path lands and needs token-level latency.
_FEATURES: frozenset[str] = frozenset({"caching", "parallel_tools", "reasoning"})


def _coerce_content_to_text(content: Any) -> str:
    """Tool results are arbitrary JSON-friendly Python — Anthropic wants
    a string. ``json.dumps`` would be lossy on non-serialisable objects;
    ``str()`` is good enough for the model and never raises."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    try:
        import json
        return json.dumps(content, default=str, ensure_ascii=False)
    except Exception:  # noqa: BLE001 — last-resort fallback
        return str(content)


def _to_anthropic_blocks(msg: Message) -> list[dict[str, Any]] | str:
    """Translate one internal ``Message`` body to Anthropic content.

    Anthropic accepts either a plain string (text-only user/assistant)
    or a list of typed blocks (``text``, ``tool_use``, ``tool_result``).
    Use the block form when the message carries tool plumbing — that's
    the only path that can co-locate tool calls with text.
    """
    role = msg.get("role")
    text = msg.get("content")
    tool_calls = msg.get("tool_calls") or []

    if role == "assistant":
        blocks: list[dict[str, Any]] = []
        if text:
            blocks.append({"type": "text", "text": text})
        for tc in tool_calls:
            blocks.append({
                "type": "tool_use",
                "id": tc["id"],
                "name": tc["name"],
                "input": tc.get("arguments") or {},
            })
        return blocks or (text or "")

    if role == "tool":
        # The agent loop turns one internal "tool" message into a single
        # ``tool_result`` block hanging off a *user* turn — Anthropic's
        # wire format quirk.  Multiple parallel results merge at the
        # ``format_messages`` layer, not here.
        return [{
            "type": "tool_result",
            "tool_use_id": msg.get("tool_call_id") or "",
            "content": _coerce_content_to_text(text),
        }]

    # Plain user/system text rides as a string.
    return text or ""


class AnthropicAdapter(ProviderAdapter):
    """Concrete adapter for ``anthropic.Anthropic`` (and Bedrock-hosted
    Claude through the same SDK shape, if a Bedrock client is injected).

    Construction options:

      * ``api_key`` — required for direct Anthropic. Pass ``None`` and
        inject ``client`` when using Bedrock or a pre-built client.
      * ``model`` — e.g. ``"claude-sonnet-4-6"``.
      * ``max_tokens`` — default 4096; the per-turn ceiling on the
        response, not the context. Override per ``call`` via ``kwargs``.
      * ``timeout_s`` — SDK-level HTTP timeout.
      * ``base_url`` — optional override (proxies, Bedrock gateways).
      * ``prompt_caching`` — gate the ``cache_control`` markers; default
        on for direct Anthropic, callers turn it off for providers that
        don't honour the markers.
      * ``client`` — inject a pre-built SDK client for testing or
        Bedrock; when given, ``api_key`` / ``base_url`` are ignored.
    """

    name = "anthropic"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str = "claude-sonnet-4-6",
        max_tokens: int = 4096,
        timeout_s: float = 60.0,
        base_url: str | None = None,
        prompt_caching: bool = True,
        client: Any = None,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.max_tokens = int(max_tokens)
        self.timeout_s = float(timeout_s)
        self.base_url = base_url
        self.prompt_caching = bool(prompt_caching)
        # Lazily built so import-time has no network cost and unit tests
        # can pre-inject a stub client.
        self._client = client
        # The most recent ``call()``'s usage payload, exposed for budget
        # bookkeeping and the ``/runtime`` panel. Adapters that want to
        # surface usage to the agent loop set this on every successful
        # call.
        self.last_usage: dict[str, Any] | None = None

    # ── client lifecycle ────────────────────────────────────────────

    def _ensure_client(self) -> Any:
        if self._client is not None:
            return self._client
        from anthropic import Anthropic
        kwargs: dict[str, Any] = {"timeout": self.timeout_s}
        if self.api_key:
            kwargs["api_key"] = self.api_key
        if self.base_url:
            kwargs["base_url"] = self.base_url
        self._client = Anthropic(**kwargs)
        return self._client

    # ── conversion ──────────────────────────────────────────────────

    def format_messages(
        self,
        messages: list[Message],
        tools: list[ToolDef],
        system: str,
    ) -> dict[str, Any]:
        """Build the kwargs dict that goes into ``messages.create``.

        Anthropic splits system out of the conversation, demands strict
        ``user``/``assistant`` alternation, and packs tool plumbing into
        typed content blocks. The translation here is mechanical — but
        consecutive tool results merge into one user turn (Anthropic
        requires it for parallel tools) and tool blocks ride alongside
        text blocks on the same assistant turn.
        """
        converted: list[dict[str, Any]] = []
        for msg in messages:
            role = msg.get("role")
            if role == "system":
                # Internal "system" messages roll into the top-level
                # system parameter, not the conversation. Append to the
                # provided system so callers can supply both.
                extra = msg.get("content") or ""
                system = (system + "\n\n" + extra).strip() if system else extra
                continue

            body = _to_anthropic_blocks(msg)

            if role == "tool":
                # Merge with the previous user turn if it's also a tool
                # result group — Anthropic wants parallel results packed
                # together on a single user message.
                if (
                    converted
                    and converted[-1]["role"] == "user"
                    and isinstance(converted[-1]["content"], list)
                    and converted[-1]["content"]
                    and converted[-1]["content"][0].get("type") == "tool_result"
                ):
                    converted[-1]["content"].extend(body)  # type: ignore[arg-type]
                else:
                    converted.append({"role": "user", "content": body})
                continue

            if role in ("user", "assistant"):
                converted.append({"role": role, "content": body})
                continue

            # Unknown role — drop it loudly via the loop's logging
            # rather than silently corrupting the conversation.
            raise ValueError(f"unknown message role for Anthropic: {role!r}")

        # Cache markers on the highest-value spots: system + last user.
        system_payload: Any = system or None
        if self.prompt_caching and system:
            system_payload = [
                {"type": "text", "text": system, "cache_control": {"type": "ephemeral"}},
            ]
        if self.prompt_caching and converted:
            # Hermes "system_and_3" pattern: mark the system block + the
            # last 3 user/assistant turns with ``cache_control`` so a
            # follow-up call can reuse the cached prefix. Anthropic
            # caches up to 4 breakpoints, so we use system + 3 = 4. The
            # extra coverage vs marking only the last user turn means
            # the multi-tool sequences common in JROS (each tool result
            # generates a new user turn) still hit cache on the next
            # iteration.
            self._mark_recent_message_cache(converted, n=3)

        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "messages": converted,
        }
        if system_payload is not None:
            kwargs["system"] = system_payload
        if tools:
            kwargs["tools"] = [t.to_anthropic_schema() for t in tools]
        return kwargs

    @staticmethod
    def _mark_last_user_cache(messages: list[dict[str, Any]]) -> None:
        """Legacy single-marker helper — tag the trailing user turn
        only. Kept for callers that opt out of the broader marker
        coverage; the default :meth:`format_messages` now uses
        :meth:`_mark_recent_message_cache` instead."""
        for i in range(len(messages) - 1, -1, -1):
            if messages[i].get("role") != "user":
                continue
            AnthropicAdapter._mark_one_message(messages[i])
            return

    @staticmethod
    def _mark_one_message(message: dict[str, Any]) -> None:
        """Apply a ``cache_control`` marker to a single message in
        place. Wraps a string body in a single text block so the
        marker has a position to attach to; on an existing list of
        blocks, tags the last block (caching is positional)."""
        content = message.get("content")
        if isinstance(content, str):
            message["content"] = [{
                "type": "text", "text": content,
                "cache_control": {"type": "ephemeral"},
            }]
        elif isinstance(content, list) and content:
            content[-1] = {**content[-1], "cache_control": {"type": "ephemeral"}}

    @staticmethod
    def _mark_recent_message_cache(
        messages: list[dict[str, Any]], n: int = 3,
    ) -> None:
        """Tag the trailing ``n`` messages (any role) with
        ``cache_control``. Used together with the system-block marker
        to give Anthropic the four cache breakpoints it permits per
        request, maximising cache reuse across multi-tool turns.

        ``n`` is a soft target — if fewer than ``n`` messages are
        present, all of them get marked. The function is idempotent:
        re-marking an already-marked block leaves the existing marker
        in place rather than duplicating."""
        marked = 0
        # Walk from the end backwards so the "last n" are the n closest
        # to the latest message.
        for i in range(len(messages) - 1, -1, -1):
            if marked >= n:
                break
            AnthropicAdapter._mark_one_message(messages[i])
            marked += 1

    # ── call + parse ────────────────────────────────────────────────

    def call(
        self,
        formatted: Any,
        interrupt_event: threading.Event,
        *,
        stale_timeout: float | None = None,
        on_heartbeat: Any = None,
        **kwargs: Any,
    ) -> Any:
        """Run one ``messages.create`` request, interrupt-aware.

        Caller kwargs win over the formatted defaults — that's how the
        agent loop overrides ``max_tokens`` / ``temperature`` per turn
        without rebuilding the payload.

        Phase-8: ``stale_timeout`` / ``on_heartbeat`` propagate through
        :func:`interruptible_call` so the agent loop can detect hung
        provider sockets and surface "still waiting" status to the TUI.
        Both default to ``None`` — adapters used directly in tests get
        the legacy behaviour."""
        client = self._ensure_client()
        api_kwargs = {**formatted, **kwargs}
        return interruptible_call(
            lambda: client.messages.create(**api_kwargs),
            interrupt_event,
            stale_timeout=stale_timeout,
            on_heartbeat=on_heartbeat,
        )

    def parse_response(self, raw: Any) -> Message:
        """Decode an ``anthropic.types.Message`` to internal ``Message``.

        Anthropic returns a ``content: list[Block]`` with ``text`` and/or
        ``tool_use`` blocks; we concatenate text and lift tool_use into
        the internal ``ToolCall`` shape. ``usage`` lands on
        ``self.last_usage`` for the budget logic to read."""
        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        for block in getattr(raw, "content", []) or []:
            kind = getattr(block, "type", None)
            if kind == "text":
                text_parts.append(getattr(block, "text", "") or "")
            elif kind == "tool_use":
                tool_calls.append({
                    "id": getattr(block, "id", "") or "",
                    "name": getattr(block, "name", "") or "",
                    "arguments": dict(getattr(block, "input", {}) or {}),
                })

        usage = getattr(raw, "usage", None)
        if usage is not None:
            self.last_usage = {
                "input_tokens": getattr(usage, "input_tokens", None),
                "output_tokens": getattr(usage, "output_tokens", None),
                "cache_creation_input_tokens": getattr(
                    usage, "cache_creation_input_tokens", None,
                ),
                "cache_read_input_tokens": getattr(
                    usage, "cache_read_input_tokens", None,
                ),
            }

        message: Message = {"role": "assistant", "content": "".join(text_parts) or None}
        if tool_calls:
            message["tool_calls"] = tool_calls
        # Anthropic uses ``stop_reason`` rather than OpenAI's
        # ``finish_reason``; normalise so the agent loop's retry logic
        # reads one key regardless of backend. ``"max_tokens"`` is
        # Anthropic's signal for the same condition OpenAI calls
        # ``"length"``.
        stop_reason = getattr(raw, "stop_reason", None)
        if stop_reason:
            message["finish_reason"] = (
                "length" if stop_reason == "max_tokens" else stop_reason
            )
        return message

    # ── capabilities + health ───────────────────────────────────────

    def supports(self, feature: str) -> bool:
        return feature in _FEATURES

    def health_check(self) -> dict[str, Any]:
        """Cheap reachability probe — one-token generation. Anthropic
        has no ``/models`` list endpoint, so the smallest possible
        request stands in.

        Returns ``{ok, detail, latency_s}``. A failure is reported with
        ``ok=False`` and the exception's short class name — the slash
        command formats it for the user."""
        started = time.perf_counter()
        try:
            client = self._ensure_client()
            client.messages.create(
                model=self.model,
                max_tokens=1,
                messages=[{"role": "user", "content": "."}],
            )
            return {
                "ok": True,
                "detail": "reachable",
                "latency_s": round(time.perf_counter() - started, 2),
            }
        except Exception as exc:  # noqa: BLE001 — health probe must never raise
            return {
                "ok": False,
                "detail": f"{type(exc).__name__}: {exc}"[:200],
                "latency_s": round(time.perf_counter() - started, 2),
            }

    def describe(self) -> str:
        return f"anthropic · {self.model}"


__all__ = ["AnthropicAdapter"]
