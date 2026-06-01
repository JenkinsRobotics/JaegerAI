"""``HermesXMLAdapter`` — local models that speak Hermes-style XML.

Two distinct use cases share this adapter:

  1. **Models without structured tool-calling.** Older Hermes finetunes,
     base instruct models that weren't trained on ``tools=[...]``: the
     tools list is embedded in the system prompt as a ``<tools>`` JSON
     block and the model is told to emit calls inside
     ``<tool_call>{json}</tool_call>``. The agent parses those out of
     plain text. No structured ``tool_calls`` field exists on the wire.
  2. **Models with structured tool-calling that still drift.** Gemma 4
     and Qwen3-Coder *do* expose structured tool_calls — but their chat
     templates frequently emit the call as text anyway (or as text *and*
     structured, duplicated). Subclasses of :class:`OpenAIAdapter` that
     route through the chat-completions wire format inherit the drift
     parser to catch the text-only case.

This adapter implements case (1) — a fully text-based prompt path that
calls into a *runner* callable (``str -> str``). The runner is
deliberately a function instead of an SDK client so it can wrap
``llama_cpp.Llama.create_completion``, ``mlx_lm.generate``, an HTTP
``/completion`` endpoint, or a unit-test stub interchangeably.

Drift parsing lives in :mod:`jaeger_os.agent.dialects` so both this
adapter and the future ``OpenAICompatLocalAdapter`` (Gemma / Qwen on
llama.cpp's OpenAI surface) can share one battle-tested implementation.
"""

from __future__ import annotations

import json
import threading
import time
from typing import Any, Callable

from jaeger_os.agent.dialects import extract_tool_calls
from jaeger_os.agent.loop.interrupt import interruptible_call
from jaeger_os.agent.schemas.message_types import Message
from jaeger_os.agent.schemas.tool_schema import ToolDef
from .base import ProviderAdapter


# Features this adapter supports. No native parallel tool calls — Hermes
# XML expects one ``<tool_call>`` block per assistant turn (the drift
# parser will salvage multiple if the model emits them, but the design
# contract is one).
_FEATURES: frozenset[str] = frozenset()


HERMES_TOOL_INSTRUCTIONS = """\
You are a tool-calling AI assistant. You have access to the following
tools. To use one, respond with EXACTLY:

<tool_call>
{"name": "<tool_name>", "arguments": <json-object>}
</tool_call>

After the tool runs, you will see the result as a user message. Continue
until the user's question is fully answered, then reply with plain text
and no <tool_call> block.
"""


def _stringify_content(content: Any) -> str:
    """Tool results are arbitrary JSON-friendly Python; we stringify so
    the model sees one consistent textual representation regardless of
    where the call came from."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    try:
        return json.dumps(content, default=str, ensure_ascii=False)
    except Exception:  # noqa: BLE001 — last-resort fallback
        return str(content)


def _render_tools_block(tools: list[ToolDef]) -> str:
    """Render the tool catalogue as the JSON array Hermes finetunes
    expect inside ``<tools>...</tools>``. Each tool is its OpenAI
    schema — that's the shape Hermes was finetuned against."""
    if not tools:
        return ""
    schemas = [t.to_openai_schema() for t in tools]
    return f"<tools>\n{json.dumps(schemas, ensure_ascii=False)}\n</tools>"


def _render_message_as_text(msg: Message) -> str:
    """Render one internal ``Message`` to the Hermes XML chat-turn shape.

    Assistant turns with tool calls become ``<tool_call>`` blocks. Tool
    result turns become ``<tool_response>`` blocks. Everything else is
    plain text under a ``role:`` label.
    """
    role = msg.get("role")
    text = msg.get("content")
    tool_calls = msg.get("tool_calls") or []

    if role == "assistant" and tool_calls:
        parts: list[str] = []
        if text:
            parts.append(str(text))
        for tc in tool_calls:
            payload = {
                "name": tc.get("name") or "",
                "arguments": tc.get("arguments") or {},
            }
            parts.append(
                f"<tool_call>\n{json.dumps(payload, ensure_ascii=False)}\n</tool_call>"
            )
        return "<|im_start|>assistant\n" + "\n".join(parts) + "\n<|im_end|>"

    if role == "tool":
        body = _stringify_content(text)
        return f"<|im_start|>user\n<tool_response>\n{body}\n</tool_response>\n<|im_end|>"

    label = role or "user"
    return f"<|im_start|>{label}\n{text or ''}\n<|im_end|>"


