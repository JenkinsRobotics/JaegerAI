"""Ollama native transport for local context and thinking controls.

    The shared loop and OpenAI message parser remain authoritative. Hosted
    Ollama models retain the existing OpenAI transport. Local runtime options
    belong on /api/chat; putting options.num_ctx on /v1 did not enforce them.
"""
from __future__ import annotations

import copy
import json
import threading
import time
from urllib.parse import urlparse

from .openai import OpenAIAdapter
from jaeger_agent.loop.interrupt import AgentInterrupted, CallProgress, interruptible_call


class OllamaAdapter(OpenAIAdapter):
    def __init__(self, *, metadata=None, reasoning_policy="auto", **kwargs):
        super().__init__(**kwargs)
        self._metadata_value = metadata
        self.reasoning_policy = reasoning_policy
        self.effective_thinking = None

    @property
    def _native_root(self):
        root = (self.base_url or "http://localhost:11434/v1").rstrip("/")
        for suffix in ("/v1", "/api"):
            if root.endswith(suffix):
                root = root[:-len(suffix)]
                break
        return root

    def _metadata(self):
        if urlparse(self._native_root).hostname == "ollama.com":
            # Direct cloud chat does not need /api/show; skip a failing probe.
            return self._metadata_value or {}
        if self._metadata_value is None:
            import httpx
            headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
            response = httpx.post(self._native_root + "/api/show", json={"model": self.model},
                                  headers=headers, timeout=5)
            response.raise_for_status()
            self._metadata_value = response.json()
        return self._metadata_value

    def _hosted(self):
        # Native /api/chat is used for both local Ollama and ollama.com.
        return False

    def _native_body(self, formatted, metadata):
        messages = copy.deepcopy(formatted["messages"])
        names = {}
        for message in messages:
            for call in message.get("tool_calls") or []:
                names[call.get("id")] = call["function"]["name"]
                args = call["function"]["arguments"]
                call["function"]["arguments"] = json.loads(args) if isinstance(args, str) else args
            if message["role"] == "tool":
                message["tool_name"] = names.get(message.get("tool_call_id"), "")
            if message.get("content") is None:
                message["content"] = ""
            # Native Ollama accepts base64 image data, not OpenAI content blocks.
            if isinstance(message.get("content"), list):
                texts, images = [], []
                for block in message["content"]:
                    if block.get("type") == "text":
                        texts.append(block["text"])
                    elif block.get("type") == "image_url":
                        url = block["image_url"]["url"]
                        if not url.startswith("data:image/") or ";base64," not in url:
                            raise ValueError("Local Ollama requires inline base64 images")
                        images.append(url.split(",", 1)[1])
                    else:
                        raise ValueError("Unsupported native Ollama content block")
                message["content"] = "\n".join(texts)
                if images:
                    message["images"] = images
        options = {"num_predict": formatted["max_tokens"]}
        options.update({key: formatted[key] for key in ("temperature", "top_p") if key in formatted})
        if self.num_ctx:
            options["num_ctx"] = self.num_ctx
        try:
            from jaeger_ai.core.models.router import ollama_cloud_api_model
            model_name = ollama_cloud_api_model(self.model) if self.provider == "ollama-cloud" else self.model
        except Exception:
            model_name = self.model
        body = {"model": model_name, "messages": messages, "stream": True, "options": options}
        if formatted.get("tools"):
            body["tools"] = formatted["tools"]
        effort = formatted.get("reasoning_effort")
        values = (metadata.get("thinking") or {}).get("values", [])
        if effort in {None, "", "auto", "provider"}:
            pass
        elif effort == "none":
            if values and False not in values:
                raise ValueError(f"{self.model} does not support disabling thinking; supported: {values}")
            body["think"] = False
        elif effort in values:
            body["think"] = effort
        elif values:
            raise ValueError(f"{self.model} does not support reasoning effort {effort!r}; supported thinking values: {values}")
        self.effective_thinking = body.get("think", (metadata.get("thinking") or {}).get("default"))
        return body

    def _call_once(self, formatted, interrupt_event, *, stale_timeout=None, first_progress_timeout_s=None, on_heartbeat=None,
                   on_abandon=None, join_on_abandon=0, progress=None, on_delta=None,
                   on_reasoning=None, **kwargs):
        if interrupt_event.is_set():
            raise AgentInterrupted("Ollama generation interrupted")
        if self._hosted():
            return super()._call_once(formatted, interrupt_event, stale_timeout=stale_timeout,
                first_progress_timeout_s=first_progress_timeout_s,
                on_heartbeat=on_heartbeat, on_abandon=on_abandon, join_on_abandon=join_on_abandon,
                progress=progress, on_delta=on_delta, on_reasoning=on_reasoning, **kwargs)
        metadata = self._metadata()
        if metadata.get("remote_host"):
            hosted = {k: v for k, v in formatted.items() if k != "extra_body"}
            if self.reasoning_policy in {None, "auto", "provider"}:
                hosted.pop("reasoning_effort", None)
            return super()._call_once(hosted, interrupt_event, stale_timeout=stale_timeout,
                first_progress_timeout_s=first_progress_timeout_s,
                on_heartbeat=on_heartbeat, on_abandon=on_abandon, join_on_abandon=join_on_abandon,
                progress=progress, on_delta=on_delta, on_reasoning=on_reasoning, **kwargs)
        body = self._native_body({**formatted, **kwargs}, metadata)
        beacon = progress or CallProgress()
        started = time.perf_counter()
        self.last_ttft_s = None
        active = []

        def generate():
            import httpx
            if interrupt_event.is_set():
                raise AgentInterrupted("Ollama generation interrupted")
            headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
            text, reasoning, calls = [], [], []
            final = None
            with httpx.Client(timeout=httpx.Timeout(max(self.timeout_s, first_progress_timeout_s or 0), connect=10), headers=headers) as client:
                with client.stream("POST", self._native_root + "/api/chat", json=body) as response:
                    active.append(response)
                    response.raise_for_status()
                    if interrupt_event.is_set():
                        raise AgentInterrupted("Ollama generation interrupted")
                    for line in response.iter_lines():
                        if interrupt_event.is_set():
                            raise AgentInterrupted("Ollama generation interrupted")
                        if not line:
                            continue
                        row = json.loads(line)
                        if row.get("error"):
                            raise RuntimeError(row["error"])
                        beacon.touch()
                        msg = row.get("message") or {}
                        if msg.get("content"):
                            text.append(msg["content"])
                            if on_delta:
                                on_delta(msg["content"])
                        if msg.get("thinking"):
                            reasoning.append(msg["thinking"])
                            if on_reasoning:
                                on_reasoning(msg["thinking"])
                        for call in msg.get("tool_calls") or []:
                            wire_call = copy.deepcopy(call)
                            arguments = wire_call["function"].get("arguments", {})
                            wire_call["function"]["arguments"] = json.dumps(arguments) if isinstance(arguments, dict) else arguments
                            calls.append(wire_call)
                        if row.get("done"):
                            final = row
                    active.clear()
            if final is None:
                raise RuntimeError("Ollama stream ended without a completion receipt")
            return {"model": final.get("model", self.model), "choices": [{
                "message": {"role": "assistant", "content": "".join(text),
                            "reasoning": "".join(reasoning), "tool_calls": calls},
                "finish_reason": final.get("done_reason", "stop")}],
                "usage": {"prompt_tokens": final.get("prompt_eval_count", 0),
                          "completion_tokens": final.get("eval_count", 0),
                          "total_tokens": final.get("prompt_eval_count", 0) + final.get("eval_count", 0)}}

        def abandon():
            for response in list(active):
                response.close()
            if on_abandon:
                on_abandon()

        result = interruptible_call(generate, interrupt_event,
            stale_timeout=stale_timeout if stale_timeout is not None else self.timeout_s,
            first_progress_timeout_s=first_progress_timeout_s,
            on_heartbeat=on_heartbeat, on_abandon=abandon,
            join_on_abandon=join_on_abandon, progress=beacon)
        if beacon.first is not None:
            self.last_ttft_s = max(0, beacon.first - started)
        return result
