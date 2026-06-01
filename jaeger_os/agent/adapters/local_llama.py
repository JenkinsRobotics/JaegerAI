"""``LocalLlamaAdapter`` — in-process llama-cpp-python.

llama-cpp's ``create_chat_completion`` exposes an OpenAI-compatible
response shape, so 95% of :class:`OpenAIAdapter` applies unchanged.
The remaining 5%:

  • the "client" is a ``llama_cpp.Llama`` instance, not an
    ``openai.OpenAI`` — we wrap it in a thin facade that exposes
    ``.chat.completions.create(**kw)`` so the parent class's call path
    works verbatim.
  • Gemma 4 / Qwen3-Coder routinely emit tool calls as TEXT inside
    ``<tool_call>…</tool_call>`` blocks even when ``tools=[...]`` is
    passed structurally — :mod:`jaeger_os.agent.dialects` salvages
    those after the parent's parse step.

Construction stays light: nothing loads at import time. A real
``Llama`` instance is built on first call (or injected by the caller
when sharing one across adapters / instances).
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from jaeger_os.agent.dialects import (
    detect_family,
    detect_reasoning,
    extract_tool_calls,
    render_tools_for,
    strip_think_blocks,
    textify_tool_history,
)
from jaeger_os.agent.loop.interrupt import AgentInterrupted, StaleCallTimeout
from jaeger_os.agent.schemas.message_types import Message
from jaeger_os.agent.schemas.tool_schema import ToolDef
from .openai import OpenAIAdapter


# Stall-watchdog floor for reasoning models. They legitimately spend
# minutes deliberating in ``<think>`` blocks; the default 120s floor
# fires mid-thought, abandons the llama worker, and the next call hits
# a corrupted KV cache → process crash (the 2026-05-28 ``0/1`` aborts).
# A reasoning model gets at least this long before the watchdog trips.
_REASONING_STALL_FLOOR_S = 300.0

# After the stall watchdog signals abort, wait at most this long for the
# in-flight decode to notice ``stopping_criteria`` and finish, so the
# shared model is clean before the next call. A real generation stall
# stops within a token of the flag (sub-second); this short cap keeps a
# pathological "wedged in prefill" hang from blocking the bail. The abort
# flag stays SET after we bail, so even a worker that misses this window
# still self-terminates at its next token before the next case runs.
_ABORT_JOIN_S = 1.5


class _AbortGeneration(Exception):
    """Raised from the in-process ``logits_processor`` when the adapter's
    abort flag is set, to stop a stalled / interrupted decode cleanly at
    a token boundary (the KV cache stays consistent — the in-flight batch
    has already been decoded; we simply stop before sampling the next)."""


# Sensible llama-cpp defaults for Apple Silicon. Match the existing
# ``core/llm_client.py:LlamaCppPythonClient`` so a head-to-head with the
# legacy path measures the agent loop, not the backend.
_LLAMA_DEFAULTS: dict[str, Any] = {
    "n_ctx": 8192,
    "n_gpu_layers": -1,
    "n_batch": 512,
    "n_ubatch": 512,
    "flash_attn": True,
    "swa_full": False,
    "verbose": False,
}


class _LlamaChatFacade:
    """Adapts a ``llama_cpp.Llama`` to the ``.chat.completions.create``
    shape :class:`OpenAIAdapter._ensure_client` expects.

    Two nested attributes, one bound method — enough surface for the
    parent adapter's call site without dragging in the rest of the
    OpenAI client API. ``models.list`` is stubbed for health checks.
    """

    def __init__(self, llama: Any, abort_flag: Any = None) -> None:
        self._llama = llama
        self._abort_flag = abort_flag
        self.chat = self
        self.completions = self
        # ``models.list`` is what :meth:`OpenAIAdapter.health_check`
        # calls — an in-process model is always reachable once loaded,
        # so return an empty list rather than an exception.
        self.models = _LlamaModelsStub()

    def create(self, **kwargs: Any) -> Any:
        """Pass through to ``create_chat_completion``, stripping kwargs
        llama-cpp doesn't understand. The response is already in OpenAI
        shape so :meth:`OpenAIAdapter.parse_response` decodes it
        unchanged.

        Critical fix: llama-cpp's Jinja chat template (Qwen3.5, Gemma,
        Hermes, …) iterates ``tool_call.arguments|items`` — it expects
        ``arguments`` as a **dict**. But the OpenAI wire format encodes
        it as a JSON string, so the parent adapter's ``format_messages``
        JSON-dumps. We re-decode in-place here so the in-process chat
        template sees the dict it needs. Without this, the second turn
        of any multi-iteration conversation crashes with
        ``TypeError: Can only get item pairs from a mapping`` from
        Jinja's ``do_items`` filter.
        """
        kwargs.pop("stream", None) or kwargs.setdefault("stream", False)
        # llama-cpp accepts the same field names — only the auth-y bits
        # ride OpenAI's HTTP envelope and have no in-process equivalent.
        for hostonly in ("api_key", "base_url", "extra_headers", "timeout"):
            kwargs.pop(hostonly, None)
        # If the adapter pre-rendered the chat template with an explicit
        # ``enable_thinking`` (the cloud-style think ON/OFF toggle —
        # ``create_chat_completion`` won't take that as a kwarg), it
        # stashes the rendered prompt here. We branch to the lower-level
        # ``create_completion`` and wrap the raw text back into the
        # chat-completion shape so :meth:`OpenAIAdapter.parse_response`
        # is none the wiser. Drift parser still catches text-emitted
        # tool calls. Falls through to the normal path otherwise.
        manual_prompt = kwargs.pop("_thinking_prompt", None)
        if manual_prompt is not None:
            return self._create_with_rendered_prompt(manual_prompt, kwargs)
        msgs = kwargs.get("messages")
        if isinstance(msgs, list):
            kwargs["messages"] = [
                _coerce_none_content(_decode_tool_call_args(m)) for m in msgs
            ]
        # Phase-8 hardening: sanitise tool schemas before handing them
        # to llama-cpp's grammar generator. The generator rejects
        # bare-string schema values, ``type: [X, "null"]`` arrays, and
        # ``anyOf`` nullable unions with HTTP 400 / parse failures.
        # Sanitisation is idempotent so calling it twice is safe.
        tools = kwargs.get("tools")
        if isinstance(tools, list):
            from jaeger_os.agent.parsing import schema_sanitizer
            kwargs["tools"] = schema_sanitizer.sanitize_tool_schemas(tools)
        # Cooperative cancellation: ``create_chat_completion`` doesn't
        # accept ``stopping_criteria`` (only the low-level completion
        # path does), but it DOES accept a ``logits_processor`` that runs
        # every generated token. Bound to the adapter's abort flag, it
        # raises :class:`_AbortGeneration` the instant the flag is set, so
        # a stalled / interrupted decode stops CLEANLY mid-generation
        # instead of being abandoned — which would leave the shared
        # model's KV cache corrupted and cascade ``llama_decode -1/-3``
        # errors into every later call. See :func:`interruptible_call`.
        if self._abort_flag is not None and "logits_processor" not in kwargs:
            import llama_cpp
            flag = self._abort_flag

            def _abort_proc(input_ids: Any, scores: Any) -> Any:
                if flag.is_set():
                    raise _AbortGeneration()
                return scores

            kwargs["logits_processor"] = llama_cpp.LogitsProcessorList(
                [_abort_proc]
            )
        return self._llama.create_chat_completion(**kwargs)

    def _create_with_rendered_prompt(self, prompt: str, kwargs: dict) -> Any:
        """Lower-level path used when the adapter has pre-rendered the
        chat template (e.g. with ``enable_thinking=False`` to take the
        model out of its reasoning mode). Forwards only the kwargs that
        :meth:`Llama.create_completion` accepts, then re-shapes the raw
        text response into the chat-completion dict the parent's
        ``parse_response`` expects."""
        # Re-attach the abort flag's logits_processor (same cooperative-
        # cancellation contract as the structured path).
        if self._abort_flag is not None and "logits_processor" not in kwargs:
            import llama_cpp
            flag = self._abort_flag

            def _abort_proc(input_ids: Any, scores: Any) -> Any:
                if flag.is_set():
                    raise _AbortGeneration()
                return scores

            kwargs["logits_processor"] = llama_cpp.LogitsProcessorList(
                [_abort_proc]
            )
        gen_keys = {
            "max_tokens", "temperature", "top_p", "top_k", "min_p",
            "stop", "seed", "logprobs", "echo", "stream",
            "logits_processor", "grammar", "repeat_penalty",
            "presence_penalty", "frequency_penalty", "mirostat_mode",
            "mirostat_tau", "mirostat_eta",
        }
        gen_kwargs = {k: v for k, v in kwargs.items() if k in gen_keys}
        raw = self._llama.create_completion(prompt=prompt, **gen_kwargs)
        return _wrap_completion_as_chat(raw)


def _wrap_completion_as_chat(raw: dict) -> dict:
    """Convert a ``create_completion`` response into the
    ``create_chat_completion`` shape so the parent ``parse_response``
    can decode it unchanged. Drift parser handles any text-emitted tool
    calls; no native ``tool_calls`` field is populated by this path."""
    choices = raw.get("choices") or [{}]
    text = (choices[0].get("text") or "")
    finish = choices[0].get("finish_reason")
    return {
        "id": raw.get("id", ""),
        "object": "chat.completion",
        "model": raw.get("model", ""),
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": text},
            "finish_reason": finish,
        }],
        "usage": raw.get("usage", {}),
    }


class _LlamaModelsStub:
    @staticmethod
    def list() -> Any:
        from types import SimpleNamespace
        return SimpleNamespace(data=[])


def _coerce_none_content(msg: Any) -> Any:
    """Return ``msg`` with ``content=None`` rewritten to ``""``.

    A pure tool-call assistant turn carries ``content=None`` in the
    OpenAI wire shape — fine for OpenAI's API, but many GGUF chat
    templates render content with an unguarded ``'</think>' in content``
    or ``content + …`` and crash on ``None`` (verified: DeepSeek-R1's
    embedded template, 2026-05-28). We're the in-process path that runs
    the template directly, so we feed it a clean empty string instead.
    Matching the model means adapting to its template, not the reverse.
    """
    if isinstance(msg, dict) and msg.get("content") is None:
        return {**msg, "content": ""}
    return msg


def _decode_tool_call_args(msg: Any) -> Any:
    """Return ``msg`` with any assistant ``tool_calls[*].function.arguments``
    JSON-string decoded back to a dict.

    The OpenAI wire format encodes ``arguments`` as a JSON-encoded
    string; llama-cpp's bundled Jinja chat templates (Qwen3.5, Gemma,
    Hermes, …) instead expect a dict so they can iterate ``|items``.
    Walking once per message is O(messages × tool_calls) which is
    negligible vs the actual generation cost.

    Non-string ``arguments`` (already-dict, ``None``, malformed)
    pass through unchanged so the template's own ``|tojson`` fallback
    handles them.
    """
    if not isinstance(msg, dict):
        return msg
    if msg.get("role") != "assistant":
        return msg
    tool_calls = msg.get("tool_calls")
    if not tool_calls:
        return msg
    import json as _json
    new_tool_calls: list[Any] = []
    for tc in tool_calls:
        if not isinstance(tc, dict):
            new_tool_calls.append(tc)
            continue
        fn = tc.get("function")
        if not isinstance(fn, dict):
            new_tool_calls.append(tc)
            continue
        args = fn.get("arguments")
        if isinstance(args, str):
            try:
                decoded = _json.loads(args) if args else {}
            except (TypeError, ValueError):
                decoded = {}
            new_tool_calls.append({
                **tc,
                "function": {**fn, "arguments": decoded},
            })
        else:
            new_tool_calls.append(tc)
    return {**msg, "tool_calls": new_tool_calls}


class LocalLlamaAdapter(OpenAIAdapter):
    """In-process llama-cpp-python. Same wire shape as OpenAI; drift
    parser layered on top of :meth:`parse_response` because local
    chat templates routinely emit tool calls as text.

    Construction options:

      * ``model_path`` — path to the GGUF file. Required unless
        ``llama`` is injected.
      * ``llama`` — pre-loaded ``llama_cpp.Llama`` instance. Skip the
        path-based load entirely; useful when one model serves multiple
        agents or unit tests inject a stub.
      * ``llama_kwargs`` — overrides for the ``Llama`` constructor
        (``n_ctx``, ``n_gpu_layers``, …). Defaults match the legacy
        :class:`jaeger_os.core.models.llm_client.LlamaCppPythonClient` so
        benchmarks compare apples to apples.
      * Everything else (``model``, ``max_tokens``, ``temperature``)
        flows to :class:`OpenAIAdapter` unchanged.
    """

    def __init__(
        self,
        *,
        model: str = "local",
        model_path: str | Path | None = None,
        llama: Any = None,
        llama_kwargs: dict[str, Any] | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.0,
        top_p: float = 0.95,
        enable_thinking: bool | None = None,
    ) -> None:
        # Skip OpenAIAdapter's network kwargs entirely — we never talk
        # to an HTTP endpoint. Pass the bits that DO apply via super().
        super().__init__(
            provider="local-llama",
            model=model,
            api_key=None,
            base_url=None,
            max_tokens=max_tokens,
            temperature=temperature,
            top_p=top_p,
            client=None,
        )
        self.model_path = Path(model_path).expanduser() if model_path else None
        self.llama_kwargs = {**_LLAMA_DEFAULTS, **(llama_kwargs or {})}
        # Either an already-built Llama, or built on first use.
        self._llama = llama
        # Override the diagnostic name so /runtime shows the right label.
        self.name = "local-llama"
        # Whether to embed the tool catalogue in the system prompt using
        # the MODEL'S NATIVE dialect (on top of the structured ``tools=``
        # param). Default ON. See ``format_messages``.
        self.inject_tools_prose = True
        # Cached tool dialect ("chatml" / "mistral" / "llama3" / …),
        # resolved lazily on first ``format_messages``.
        self._tool_family: str | None = None
        # Cached reasoning flag (model emits <think> deliberation).
        self._is_reasoning: bool | None = None
        # Cloud-style ``thinking`` toggle. ``None`` = use the model's
        # default mode (current behaviour, unchanged). ``True``/``False``
        # = force ON or OFF — applied only when the model's chat template
        # actually exposes ``enable_thinking`` (a "hybrid" thinking model
        # like Qwen3.x or gemma-4). For non-hybrid models this flag is a
        # no-op; their behaviour is whatever the template defines.
        self._enable_thinking = enable_thinking
        # Cached chat template + hybrid flag, lazy on first
        # ``format_messages`` (when the Llama instance is available).
        self._chat_template_cache: str | None = None
        self._hybrid_thinking: bool | None = None
        # Cooperative-abort flag. Polled by the in-process generation via
        # ``stopping_criteria`` so a stalled / interrupted decode stops
        # cleanly at the next token rather than being abandoned mid-flight
        # (which corrupts the shared model's KV cache → cascade failures).
        self._abort_flag = threading.Event()

    # ── tool presentation ───────────────────────────────────────────

    def _resolve_tool_family(self) -> str:
        """Determine the model's native tool dialect from its name +
        embedded chat template. Cached after the first call.

        Principle: we match the model. Each family was trained on a
        specific tool dialect; we present tools in THAT dialect so the
        model never has to drift to a foreign format.
        """
        if self._tool_family is not None:
            return self._tool_family
        name = ""
        if self.model_path is not None:
            name = Path(self.model_path).stem
        template = ""
        # The embedded chat template lives in the Llama metadata once
        # the client is built. Read it if available; fall back to the
        # name alone otherwise (the name is usually enough).
        llama = self._llama
        meta = getattr(llama, "metadata", None) if llama is not None else None
        if isinstance(meta, dict):
            template = meta.get("tokenizer.chat_template", "") or ""
            if not name:
                name = meta.get("general.name", "") or ""
        self._tool_family = detect_family(name, template)
        self._is_reasoning = detect_reasoning(name, template)
        return self._tool_family

    def _resolve_reasoning(self) -> bool:
        """Whether this model emits ``<think>`` deliberation. Resolved
        alongside the tool family (same name+template signals)."""
        if self._is_reasoning is None:
            self._resolve_tool_family()  # populates both
        return bool(self._is_reasoning)

    def _chat_template_str(self) -> str:
        """Cached chat template from GGUF metadata. ``""`` when the
        model is injected (test stub with no metadata) or hasn't loaded
        yet."""
        if self._chat_template_cache is not None:
            return self._chat_template_cache
        try:
            llama = self._ensure_client()._llama  # type: ignore[attr-defined]
            meta = getattr(llama, "metadata", None) or {}
            self._chat_template_cache = meta.get(
                "tokenizer.chat_template", "") or ""
        except Exception:  # noqa: BLE001 — never block format_messages
            self._chat_template_cache = ""
        return self._chat_template_cache

    def _is_hybrid_thinking(self) -> bool:
        """A *hybrid* thinking model has a first-class ``enable_thinking``
        knob in its chat template (Qwen3.x, gemma-4) — the user can
        toggle reasoning ON or OFF per call, the way Claude / GPT-o1
        expose thinking. Always-reasoning models (DeepSeek-R1, Ministral-
        Reasoning) don't; their reasoning isn't disableable."""
        if self._hybrid_thinking is None:
            self._hybrid_thinking = "enable_thinking" in self._chat_template_str()
        return bool(self._hybrid_thinking)

    def _render_with_thinking(
        self,
        wire_messages: list[dict[str, Any]],
        wire_tools: list[dict[str, Any]] | None,
        enable_thinking: bool,
    ) -> str | None:
        """Render the model's own chat template with an explicit
        ``enable_thinking`` flag. Returns ``None`` if the template can't
        be loaded or rendering fails (caller falls back to the default
        path). Same renderer the sanity probe uses, kept in one place."""
        template_str = self._chat_template_str()
        if not template_str:
            return None
        try:
            import jinja2
            env = jinja2.Environment()
            env.globals["raise_exception"] = (
                lambda m: (_ for _ in ()).throw(Exception(m))
            )
            tmpl = env.from_string(template_str)
            return tmpl.render(
                messages=wire_messages,
                tools=wire_tools or None,
                add_generation_prompt=True,
                enable_thinking=enable_thinking,
            )
        except Exception:  # noqa: BLE001 — fall back to default rendering
            return None

    def format_messages(
        self,
        messages: list[Message],
        tools: list[ToolDef],
        system: str,
    ) -> dict[str, Any]:
        """Build the chat-completion kwargs, presenting tools through
        BOTH channels:

          1. The structured ``tools=`` param (parent OpenAIAdapter) —
             llama-cpp applies the model's chat template when its handler
             supports function-calling. This works for models whose GGUF
             template renders tools (Gemma-4, some Qwen).

          2. A NATIVE-DIALECT tool block embedded in the system prompt
             (this override, via :mod:`jaeger_os.agent.dialects`). Many GGUF
             builds ship templates with the tool section stripped (the
             LM Studio Hermes-3 build, verified), so the structured
             param silently no-ops and the model never sees the tools →
             it answers as a plain chatbot (the 3.9% flatlines in the
             2026-05-27 sweep).

        Crucially, the prose block is rendered in the MODEL'S OWN
        dialect — Hermes/Qwen get ``<tools>`` + ``<tool_call>``, Mistral
        gets ``[AVAILABLE_TOOLS]`` + ``[TOOL_CALLS]``, Llama gets the
        ``<|python_tag|>`` convention. We match the model; it never
        drifts to a format foreign to it. The drift parser reads back
        whatever native format it emits.

        Gemma + unknown families inject nothing here (their structured
        path works / we don't want to perturb a working model).
        """
        kwargs = super().format_messages(messages, tools, system)
        if not (self.inject_tools_prose and tools):
            return self._apply_thinking_toggle(kwargs)
        family = self._resolve_tool_family()
        addition = render_tools_for(family, tools)
        if not addition:
            # gemma/unknown → structured channel only — but they're
            # ALSO hybrid thinking (gemma-4 has ``enable_thinking`` in
            # its template), so the toggle still applies.
            return self._apply_thinking_toggle(kwargs)
        wire = kwargs.get("messages") or []
        for entry in wire:
            if entry.get("role") == "system":
                existing = entry.get("content") or ""
                entry["content"] = (
                    f"{existing}\n\n{addition}" if existing else addition
                )
                break
        else:
            wire.insert(0, {"role": "system", "content": addition})
        # Prose families are driven entirely as TEXT: rewrite tool-call
        # history into native in-dialect text turns and drop the
        # structured ``tools=`` param. Otherwise the conversation history
        # (assistant ``tool_calls`` + ``tool`` results) routes back
        # through the model's own GGUF tool template — which is fragile
        # and mutually incompatible across builds (DeepSeek-R1 crashes on
        # dict args / None content; Hermes builds strip the tool section).
        # We presented the catalogue as prose, so the structured channel
        # is redundant here. Gemma already returned above (its handler
        # works), so reaching this point means a text-driven family.
        kwargs["messages"] = textify_tool_history(wire, family)
        kwargs.pop("tools", None)
        kwargs.pop("tool_choice", None)
        return self._apply_thinking_toggle(kwargs)

    def _apply_thinking_toggle(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        """Cloud-style think ON/OFF toggle (Claude / GPT-o1 style).

        Only fires when the caller set ``enable_thinking`` AND the model
        is a hybrid (template exposes the knob — Qwen3.x, gemma-4). For
        non-hybrid models this is a no-op, so default behaviour is
        UNCHANGED. A successful manual render stashes the rendered
        prompt for the facade to pick up via ``create_completion``;
        a failed render falls through to the default path silently."""
        if self._enable_thinking is None:
            return kwargs
        if not self._is_hybrid_thinking():
            return kwargs
        rendered = self._render_with_thinking(
            kwargs.get("messages") or [],
            kwargs.get("tools"),
            bool(self._enable_thinking),
        )
        if rendered is not None:
            kwargs["_thinking_prompt"] = rendered
        return kwargs

    # ── client lifecycle ────────────────────────────────────────────

    def _ensure_client(self) -> Any:
        """Build (or reuse) the ``Llama`` instance, wrap it in the
        chat-completions facade, and cache for subsequent calls.

        Heavy: the first call loads the GGUF off disk and warms the
        graph. Make sure the agent loop calls this once per adapter
        lifetime, not once per turn — that's why ``self._client``
        caches the facade.
        """
        if self._client is not None:
            return self._client
        if self._llama is None:
            if self.model_path is None:
                raise ValueError(
                    "LocalLlamaAdapter needs either ``model_path`` or a "
                    "pre-loaded ``llama`` instance."
                )
            from llama_cpp import Llama
            if not self.model_path.exists():
                raise FileNotFoundError(f"GGUF not found: {self.model_path}")
            self._llama = Llama(
                model_path=str(self.model_path),
                **self.llama_kwargs,
            )
        self._client = _LlamaChatFacade(self._llama, self._abort_flag)
        return self._client

    # ── in-process call (override the inherited HTTP version) ───────

    def call(
        self,
        formatted: Any,
        interrupt_event: Any,
        *,
        stale_timeout: float | None = None,
        on_heartbeat: Any = None,
        **kwargs: Any,
    ) -> Any:
        """In-process call with a **caller-controlled stall watchdog**
        and **cooperative cancellation**.

        The old posture abandoned the worker thread on a stall: the
        llama-cpp decode kept running on the shared model, leaving a
        half-decoded KV cache that produced ``llama_decode -1/-3`` on
        every subsequent call (the 2026-05-28 Hermes-3 full-corpus
        cascade — one stalled case poisoned 42 more).

        New posture — cooperative abort:

          * Generation polls ``self._abort_flag`` via llama-cpp's
            ``stopping_criteria`` (wired in the facade). When the stall
            watchdog fires, ``interruptible_call`` calls ``on_abandon``
            → we SET the flag → the decode stops cleanly at the next
            token, the worker returns, and the shared model is left in a
            normal post-generation state. ``join_on_abandon`` waits for
            that to happen before control returns, so the NEXT call
            starts from a clean instance. No zombie, no cascade.

          * The interrupt event is still uncancellable here — Ctrl-C
            tear-down is handled at the loop boundary — but the abort
            flag means even an abandoned stall no longer corrupts state.
        """
        # Reasoning models legitimately deliberate for minutes; raise
        # the watchdog floor so it doesn't fire mid-think.
        if (
            stale_timeout is not None
            and self._resolve_reasoning()
            and stale_timeout < _REASONING_STALL_FLOOR_S
        ):
            stale_timeout = _REASONING_STALL_FLOOR_S
        # Fresh decode → clear any abort signal left over from a prior
        # stalled turn so this generation isn't stopped at token 0. We
        # clear at the START (not in a ``finally``): if a stall abandons
        # the worker after the join cap, the flag must stay SET so that
        # worker still stops at its next token instead of running on as
        # a zombie that corrupts the shared KV cache.
        self._abort_flag.clear()
        uncancellable_event = threading.Event()
        try:
            return super().call(
                formatted,
                uncancellable_event,
                stale_timeout=stale_timeout,
                on_heartbeat=on_heartbeat,
                # Stop generation cleanly on stall; wait briefly for the
                # worker to finish so the shared model stays usable.
                on_abandon=self._abort_flag.set,
                join_on_abandon=_ABORT_JOIN_S,
                **kwargs,
            )
        except (StaleCallTimeout, AgentInterrupted):
            # The decode was aborted mid-generation. Even after the
            # worker stops, llama-cpp's internal batch/KV state is left
            # crash-prone — the NEXT decode segfaults the process (the
            # 2026-05-28 Hermes-3 full-corpus crash at case 8). Reset the
            # context so the next case starts from a clean slate.
            self._reset_after_abort()
            raise

    def _reset_after_abort(self) -> None:
        """Bring the shared llama-cpp instance back to a clean state
        after an aborted decode. Best-effort: ``reset()`` clears the KV
        cache + token count; if the instance is wedged beyond that, drop
        it so the next call rebuilds from the GGUF (only possible when a
        ``model_path`` is known)."""
        llama = self._llama
        try:
            if llama is not None and hasattr(llama, "reset"):
                llama.reset()
                return
        except Exception:  # noqa: BLE001 — fall through to a full reload
            pass
        if self.model_path is not None:
            # Drop the poisoned instance; _ensure_client rebuilds lazily.
            self._llama = None
            self._client = None

    # ── parse with drift fallback ───────────────────────────────────

    def parse_response(self, raw: Any) -> Message:
        """Decode the chat-completions response, then merge any
        text-format tool calls salvaged by the drift parser.

        Why both: llama-cpp's chat handler may parse some calls into the
        structured ``tool_calls`` field while leaving others as raw text
        (template quirks vary per model — Gemma 4 in particular). The
        union is what the model actually intended; the agent loop
        dispatches both equally.
        """
        message = super().parse_response(raw)
        text = message.get("content") or ""
        # gpt-oss harmony: llama-cpp's handler returns the raw 3-channel
        # text (analysis / commentary / final) without parsing it. Pull
        # tool calls off the commentary channel and the answer off the
        # final channel, dropping the analysis (reasoning) channel. The
        # ``<|channel|>`` marker is harmony-specific, so this never fires
        # for other dialects.
        if "<|channel|>" in text:
            from jaeger_os.agent.dialects import parse_harmony
            harmony_calls, harmony_answer = parse_harmony(text)
            if harmony_calls:
                existing = list(message.get("tool_calls") or [])
                existing.extend(harmony_calls)
                message["tool_calls"] = existing
                message["content"] = harmony_answer or None
                return message
            message["content"] = harmony_answer or None
            return message
        # Reasoning models emit ``<think>…</think>`` deliberation BEFORE
        # the answer / tool call. Strip it first so (a) the drift parser
        # doesn't try to read tool calls out of the reasoning, and (b)
        # the visible answer isn't a wall of internal monologue. The
        # actual tool call (if any) comes after ``</think>``.
        if "<think>" in text:
            stripped = strip_think_blocks(text)
            message["content"] = stripped or None
            text = stripped
        # Cheap pre-filter: skip the drift parser only when the text
        # can't possibly hold a tool call. A tool call always contains
        # either an angle-bracket envelope (``<tool_call>``,
        # ``<|python_tag|>``) or a JSON object (bare ``{"name": …}``,
        # Gemma braces, or Mistral's bare ``name{json}``). So anything
        # with neither ``<`` nor ``{`` is plain prose — skip it; let
        # ``extract_tool_calls`` be the single decision point otherwise.
        # (The old guard required a ``"name"`` key and so silently
        # dropped DeepSeek-R1's bare JSON and Ministral's ``name{}``.)
        if "<" not in text and "{" not in text:
            return message
        salvaged = extract_tool_calls(text)
        if not salvaged:
            return message
        # Strip the envelopes from the visible text so the loop doesn't
        # echo the markup back to the user on the final answer.
        cleaned = self._strip_tool_call_blocks(text).strip()
        # Bare-JSON tool calls (no envelope) aren't removed by the
        # envelope stripper — so when the cleaned remainder is itself
        # just a tool-call JSON object, null it. Otherwise the model's
        # raw ``{"name": …}`` would surface as the visible "answer".
        if cleaned.startswith("{") and (
            '"name"' in cleaned or '"tool_name"' in cleaned
        ):
            cleaned = ""
        message["content"] = cleaned or None
        existing = list(message.get("tool_calls") or [])
        existing.extend(salvaged)
        message["tool_calls"] = existing
        return message

    @staticmethod
    def _strip_tool_call_blocks(text: str) -> str:
        """Remove every ``<tool_call>`` / ``<|tool_call|>`` envelope
        from the response text. Mirrors :class:`HermesXMLAdapter`'s
        helper — kept here so the local-llama and Hermes-XML paths
        agree on the visible-text contract."""
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

    # ── capabilities + diagnostics ──────────────────────────────────

    def supports(self, feature: str) -> bool:
        # llama-cpp's chat handlers vary per-model on parallel tool
        # calling; the drift parser handles the multi-call case from
        # text either way. Report only what the wire format guarantees.
        if feature == "streaming":
            return self.streaming
        return False

    def health_check(self) -> dict[str, Any]:
        """In-process — if the ``Llama`` is loaded, we're reachable."""
        try:
            self._ensure_client()
            return {"ok": True, "detail": "model loaded", "latency_s": 0.0}
        except Exception as exc:  # noqa: BLE001
            return {
                "ok": False,
                "detail": f"{type(exc).__name__}: {exc}"[:200],
                "latency_s": 0.0,
            }

    def describe(self) -> str:
        path = self.model_path.name if self.model_path else self.model
        return f"local-llama · {path}"


__all__ = ["LocalLlamaAdapter"]
