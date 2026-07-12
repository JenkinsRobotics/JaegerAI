"""``OpenAIAdapter`` — every OpenAI-compatible backend in one class.

One adapter, five backends. The chat-completions wire format is
identical across:

  • OpenAI itself (api.openai.com)
  • Google Gemini's OpenAI-compatible endpoint
    (generativelanguage.googleapis.com/v1beta/openai/)
  • Ollama Cloud (ollama.com/v1) — hosted, API-key required
  • Local Ollama (localhost:11434/v1) — placeholder key accepted
  • LM Studio (localhost:1234/v1) — placeholder key accepted

The differences are at construction time (base URL + how the API key
is sourced), not in the request shape. So one adapter handles all
five — the ``provider`` slug is recorded for diagnostics and to pick
the right placeholder key when a real one isn't required.

Wire-format quirks vs Anthropic, all handled below:

  • Internal ``ToolCall.arguments`` is a ``dict``; OpenAI's ``arguments``
    is a JSON-encoded string. The adapter encodes on the way out and
    decodes on the way in.
  • Tool results carry ``tool_call_id`` on a top-level ``tool`` role,
    not embedded in a user turn (Anthropic's pattern).
  • System prompt rides inside ``messages`` as ``role="system"`` rather
    than a separate top-level parameter.
"""

from __future__ import annotations

import json
import threading
import time
from typing import Any

from jaeger_ai.agent.loop.interrupt import (
    AgentInterrupted,
    CallProgress,
    interruptible_call,
)
from jaeger_ai.agent.schemas.message_types import Message, ToolCall
from jaeger_os.core.tools.tool_schema import ToolDef
from .base import ProviderAdapter


# Backends that talk the OpenAI wire format. Mirrors
# ``_OPENAI_COMPATIBLE`` in ``core/external_model.py`` so the slugs stay
# consistent between the legacy code path and the new adapter.
KNOWN_PROVIDERS: frozenset[str] = frozenset({
    "openai", "lmstudio", "ollama", "ollama-cloud", "gemini",
})

# Local servers accept any non-empty key — supply a placeholder so the
# SDK doesn't refuse to construct. True cloud endpoints reject these.
_LOCAL_PLACEHOLDER_KEYS: dict[str, str] = {
    "lmstudio": "lm-studio",
    "ollama": "ollama",
}


# Features the chat-completions surface supports. Gated by capability
# rather than provider — a Gemini-on-OpenAI-compat call and an
# OpenAI-on-OpenAI call behave identically here.
_FEATURES: frozenset[str] = frozenset({"parallel_tools"})