class HermesXMLAdapter(ProviderAdapter):
    """Adapter for text-completion runners that speak Hermes XML.

    Construction:

      * ``runner`` — ``Callable[[str, dict], str]``. Receives the fully
        assembled prompt and any kwargs the agent loop passed through.
        Returns the model's raw text completion. Wrap your llama-cpp /
        mlx-lm / HTTP-/completion call here.
      * ``name`` — short identifier for the ``/runtime`` panel.
      * ``stop_sequences`` — completion stop tokens the runner should
        honour. Recorded on the adapter so the loop can read them, but
        passing them to the underlying runtime is the runner's job.
      * ``inject_tool_instructions`` — when True (default), the system
        prompt is augmented with :data:`HERMES_TOOL_INSTRUCTIONS` so the
        model knows the format. Off for runners whose chat template
        already injects equivalent prose.
    """

    def __init__(
        self,
        runner: Callable[[str, dict[str, Any]], str],
        *,
        name: str = "hermes-xml",
        stop_sequences: tuple[str, ...] = ("<|im_end|>",),
        inject_tool_instructions: bool = True,
    ) -> None:
        self.runner = runner
        self.name = name
        self.stop_sequences = tuple(stop_sequences)
        self.inject_tool_instructions = bool(inject_tool_instructions)
        # Diagnostics — last call's raw text + parsed shape. Exposed
        # for the ``/runtime`` panel and unit tests.
        self.last_raw_response: str | None = None
        self.last_usage: dict[str, Any] | None = None

    # ── conversion ──────────────────────────────────────────────────

    def format_messages(
        self,
        messages: list[Message],
        tools: list[ToolDef],
        system: str,
    ) -> dict[str, Any]:
        """Assemble the full text prompt + the kwargs the runner needs.

        The agent loop's ``system`` text and any internal ``system``
        messages get merged together at the top, optionally followed by
        the Hermes tool-calling instructions and the ``<tools>`` JSON
        block. Then the conversation turns render in order.
        """
        # Pull internal system messages out of the conversation — they
        # belong at the top alongside the loop-provided system.
        system_parts: list[str] = []
        if system:
            system_parts.append(system)
        if self.inject_tool_instructions and tools:
            system_parts.append(HERMES_TOOL_INSTRUCTIONS.strip())
        tools_block = _render_tools_block(tools)
        if tools_block:
            system_parts.append(tools_block)

        convo: list[Message] = []
        for m in messages:
            if m.get("role") == "system":
                extra = m.get("content") or ""
                if extra:
                    system_parts.append(extra)
                continue
            convo.append(m)

        prompt_chunks: list[str] = []
        if system_parts:
            prompt_chunks.append(
                "<|im_start|>system\n"
                + "\n\n".join(system_parts)
                + "\n<|im_end|>"
            )
        for m in convo:
            prompt_chunks.append(_render_message_as_text(m))
        # Open the assistant turn so the runner picks up generating
        # straight into the assistant slot — mirrors the canonical
        # Hermes chat template.
        prompt_chunks.append("<|im_start|>assistant\n")

        return {
            "prompt": "\n".join(prompt_chunks),
            "stop": list(self.stop_sequences),
        }

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
        """Invoke the runner with the assembled prompt, interrupt-aware.

        The runner is treated as a blocking sync function — wrap any
        async generation behind a ``run_until_complete`` shim before
        passing it in. ``interruptible_call`` runs it on a daemon
        thread and polls the cancel flag.

        Phase-8: ``stale_timeout`` / ``on_heartbeat`` flow through so
        a hung local-model runner can be surfaced cleanly.
        """
        merged = {**formatted, **kwargs}
        prompt = merged.pop("prompt", "")
        started = time.perf_counter()
        raw = interruptible_call(
            lambda: self.runner(prompt, merged),
            interrupt_event,
            stale_timeout=stale_timeout,
            on_heartbeat=on_heartbeat,
        )
        self.last_usage = {
            "latency_s": round(time.perf_counter() - started, 3),
            "prompt_chars": len(prompt),
            "response_chars": len(raw or ""),
        }
        return raw

    def parse_response(self, raw: Any) -> Message:
        """Decode runner text → internal ``Message``.

        Drift parser pulls ``<tool_call>`` blocks out, then any residual
        text becomes the assistant's plain content. The block itself is
        stripped from the visible content so the model isn't shown its
        own ``<tool_call>`` envelope back as user-visible text.
        """
        text = str(raw or "")
        self.last_raw_response = text

        tool_calls = extract_tool_calls(text)
        cleaned = self._strip_tool_call_blocks(text).strip()

        message: Message = {
            "role": "assistant",
            "content": cleaned or None,
        }
        if tool_calls:
            message["tool_calls"] = tool_calls
        return message

    @staticmethod
    def _strip_tool_call_blocks(text: str) -> str:
        """Remove every ``<tool_call>`` / ``<|tool_call|>`` envelope
        from a response so the visible assistant text doesn't carry the
        call markup. Mirrors the patterns used in
        :mod:`jaeger_os.agent.dialects` — kept in sync there."""
        import re
        patterns = [
            r"<\|tool_call\|>\s*.*?\s*<\|/tool_call\|>",
            r"<\|tool_call>\s*call:[^<]*<tool_call\|>",
            r"<tool_call>\s*.*?\s*</tool_call>",
        ]
        out = text
        for p in patterns:
            out = re.sub(p, "", out, flags=re.DOTALL)
        return out

    # ── capabilities + health ───────────────────────────────────────

    def supports(self, feature: str) -> bool:
        return feature in _FEATURES

    def health_check(self) -> dict[str, Any]:
        """Cheap reachability probe — invoke the runner with an empty
        prompt and confirm it returns. A runner that doesn't tolerate
        an empty prompt should be wrapped to substitute a sentinel."""
        started = time.perf_counter()
        try:
            self.runner("", {})
            return {
                "ok": True,
                "detail": "runner responded",
                "latency_s": round(time.perf_counter() - started, 2),
            }
        except Exception as exc:  # noqa: BLE001 — health probe must never raise
            return {
                "ok": False,
                "detail": f"{type(exc).__name__}: {exc}"[:200],
                "latency_s": round(time.perf_counter() - started, 2),
            }

    def describe(self) -> str:
        return f"hermes-xml · {self.name}"


__all__ = ["HermesXMLAdapter", "HERMES_TOOL_INSTRUCTIONS"]
