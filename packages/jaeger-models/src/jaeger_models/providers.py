"""Live streaming HTTP model provider clients implementing ModelPort (Ollama, OpenAI-compat, Anthropic).

Supports real incremental token-by-token streaming (Ollama NDJSON, OpenAI SSE,
Anthropic SSE) via ``bind_stream_sink`` ContextVar, automatic tool-schema
sanitization, structured tool calls, thinking blocks, and prompt-cache usage metrics.
"""

from __future__ import annotations

import contextlib
import json
import os
import time
import urllib.error
import urllib.request
import uuid
from contextvars import ContextVar
from typing import Any, Callable, Iterator, Mapping, Sequence

from jaeger_contracts import ModelProfile

StreamSink = Callable[[str, str], None]
_stream_sink_var: ContextVar[StreamSink | None] = ContextVar("jaeger_model_stream_sink", default=None)


@contextlib.contextmanager
def bind_stream_sink(sink: StreamSink | None) -> Iterator[None]:
    """Bind a per-turn callback ``sink(kind, delta)`` where kind is ``'text'`` or ``'thinking'``."""
    token = _stream_sink_var.set(sink)
    try:
        yield
    finally:
        _stream_sink_var.reset(token)


def _emit_delta(kind: str, delta: str) -> None:
    if not delta:
        return
    sink = _stream_sink_var.get()
    if sink is not None:
        try:
            sink(kind, delta)
        except Exception:  # noqa: BLE001
            pass


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


def _post_stream_lines(
    url: str,
    payload: Mapping[str, Any],
    *,
    headers: Mapping[str, str] | None = None,
    timeout_s: float = 180.0,
) -> Iterator[str]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req_headers = {"Content-Type": "application/json", **dict(headers or {})}
    req = urllib.request.Request(url, data=data, headers=req_headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            for raw_line in resp:
                yield raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
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
    try:
        from jaeger_reliability.hermes_schema_sanitizer import sanitize_tool_schemas

        return sanitize_tool_schemas(out)
    except Exception:  # noqa: BLE001
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
    """Native Ollama /api/chat provider implementing ModelPort with live NDJSON streaming."""

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

    def profile(self, model_id: str) -> ModelProfile:
        """Resolve context window from loaded Ollama runner (/api/ps), falling back to /api/show."""
        window = 0
        try:
            runners = _get_json(f"{self._base_url}/api/ps", timeout_s=1.0)
            window = next((int(row.get("context_length") or 0)
                           for row in runners.get("models", [])
                           if model_id in (row.get("model"), row.get("name"))), 0)
        except Exception:  # noqa: BLE001
            window = 0
        if window <= 0:
            try:
                info = _post_json(f"{self._base_url}/api/show", {"name": model_id}, timeout_s=2.0)
                model_info = info.get("model_info") if isinstance(info, Mapping) else None
                if isinstance(model_info, Mapping):
                    for key, val in model_info.items():
                        if str(key).endswith(".context_length") and isinstance(val, (int, float)) and int(val) > 0:
                            window = int(val)
                            break
            except Exception:  # noqa: BLE001
                window = 0
        if window <= 0 and model_id.endswith((":cloud", "-cloud")):
            window = 131_072
        return ModelProfile(model_id=model_id, provider="ollama", context_window=window)

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
        sink = _stream_sink_var.get()
        emitted = False

        def forward(kind: str, delta: str) -> None:
            nonlocal emitted
            emitted = True
            if sink is not None:
                sink(kind, delta)

        delays = (0.5, 2.0, 5.0)
        for attempt in range(len(delays) + 1):
            try:
                with bind_stream_sink(forward if sink is not None else None):
                    return self._complete_once(
                        messages, tools=tools, temperature=temperature, max_tokens=max_tokens,
                    )
            except (RuntimeError, OSError) as exc:
                cause = exc.__cause__ or exc
                if isinstance(cause, urllib.error.HTTPError):
                    transient = cause.code in {408, 500, 502, 503, 504}
                else:
                    if isinstance(cause, urllib.error.URLError):
                        cause = cause.reason
                    transient = isinstance(cause, (ConnectionError, TimeoutError))
                if not transient:
                    raise
                if emitted:
                    raise RuntimeError("The model connection dropped after the response began.") from exc
                if attempt == len(delays):
                    raise RuntimeError("The model connection is still unavailable after three retries.") from exc
                time.sleep(delays[attempt])

    def _complete_once(
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

        streaming = _stream_sink_var.get() is not None
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": ollama_msgs,
            "stream": streaming,
            "options": {"temperature": temperature},
        }
        if max_tokens is not None:
            payload["options"]["num_predict"] = int(max_tokens)
        if tools:
            payload["tools"] = _to_openai_tools(tools)

        if streaming:
            content_parts: list[str] = []
            thinking_parts: list[str] = []
            raw_calls: list[dict[str, Any]] = []
            prompt_tokens = 0
            completion_tokens = 0
            done = False
            for line in _post_stream_lines(f"{self._base_url}/api/chat", payload, timeout_s=self._timeout_s):
                if not line.strip():
                    continue
                chunk = json.loads(line)
                if chunk.get("error"):
                    raise RuntimeError(f"Ollama stream error: {chunk['error']}")
                msg = chunk.get("message") or {}
                th = str(msg.get("thinking") or "")
                if th:
                    thinking_parts.append(th)
                    _emit_delta("thinking", th)
                tx = str(msg.get("content") or "")
                if tx:
                    content_parts.append(tx)
                    _emit_delta("text", tx)
                if msg.get("tool_calls"):
                    raw_calls.extend(msg["tool_calls"])
                if chunk.get("done"):
                    done = True
                    prompt_tokens = int(chunk.get("prompt_eval_count") or 0)
                    completion_tokens = int(chunk.get("eval_count") or 0)
            if not done:
                raise ConnectionError("Ollama closed the stream before completion.")
            content = "".join(content_parts)
            thinking = "".join(thinking_parts)
        else:
            data = _post_json(f"{self._base_url}/api/chat", payload, timeout_s=self._timeout_s)
            msg = data.get("message") or {}
            content = str(msg.get("content") or "")
            thinking = str(msg.get("thinking") or "")
            raw_calls = list(msg.get("tool_calls") or [])
            prompt_tokens = int(data.get("prompt_eval_count") or 0)
            completion_tokens = int(data.get("eval_count") or 0)

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
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
            },
            "model": self._model,
            "streamed": streaming,
        }