def _coerce_content_to_text(content: Any) -> str:
    """Tool results are arbitrary JSON-friendly Python — OpenAI wants a
    string. Mirrors :mod:`adapters.anthropic`'s helper so both adapters
    agree on the serialisation contract."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    try:
        return json.dumps(content, default=str, ensure_ascii=False)
    except Exception:  # noqa: BLE001 — last-resort fallback
        return str(content)


def _to_openai_tool_calls(tool_calls: list[ToolCall]) -> list[dict[str, Any]]:
    """Internal ``ToolCall`` dicts → OpenAI ``tool_calls`` list.

    OpenAI nests ``name``/``arguments`` under a ``function`` object and
    requires ``arguments`` to be a JSON-encoded *string* (not a dict).
    """
    out: list[dict[str, Any]] = []
    for tc in tool_calls:
        out.append({
            "id": tc.get("id") or "",
            "type": "function",
            "function": {
                "name": tc.get("name") or "",
                "arguments": json.dumps(tc.get("arguments") or {}, ensure_ascii=False),
            },
        })
    return out


def _from_openai_tool_calls(raw_calls: Any) -> list[ToolCall]:
    """OpenAI ``tool_calls`` list → internal ``ToolCall`` dicts.

    The SDK can return either typed objects (``.function.arguments``)
    or plain dicts depending on version + streaming mode. Handle both.
    ``arguments`` is JSON-encoded string on the wire; decode to dict.
    Malformed JSON becomes ``{}`` plus a ``_raw_arguments`` field so the
    tool dispatcher can surface a clear validation error rather than
    crash on a quote-mismatched payload.
    """
    out: list[ToolCall] = []
    for raw in raw_calls or []:
        if isinstance(raw, dict):
            tc_id = raw.get("id") or ""
            fn = raw.get("function") or {}
            name = fn.get("name") or ""
            args_str = fn.get("arguments") or ""
        else:
            tc_id = getattr(raw, "id", "") or ""
            fn = getattr(raw, "function", None)
            name = getattr(fn, "name", "") or ""
            args_str = getattr(fn, "arguments", "") or ""

        try:
            arguments = json.loads(args_str) if args_str else {}
            if not isinstance(arguments, dict):
                arguments = {"value": arguments}
        except (TypeError, ValueError):
            # Try the drift parser's argument-repair pass before giving
            # up. Common model output bugs — trailing commas, single
            # quotes, Python ``None`` / ``True`` literals, unclosed
            # braces — are repairable; the previous code dropped them
            # to ``_raw_arguments`` and forced the model to retry the
            # whole call. ``repair_arguments`` lives in the drift
            # parser so it stays close to the in-text Gemma/Qwen
            # tolerance — same JSON repair, just applied to the
            # structured tool_calls path too.
            try:
                from jaeger_ai.agent.dialects import repair_arguments
                repaired, ok = repair_arguments(args_str)
                if ok and isinstance(repaired, dict):
                    arguments = repaired
                else:
                    arguments = {"_raw_arguments": args_str}
            except Exception:  # noqa: BLE001
                arguments = {"_raw_arguments": args_str}

        out.append({"id": tc_id, "name": name, "arguments": arguments})
    return out


class OpenAIAdapter(ProviderAdapter):
    """Concrete adapter for ``openai.OpenAI`` and every chat-completions
    compatible server. One class, five backends — selected by the
    ``provider`` slug.

    Construction options:

      * ``provider`` — one of :data:`KNOWN_PROVIDERS`. Drives placeholder
        keys, the ``describe`` line, and the ``name`` field. Unknown
        slugs are accepted (forward-compat) but log a warning via the
        loop's ``on_thinking`` hook the first time they're used.
      * ``model`` — model id (e.g. ``"gpt-4o"``, ``"gemma-3-27b-it"``).
      * ``api_key`` — required for cloud endpoints. Local servers accept
        ``None`` (the placeholder is injected).
      * ``base_url`` — provider endpoint. Defaults to OpenAI's official
        URL when the slug is ``openai``; required otherwise.
      * ``max_tokens`` / ``temperature`` / ``top_p`` — request defaults.
        Callers override per-``call`` via kwargs.
      * ``timeout_s`` — SDK-level HTTP timeout.
      * ``stream_transport`` — stream the response at the transport
        level and aggregate to one message (default on). Keeps the
        stale detector + SDK read-timeout honest on long generations
        and lets an interrupt actually cancel the request. Turn off
        for backends whose ``create`` can't stream (the in-process
        llama facade does this) or for test stubs that return a
        canned non-stream response.
      * ``client`` — inject a pre-built SDK client for testing.

    The adapter is intentionally thin — no retry / no fallback / no
    rate-limit handling. Retries belong in
    :mod:`jaeger_os.core.runtime.cloud_errors`; fallback belongs in
    ``JaegerAgent.fallback_adapters``.
    """

    def __init__(
        self,
        *,
        provider: str = "openai",
        model: str = "gpt-4o-mini",
        api_key: str | None = None,
        base_url: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.0,
        top_p: float = 0.95,
        timeout_s: float = 60.0,
        stream_transport: bool = True,
        client: Any = None,
    ) -> None:
        self.provider = provider
        self.model = model
        self.api_key = api_key
        self.base_url = base_url
        self.max_tokens = int(max_tokens)
        self.temperature = float(temperature)
        self.top_p = float(top_p)
        self.timeout_s = float(timeout_s)
        self.stream_transport = bool(stream_transport)
        self._client = client

        # The adapter's ``name`` shows up in the active-brain status line
        # — keep it precise so a user picking 'gemini' sees 'gemini'
        # rather than the generic 'openai'.
        self.name = provider

        # Most-recent usage payload — feeds the budget logic and the
        # ``/runtime`` panel. Populated by ``parse_response``.
        self.last_usage: dict[str, Any] | None = None
        # Real time-to-first-token of the most recent streamed call;
        # None when the call didn't stream or nothing arrived.
        self.last_ttft_s: float | None = None

    # ── client lifecycle ────────────────────────────────────────────

    def _resolve_key(self) -> str:
        """Return the effective API key, substituting a placeholder for
        local servers when no real key was provided."""
        if self.api_key:
            return self.api_key
        return _LOCAL_PLACEHOLDER_KEYS.get(self.provider, "")

    def _ensure_client(self) -> Any:
        if self._client is not None:
            return self._client
        from openai import OpenAI
        kwargs: dict[str, Any] = {"timeout": self.timeout_s}
        key = self._resolve_key()
        if key:
            kwargs["api_key"] = key
        if self.base_url:
            kwargs["base_url"] = self.base_url
        self._client = OpenAI(**kwargs)
        return self._client

    # ── conversion ──────────────────────────────────────────────────

    def format_messages(
        self,
        messages: list[Message],
        tools: list[ToolDef],
        system: str,
    ) -> dict[str, Any]:
        """Build the kwargs dict that goes into ``chat.completions.create``.

        OpenAI's ``messages`` list carries system inline (role
        ``"system"``), so the top-level ``system`` argument from the
        agent loop becomes the *first* message. Internal ``system``
        messages already in the list are preserved in order — they're
        usually mid-conversation reminders the prompt builder injected.
        """
        wire: list[dict[str, Any]] = []
        if system:
            wire.append({"role": "system", "content": system})

        for msg in messages:
            role = msg.get("role")
            text = msg.get("content")
            tool_calls = msg.get("tool_calls") or []

            if role == "assistant":
                entry: dict[str, Any] = {"role": "assistant"}
                # Content can be None when the assistant only made tool
                # calls — OpenAI accepts that, but represents the absence
                # explicitly rather than as a missing key.
                entry["content"] = text if text is not None else None
                if tool_calls:
                    entry["tool_calls"] = _to_openai_tool_calls(tool_calls)
                wire.append(entry)
                continue

            if role == "tool":
                wire.append({
                    "role": "tool",
                    "tool_call_id": msg.get("tool_call_id") or "",
                    "content": _coerce_content_to_text(text),
                })
                continue

            if role in ("user", "system"):
                wire.append({"role": role, "content": text or ""})
                continue

            raise ValueError(f"unknown message role for OpenAI: {role!r}")

        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": wire,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "top_p": self.top_p,
        }
        if tools:
            kwargs["tools"] = [t.to_openai_schema() for t in tools]
        return kwargs

    # ── call + parse ────────────────────────────────────────────────

    def call(
        self,
        formatted: Any,
        interrupt_event: threading.Event,
        *,
        stale_timeout: float | None = None,
        on_heartbeat: Any = None,
        on_abandon: Any = None,
        join_on_abandon: float = 0.0,
        progress: CallProgress | None = None,
        on_delta: Any = None,
        **kwargs: Any,
    ) -> Any:
        """Run one ``chat.completions.create`` request, interrupt-aware.

        Caller kwargs override formatted defaults — same contract as
        :class:`AnthropicAdapter`. ``progress`` lets a subclass with
        its own progress source (the in-process llama facade touches
        it per decoded token) feed the stale detector on the
        non-streamed path.

        With ``stream_transport`` on (the default), the request is
        streamed and re-aggregated into the plain chat-completion
        shape ``parse_response`` already reads. Three wins, same as
        the Anthropic adapter: the stale detector measures real
        silence instead of total elapsed time (a long healthy answer
        is no longer killed at the 30s HTTP default), the SDK read
        timeout sees continuous bytes, and an interrupt closes the
        stream so the server stops generating."""
        client = self._ensure_client()
        api_kwargs = {**formatted, **kwargs}
        self.last_ttft_s = None
        if not self.stream_transport:
            return interruptible_call(
                lambda: client.chat.completions.create(**api_kwargs),
                interrupt_event,
                stale_timeout=stale_timeout,
                on_heartbeat=on_heartbeat,
                on_abandon=on_abandon,
                join_on_abandon=join_on_abandon,
                progress=progress,
                executor=getattr(self, "_executor", None),
            )

        api_kwargs["stream"] = True
        # ``stream_options`` is an OpenAI extension; compat servers
        # (LM Studio, Ollama, Gemini-compat) may reject the unknown
        # field, so only the real endpoint gets it. Without it the
        # final usage block is absent and token accounting falls back
        # to the loop's whitespace estimate — acceptable.
        if self.provider == "openai" and "stream_options" not in api_kwargs:
            api_kwargs["stream_options"] = {"include_usage": True}
        progress = progress or CallProgress()
        beacon = progress

        def _streamed() -> Any:
            stream = client.chat.completions.create(**api_kwargs)
            return _aggregate_chat_stream(
                stream, interrupt_event, beacon, on_delta,
            )

        started = time.perf_counter()
        raw = interruptible_call(
            _streamed,
            interrupt_event,
            stale_timeout=stale_timeout,
            on_heartbeat=on_heartbeat,
            on_abandon=on_abandon,
            join_on_abandon=join_on_abandon,
            progress=progress,
            executor=getattr(self, "_executor", None),
        )
        # Real time-to-first-token from the beacon's first touch —
        # feeds the turn's latency report (previously hardcoded 0.0).
        if beacon.first is not None:
            self.last_ttft_s = max(0.0, beacon.first - started)
        return raw

    def parse_response(self, raw: Any) -> Message:
        """Decode a chat-completions response to internal ``Message``.

        Walks ``raw.choices[0].message`` — handles both typed SDK objects
        and the bare dicts a streaming aggregator might pass back. The
        ``usage`` block (when present) lands on ``self.last_usage`` for
        the budget logic.
        """
        choices = getattr(raw, "choices", None) or (
            raw.get("choices") if isinstance(raw, dict) else None
        ) or []
        if not choices:
            return {"role": "assistant", "content": None}
        choice = choices[0]
        message = getattr(choice, "message", None) or (
            choice.get("message") if isinstance(choice, dict) else {}
        )

        content = getattr(message, "content", None)
        if content is None and isinstance(message, dict):
            content = message.get("content")
        raw_tool_calls = getattr(message, "tool_calls", None)
        if raw_tool_calls is None and isinstance(message, dict):
            raw_tool_calls = message.get("tool_calls")

        tool_calls = _from_openai_tool_calls(raw_tool_calls)

        usage = getattr(raw, "usage", None) or (
            raw.get("usage") if isinstance(raw, dict) else None
        )
        if usage is not None:
            self.last_usage = {
                "prompt_tokens": _get(usage, "prompt_tokens"),
                "completion_tokens": _get(usage, "completion_tokens"),
                "total_tokens": _get(usage, "total_tokens"),
            }

        finish_reason = getattr(choice, "finish_reason", None)
        if finish_reason is None and isinstance(choice, dict):
            finish_reason = choice.get("finish_reason")

        out: Message = {"role": "assistant", "content": content or None}
        if tool_calls:
            out["tool_calls"] = tool_calls
        if finish_reason:
            out["finish_reason"] = finish_reason
        return out

    # ── capabilities + health ───────────────────────────────────────

    def supports(self, feature: str) -> bool:
        # Transport-level streaming is an implementation detail of
        # ``call`` — the loop still receives one whole message, so
        # "streaming" (token-level delivery to the loop) stays False.
        return feature in _FEATURES

    def health_check(self) -> dict[str, Any]:
        """Cheap reachability probe — ``GET /models``. Cheaper than a
        generation; doesn't burn quota.

        Returns ``{ok, detail, latency_s}``. The caller (slash command,
        startup) formats the message for the user."""
        started = time.perf_counter()
        try:
            client = self._ensure_client()
            client.models.list()
            return {
                "ok": True,
                "detail": "reachable",
                "latency_s": round(time.perf_counter() - started, 2),
            }
        except Exception as exc:  # noqa: BLE001 — never raise from a probe
            return {
                "ok": False,
                "detail": f"{type(exc).__name__}: {exc}"[:200],
                "latency_s": round(time.perf_counter() - started, 2),
            }

    def describe(self) -> str:
        endpoint = self.base_url or "api.openai.com/v1"
        return f"{self.provider} · {self.model} · {endpoint}"


def _get(obj: Any, name: str) -> Any:
    """Dict-or-attr accessor — SDKs return typed objects, streaming
    accumulators return dicts; tests sometimes use ``SimpleNamespace``.
    A single helper keeps the parse path tidy."""
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


def _aggregate_chat_stream(
    stream: Any,
    interrupt_event: threading.Event,
    progress: CallProgress,
    on_delta: Any = None,
) -> dict[str, Any]:
    """Drain a chat-completions stream into the non-streaming response
    shape ``parse_response`` reads.

    Runs on the worker thread inside :func:`interruptible_call`:
    touches ``progress`` per chunk (feeding the stale detector) and
    checks the interrupt event between chunks so a cancel closes the
    HTTP stream promptly — the server stops generating instead of
    completing an answer nobody will read.

    Handles both typed SDK chunks and plain dicts. Tool-call deltas
    arrive fragmented (id/name first, argument string in pieces,
    keyed by ``index``) and are reassembled here; the JSON ``arguments``
    string stays a string — ``_from_openai_tool_calls`` decodes and
    repairs it downstream exactly as in the non-streamed path.
    """
    content_parts: list[str] = []
    calls_by_index: dict[int, dict[str, Any]] = {}
    finish_reason: Any = None
    usage: Any = None
    try:
        try:
            for chunk in stream:
                progress.touch()
                if interrupt_event.is_set():
                    raise AgentInterrupted("interrupted mid-stream")
                chunk_usage = _get(chunk, "usage")
                if chunk_usage is not None:
                    usage = chunk_usage
                choices = _get(chunk, "choices") or []
                if not choices:
                    continue
                choice = choices[0]
                finish_reason = _get(choice, "finish_reason") or finish_reason
                delta = _get(choice, "delta")
                if delta is None:
                    continue
                piece = _get(delta, "content")
                if piece:
                    content_parts.append(piece)
                    if on_delta is not None:
                        on_delta(piece)
                for tc in _get(delta, "tool_calls") or []:
                    idx = _get(tc, "index")
                    idx = 0 if idx is None else int(idx)
                    slot = calls_by_index.setdefault(
                        idx, {"id": "", "name": "", "arguments": []},
                    )
                    if _get(tc, "id"):
                        slot["id"] = _get(tc, "id")
                    fn = _get(tc, "function")
                    if fn is not None:
                        if _get(fn, "name"):
                            slot["name"] = _get(fn, "name")
                        args_piece = _get(fn, "arguments")
                        if args_piece:
                            slot["arguments"].append(args_piece)
        except AgentInterrupted:
            raise
        except Exception:
            # Partial-stream recovery (Hermes pattern): the connection
            # died mid-answer. If TEXT already arrived and no tool call
            # was being assembled, return what we have — the words may
            # already be on screen / spoken, and a retry would produce
            # a different answer. A half-assembled tool call re-raises:
            # truncated arguments must never dispatch.
            if content_parts and not calls_by_index:
                finish_reason = "partial_stream"
            else:
                raise
    finally:
        close = getattr(stream, "close", None)
        if close is not None:
            try:
                close()
            except Exception:  # noqa: BLE001 — closing is best-effort
                pass

    message: dict[str, Any] = {
        "role": "assistant",
        "content": "".join(content_parts) or None,
    }
    if calls_by_index:
        message["tool_calls"] = [
            {
                "id": slot["id"],
                "type": "function",
                "function": {
                    "name": slot["name"],
                    "arguments": "".join(slot["arguments"]),
                },
            }
            for _, slot in sorted(calls_by_index.items())
        ]
    out: dict[str, Any] = {
        "choices": [{
            "index": 0,
            "message": message,
            "finish_reason": finish_reason,
        }],
    }
    if usage is not None:
        out["usage"] = {
            "prompt_tokens": _get(usage, "prompt_tokens"),
            "completion_tokens": _get(usage, "completion_tokens"),
            "total_tokens": _get(usage, "total_tokens"),
        }
    return out


__all__ = ["OpenAIAdapter", "KNOWN_PROVIDERS"]
