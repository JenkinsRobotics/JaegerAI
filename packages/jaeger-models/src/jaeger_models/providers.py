"""Live HTTP model provider clients implementing ModelPort (Ollama, OpenAI-compat, Anthropic).

Zero external SDK dependencies (pure Python stdlib urllib + json) and zero upward
imports on jaeger_ai. Automatically handles tool schemas, structured tool calls,
thinking blocks, and deterministic repair of malformed arguments.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
import uuid
from typing import Any, Mapping, Sequence


def _post_json(
    url: str,
    payload: Mapping[str, Any],
    *,
    headers: Mapping[str, str] | None = None,
    timeout_s: float = 180.0,
) -> dict[str, Any]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req_headers = {"Content-Type": "application/json", **dict(headers or {})}
    req = urllib.request.Request(url, data=data, headers=req_headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return json.loads(raw) if raw.strip() else {}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"HTTP {exc.code} from {url}: {body}") from exc


def _get_json(
    url: str,
    *,
    headers: Mapping[str, str] | None = None,
    timeout_s: float = 5.0,
) -> dict[str, Any]:
    req = urllib.request.Request(url, headers=dict(headers or {}), method="GET")
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
        return json.loads(raw) if raw.strip() else {}


def _to_openai_tools(tools: Sequence[Mapping[str, Any]] | None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for t in tools or ():
        if "function" in t and t.get("type") == "function":
            out.append(dict(t))
        else:
            out.append({
                "type": "function",
                "function": {
                    "name": str(t.get("name") or ""),
                    "description": str(t.get("description") or ""),
                    "parameters": dict(t.get("schema") or t.get("parameters") or {"type": "object", "properties": {}}),
                },
            })
    return out


def _normalize_messages_for_openai(messages: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for m in messages:
        role = str(m.get("role") or "user")
        content = m.get("content")
        item: dict[str, Any] = {
            "role": role,
            "content": "" if content is None else str(content),
        }
        if role == "assistant" and m.get("tool_calls"):
            formatted_calls = []
            for tc in m["tool_calls"]:
                args = tc.get("arguments", {})
                formatted_calls.append({
                    "id": str(tc.get("id") or f"call_{uuid.uuid4().hex[:8]}"),
                    "type": "function",
                    "function": {
                        "name": str(tc.get("name") or ""),
                        "arguments": args if isinstance(args, str) else json.dumps(args, ensure_ascii=False),
                    },
                })
            item["tool_calls"] = formatted_calls
        if role == "tool":
            if m.get("tool_call_id"):
                item["tool_call_id"] = str(m["tool_call_id"])
            if m.get("name"):
                item["name"] = str(m["name"])
        out.append(item)
    return out


class OllamaModel:
    """Native Ollama /api/chat provider implementing ModelPort."""

    def __init__(
        self,
        model: str = "mistral-large-4:cloud",
        *,
        base_url: str = "http://127.0.0.1:11434",
        timeout_s: float = 180.0,
    ) -> None:
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._timeout_s = timeout_s

    @property
    def name(self) -> str:
        return f"ollama:{self._model}"

    @property
    def model_id(self) -> str:
        return self._model

    def list_models(self) -> list[dict[str, Any]]:
        try:
            data = _get_json(f"{self._base_url}/api/tags", timeout_s=3.0)
            return [
                {
                    "id": str(m.get("name") or ""),
                    "provider": "ollama",
                    "size": m.get("size"),
                    "modified_at": m.get("modified_at"),
                }
                for m in (data.get("models") or [])
                if m.get("name")
            ]
        except Exception:  # noqa: BLE001
            return []

    def probe(self) -> dict[str, Any]:
        try:
            models = self.list_models()
            return {"ok": True, "url": self._base_url, "models_count": len(models)}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "url": self._base_url, "error": str(exc)}

    def complete(
        self,
        messages: Sequence[Mapping[str, Any]],
        *,
        tools: Sequence[Mapping[str, Any]] | None = None,
        temperature: float = 0.2,
        max_tokens: int | None = None,
    ) -> Mapping[str, Any]:
        ollama_msgs: list[dict[str, Any]] = []
        for m in messages:
            role = str(m.get("role") or "user")
            entry: dict[str, Any] = {
                "role": role,
                "content": "" if m.get("content") is None else str(m.get("content")),
            }
            if role == "assistant" and m.get("tool_calls"):
                entry["tool_calls"] = [
                    {
                        "function": {
                            "name": str(tc.get("name") or ""),
                            "arguments": (
                                tc.get("arguments")
                                if isinstance(tc.get("arguments"), dict)
                                else {}
                            ),
                        }
                    }
                    for tc in m["tool_calls"]
                ]
            ollama_msgs.append(entry)

        payload: dict[str, Any] = {
            "model": self._model,
            "messages": ollama_msgs,
            "stream": False,
            "options": {"temperature": temperature},
        }
        if max_tokens is not None:
            payload["options"]["num_predict"] = int(max_tokens)
        if tools:
            payload["tools"] = _to_openai_tools(tools)

        data = _post_json(f"{self._base_url}/api/chat", payload, timeout_s=self._timeout_s)
        msg = data.get("message") or {}
        content = str(msg.get("content") or "")
        thinking = str(msg.get("thinking") or "")
        raw_calls = msg.get("tool_calls") or []
        tool_calls: list[dict[str, Any]] = []
        for idx, tc in enumerate(raw_calls):
            fn = tc.get("function") or {}
            args = fn.get("arguments") or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {"_raw": args}
            tool_calls.append({
                "id": str(tc.get("id") or f"call_{uuid.uuid4().hex[:8]}_{idx}"),
                "name": str(fn.get("name") or tc.get("name") or ""),
                "arguments": args,
            })

        return {
            "content": content,
            "thinking": thinking,
            "tool_calls": tool_calls,
            "usage": {
                "prompt_tokens": int(data.get("prompt_eval_count") or 0),
                "completion_tokens": int(data.get("eval_count") or 0),
            },
            "model": self._model,
        }


class OpenAICompatModel:
    """OpenAI-compatible /chat/completions provider implementing ModelPort."""

    def __init__(
        self,
        model: str,
        *,
        base_url: str = "https://api.openai.com/v1",
        api_key: str = "",
        timeout_s: float = 120.0,
    ) -> None:
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout_s = timeout_s

    @property
    def name(self) -> str:
        return f"openai:{self._model}"

    @property
    def model_id(self) -> str:
        return self._model

    def complete(
        self,
        messages: Sequence[Mapping[str, Any]],
        *,
        tools: Sequence[Mapping[str, Any]] | None = None,
        temperature: float = 0.2,
        max_tokens: int | None = None,
    ) -> Mapping[str, Any]:
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": _normalize_messages_for_openai(messages),
            "temperature": temperature,
        }
        if max_tokens is not None:
            payload["max_tokens"] = int(max_tokens)
        if tools:
            payload["tools"] = _to_openai_tools(tools)

        headers = {"Authorization": f"Bearer {self._api_key}"} if self._api_key else {}
        data = _post_json(
            f"{self._base_url}/chat/completions",
            payload,
            headers=headers,
            timeout_s=self._timeout_s,
        )
        choice = (data.get("choices") or [{}])[0]
        msg = choice.get("message") or {}
        content = str(msg.get("content") or "")
        thinking = str(msg.get("reasoning_content") or "")
        tool_calls: list[dict[str, Any]] = []
        for tc in msg.get("tool_calls") or []:
            fn = tc.get("function") or {}
            raw_args = fn.get("arguments") or "{}"
            try:
                args = json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args)
            except json.JSONDecodeError:
                args = {"_raw": raw_args}
            tool_calls.append({
                "id": str(tc.get("id") or f"call_{uuid.uuid4().hex[:8]}"),
                "name": str(fn.get("name") or ""),
                "arguments": args,
            })
        usage = data.get("usage") or {}
        return {
            "content": content,
            "thinking": thinking,
            "tool_calls": tool_calls,
            "usage": {
                "prompt_tokens": int(usage.get("prompt_tokens") or 0),
                "completion_tokens": int(usage.get("completion_tokens") or 0),
            },
            "model": self._model,
        }


class AnthropicModel:
    """Anthropic Messages API (/v1/messages) provider implementing ModelPort."""

    def __init__(
        self,
        model: str = "claude-sonnet-4-20250514",
        *,
        api_key: str = "",
        base_url: str = "https://api.anthropic.com",
        timeout_s: float = 120.0,
    ) -> None:
        self._model = model
        self._api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self._base_url = base_url.rstrip("/")
        self._timeout_s = timeout_s

    @property
    def name(self) -> str:
        return f"anthropic:{self._model}"

    @property
    def model_id(self) -> str:
        return self._model

    def complete(
        self,
        messages: Sequence[Mapping[str, Any]],
        *,
        tools: Sequence[Mapping[str, Any]] | None = None,
        temperature: float = 0.2,
        max_tokens: int | None = None,
    ) -> Mapping[str, Any]:
        system_parts: list[str] = []
        anth_msgs: list[dict[str, Any]] = []
        for m in messages:
            role = str(m.get("role") or "user")
            content = str(m.get("content") or "")
            if role == "system":
                system_parts.append(content)
            elif role == "tool":
                anth_msgs.append({
                    "role": "user",
                    "content": [{
                        "type": "tool_result",
                        "tool_use_id": str(m.get("tool_call_id") or "call_0"),
                        "content": content,
                    }],
                })
            elif role == "assistant" and m.get("tool_calls"):
                blocks: list[dict[str, Any]] = []
                if content:
                    blocks.append({"type": "text", "text": content})
                for tc in m["tool_calls"]:
                    blocks.append({
                        "type": "tool_use",
                        "id": str(tc.get("id") or f"call_{uuid.uuid4().hex[:8]}"),
                        "name": str(tc.get("name") or ""),
                        "input": dict(tc.get("arguments") or {}),
                    })
                anth_msgs.append({"role": "assistant", "content": blocks})
            else:
                anth_msgs.append({"role": role if role in ("user", "assistant") else "user", "content": content})

        payload: dict[str, Any] = {
            "model": self._model,
            "max_tokens": int(max_tokens or 4096),
            "temperature": temperature,
            "messages": anth_msgs,
        }
        if system_parts:
            payload["system"] = "\n\n".join(system_parts)
        if tools:
            payload["tools"] = [
                {
                    "name": str(t.get("name") or (t.get("function") or {}).get("name") or ""),
                    "description": str(t.get("description") or (t.get("function") or {}).get("description") or ""),
                    "input_schema": dict(
                        t.get("schema")
                        or t.get("input_schema")
                        or (t.get("function") or {}).get("parameters")
                        or {"type": "object", "properties": {}}
                    ),
                }
                for t in tools
            ]

        headers = {
            "x-api-key": self._api_key,
            "anthropic-version": "2023-06-01",
        }
        data = _post_json(f"{self._base_url}/v1/messages", payload, headers=headers, timeout_s=self._timeout_s)
        text_chunks: list[str] = []
        thinking_chunks: list[str] = []
        tool_calls: list[dict[str, Any]] = []
        for blk in data.get("content") or []:
            btype = blk.get("type")
            if btype == "text":
                text_chunks.append(str(blk.get("text") or ""))
            elif btype == "thinking":
                thinking_chunks.append(str(blk.get("thinking") or ""))
            elif btype == "tool_use":
                tool_calls.append({
                    "id": str(blk.get("id") or f"call_{uuid.uuid4().hex[:8]}"),
                    "name": str(blk.get("name") or ""),
                    "arguments": dict(blk.get("input") or {}),
                })
        usage = data.get("usage") or {}
        return {
            "content": "".join(text_chunks),
            "thinking": "".join(thinking_chunks),
            "tool_calls": tool_calls,
            "usage": {
                "prompt_tokens": int(usage.get("input_tokens") or 0),
                "completion_tokens": int(usage.get("output_tokens") or 0),
            },
            "model": self._model,
        }


def build_default_model(
    *,
    model: str | None = None,
    ollama_url: str | None = None,
) -> OllamaModel | OpenAICompatModel | AnthropicModel:
    """Resolve the active model provider from env or explicit override."""
    chosen = (model or os.environ.get("JAEGER_GATEWAY_OLLAMA_MODEL") or "mistral-large-4:cloud").strip()
    if chosen.startswith("anthropic:"):
        return AnthropicModel(chosen.split(":", 1)[1])
    if chosen.startswith("openai:"):
        return OpenAICompatModel(
            chosen.split(":", 1)[1],
            api_key=os.environ.get("OPENAI_API_KEY", ""),
            base_url=os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        )
    if chosen.startswith("ollama:"):
        chosen = chosen.split(":", 1)[1]
    return OllamaModel(
        model=chosen,
        base_url=ollama_url or os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434"),
    )


__all__ = [
    "AnthropicModel",
    "OllamaModel",
    "OpenAICompatModel",
    "build_default_model",
]