class OpenAICompatModel:
    """OpenAI-compatible /chat/completions provider implementing ModelPort with live SSE streaming."""

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
        streaming = _stream_sink_var.get() is not None
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": _normalize_messages_for_openai(messages),
            "temperature": temperature,
            "stream": streaming,
        }
        if streaming:
            payload["stream_options"] = {"include_usage": True}
        if max_tokens is not None:
            payload["max_tokens"] = int(max_tokens)
        if tools:
            payload["tools"] = _to_openai_tools(tools)

        headers = {"Authorization": f"Bearer {self._api_key}"} if self._api_key else {}
        if streaming:
            content_parts: list[str] = []
            thinking_parts: list[str] = []
            tc_acc: dict[int, dict[str, Any]] = {}
            usage: dict[str, Any] = {}
            for line in _post_stream_lines(
                f"{self._base_url}/chat/completions",
                payload,
                headers=headers,
                timeout_s=self._timeout_s,
            ):
                if not line.startswith("data:"):
                    continue
                body = line[5:].strip()
                if not body or body == "[DONE]":
                    continue
                chunk = json.loads(body)
                if chunk.get("usage"):
                    usage = chunk["usage"]
                choices = chunk.get("choices") or []
                if not choices:
                    continue
                delta = choices[0].get("delta") or {}
                th = str(delta.get("reasoning_content") or "")
                if th:
                    thinking_parts.append(th)
                    _emit_delta("thinking", th)
                tx = str(delta.get("content") or "")
                if tx:
                    content_parts.append(tx)
                    _emit_delta("text", tx)
                for tc in delta.get("tool_calls") or []:
                    idx = int(tc.get("index", 0))
                    slot = tc_acc.setdefault(idx, {"id": "", "name": "", "arguments": []})
                    if tc.get("id"):
                        slot["id"] = str(tc["id"])
                    fn = tc.get("function") or {}
                    if fn.get("name"):
                        slot["name"] += str(fn["name"])
                    if fn.get("arguments"):
                        slot["arguments"].append(str(fn["arguments"]))
            tool_calls: list[dict[str, Any]] = []
            for idx in sorted(tc_acc):
                slot = tc_acc[idx]
                raw_args = "".join(slot["arguments"]) or "{}"
                try:
                    args = json.loads(raw_args)
                except json.JSONDecodeError:
                    args = {"_raw": raw_args}
                tool_calls.append({
                    "id": slot["id"] or f"call_{uuid.uuid4().hex[:8]}_{idx}",
                    "name": slot["name"],
                    "arguments": args,
                })
            return {
                "content": "".join(content_parts),
                "thinking": "".join(thinking_parts),
                "tool_calls": tool_calls,
                "usage": {
                    "prompt_tokens": int(usage.get("prompt_tokens") or 0),
                    "completion_tokens": int(usage.get("completion_tokens") or 0),
                    "cache_read_tokens": int((usage.get("prompt_tokens_details") or {}).get("cached_tokens") or 0),
                },
                "model": self._model,
                "streamed": True,
            }

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
        tool_calls = []
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
                "cache_read_tokens": int((usage.get("prompt_tokens_details") or {}).get("cached_tokens") or 0),
            },
            "model": self._model,
            "streamed": False,
        }


