"""Bounded model-only requests using the same adapters as Jaeger's agent loop."""
from __future__ import annotations

import base64
from pathlib import Path
import threading
from typing import Any

from .request_policy import GovernedAdapter, ModelPolicyError, route_for, select_request_client


def user_content(text, attachments, adapter, route):
    """Typed image input shared by Chat and the tool-using agent loop."""
    images = []
    for att in attachments:
        mime = str(att.get("mime_type") or "")
        if mime.startswith("image/") and att.get("safe_path"):
            path = Path(att["safe_path"])
            if not path.is_file():
                raise ModelPolicyError("An admitted image is unavailable. Reattach it before retrying.")
            if path.stat().st_size > 25 * 1024 * 1024:
                raise ModelPolicyError("Image exceeds the 25 MB model-input limit.")
            images.append({"type": "image_url", "image_url": {"url":
                f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode("ascii")}})
    if images:
        if not adapter.supports("vision"):
            raise ModelPolicyError(f"{route.provider}/{route.model} does not support direct images. "
                                   "Choose an image-capable model; the provider was not changed.")
        return [{"type": "text", "text": text}, *images]
    return text


def complete(config, layout, text, *, model=None, provider=None, system_prompt="",
             history=(), attachments=(), interrupt_event=None, on_delta=None, on_reasoning=None,
             on_input=None, on_route=None, on_model_identity=None, local_only=False,
             default_client=None):
    from jaeger_ai.contract.channel_messages import model_content
    from jaeger_agent.loop.runtime_bridge import _adapter_for_client
    from jaeger_agent.loop.interrupt import AgentInterrupted

    interrupt = interrupt_event or threading.Event()
    if interrupt.is_set():
        raise AgentInterrupted("Cancelled before model dispatch")
    client = select_request_client(config, layout, model=model, provider=provider,
                                   default_client=default_client)
    route = route_for(client)
    adapter = _adapter_for_client(client)
    messages = [{"role": row["role"], "content": model_content(row)} for row in history
                if row.get("role") in {"user", "assistant"} and row.get("content")]
    current: dict[str, Any] = {"role": "user", "content": text}
    current["content"] = user_content(text, attachments, adapter, route)
    if not messages or messages[-1] != current:
        messages.append(current)
    context = getattr(adapter, "context_window", None) or getattr(getattr(client, "ext", None), "ctx", None)
    if context:
        from jaeger_agent.util.context_guard import ContextGuard, ContextBudget
        reserve = min(getattr(adapter, "max_tokens", 1024), max(1, context // 2))
        guard = ContextGuard(ContextBudget(ctx_window=context, reserve_for_completion=reserve))
        messages = guard.trim_to_fit(messages, system_prompt=system_prompt, tools=[]).messages
        if hasattr(adapter, "max_tokens"):
            adapter.max_tokens = reserve
    guarded = GovernedAdapter(adapter, route, local_only=local_only)
    formatted = guarded.format_messages(messages, [], system_prompt)
    if on_route:
        on_route(route.receipt())
    if on_input:
        on_input(formatted)
    reasoning_streamed = False
    def reasoning_delta(piece):
        nonlocal reasoning_streamed
        reasoning_streamed = True
        if on_reasoning:
            on_reasoning(piece)
    raw = guarded.call(formatted, interrupt, on_delta=on_delta,
                       on_reasoning=reasoning_delta,
                       first_progress_timeout_s=getattr(adapter, "first_progress_timeout_s", None))
    if interrupt.is_set():
        raise AgentInterrupted("Cancelled during model dispatch")
    parsed = adapter.parse_response(raw)
    if on_reasoning and not reasoning_streamed and parsed.get("reasoning"):
        on_reasoning(parsed["reasoning"])
    if parsed.get("finish_reason") in {"length", "partial_stream", "thinking_exhausted"}:
        raise RuntimeError("Model response stopped before completion. Retry or increase the response limit.")
    content = str(parsed.get("content") or "").strip()
    if not content or parsed.get("tool_calls"):
        raise RuntimeError("The selected model did not return a valid model-only answer.")
    if on_model_identity:
        from jaeger_ai.core.redaction import redact_text
        reported = raw.get("model") if isinstance(raw, dict) else getattr(raw, "model", None)
        on_model_identity(reported if isinstance(reported, str) and len(reported) <= 200
                          and redact_text(reported) == reported else None)
    return content