class AnthropicModel:
    """Anthropic Messages API (/v1/messages) provider implementing ModelPort with live SSE streaming."""

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

        streaming = _stream_sink_var.get() is not None
        payload: dict[str, Any] = {
            "model": self._model,
            "max_tokens": int(max_tokens or 4096),
            "temperature": temperature,
            "messages": anth_msgs,
            "stream": streaming,
        }
        if system_parts:
            payload["system"] = "\n\n".join(system_parts)
        if tools:
            sanitized = _to_openai_tools(tools)
            payload["tools"] = [
                {
                    "name": str((t.get("function") or {}).get("name") or t.get("name") or ""),
                    "description": str((t.get("function") or {}).get("description") or t.get("description") or ""),
                    "input_schema": dict(
                        (t.get("function") or {}).get("parameters")
                        or t.get("input_schema")
                        or t.get("schema")
                        or {"type": "object", "properties": {}}
                    ),
                }
                for t in sanitized
            ]

        headers = {
            "x-api-key": self._api_key,
            "anthropic-version": "2023-06-01",
        }
        if streaming:
            text_chunks: list[str] = []
            thinking_chunks: list[str] = []
            tool_blocks: dict[int, dict[str, Any]] = {}
            input_tokens = 0
            output_tokens = 0
            cache_read_tokens = 0
            for line in _post_stream_lines(
                f"{self._base_url}/v1/messages",
                payload,
                headers=headers,
                timeout_s=self._timeout_s,
            ):
                if not line.startswith("data:"):
                    continue
                body = line[5:].strip()
                if not body:
                    continue
                ev = json.loads(body)
                etype = ev.get("type")
                if etype == "message_start":
                    u = (ev.get("message") or {}).get("usage") or {}
                    input_tokens = int(u.get("input_tokens") or 0)
                    cache_read_tokens = int(u.get("cache_read_input_tokens") or 0)
                elif etype == "content_block_start":
                    idx = int(ev.get("index", 0))
                    blk = ev.get("content_block") or {}
                    if blk.get("type") == "tool_use":
                        tool_blocks[idx] = {
                            "id": str(blk.get("id") or f"call_{uuid.uuid4().hex[:8]}"),
                            "name": str(blk.get("name") or ""),
                            "json_parts": [],
                        }
                elif etype == "content_block_delta":
                    idx = int(ev.get("index", 0))
                    delta = ev.get("delta") or {}
                    dtype = delta.get("type")
                    if dtype == "text_delta":
                        tx = str(delta.get("text") or "")
                        text_chunks.append(tx)
                        _emit_delta("text", tx)
                    elif dtype == "thinking_delta":
                        th = str(delta.get("thinking") or "")
                        thinking_chunks.append(th)
                        _emit_delta("thinking", th)
                    elif dtype == "input_json_delta" and idx in tool_blocks:
                        tool_blocks[idx]["json_parts"].append(str(delta.get("partial_json") or ""))
                elif etype == "message_delta":
                    u = ev.get("usage") or {}
                    output_tokens = int(u.get("output_tokens") or output_tokens)
            tool_calls = []
            for idx in sorted(tool_blocks):
                tb = tool_blocks[idx]
                raw = "".join(tb["json_parts"]) or "{}"
                try:
                    args = json.loads(raw)
                except json.JSONDecodeError:
                    args = {"_raw": raw}
                tool_calls.append({"id": tb["id"], "name": tb["name"], "arguments": args})
            return {
                "content": "".join(text_chunks),
                "thinking": "".join(thinking_chunks),
                "tool_calls": tool_calls,
                "usage": {
                    "prompt_tokens": input_tokens,
                    "completion_tokens": output_tokens,
                    "cache_read_tokens": cache_read_tokens,
                },
                "model": self._model,
                "streamed": True,
            }

        data = _post_json(f"{self._base_url}/v1/messages", payload, headers=headers, timeout_s=self._timeout_s)
        text_chunks = []
        thinking_chunks = []
        tool_calls = []
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
                "cache_read_tokens": int(usage.get("cache_read_input_tokens") or 0),
            },
            "model": self._model,
            "streamed": False,
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
    "StreamSink",
    "bind_stream_sink",
    "build_default_model",
]
