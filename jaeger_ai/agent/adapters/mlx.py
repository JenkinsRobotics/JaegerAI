"""``MLXAdapter`` — in-process Apple MLX (mlx-lm), rebuilt for parity
with :class:`LocalLlamaAdapter`.

The first MLX attempt lagged llama.cpp for two specific reasons, both
fixed here:

  1. **Tools weren't called correctly.** The old adapter inherited
     :class:`HermesXMLAdapter`: every model got hardcoded ChatML
     ``<|im_start|>`` markers and Hermes-XML tool prose, regardless of
     what it was trained on. A Gemma/Llama/Mistral MLX build saw a
     foreign chat template AND a foreign tool dialect — drift city.
     Now the prompt renders through the model's OWN chat template
     (``tokenizer.apply_chat_template``) and tools are presented in
     the model's native dialect via :mod:`jaeger_os.agent.dialects`
     (``detect_family`` + ``render_tools_for`` + ``textify_tool_history``
     — the same machinery that fixed the llama.cpp path).

  2. **Turns didn't end when the answer did.** ``mlx_lm.generate`` has
     no ``stop`` parameter, and the old adapter dropped stop sequences
     on the floor — every call ran to the full ``max_tokens`` budget
     (4096) after the model had finished talking. Now generation runs
     through ``mlx_lm.stream_generate`` with OUR loop watching for the
     family's stop markers: the moment ``<|im_end|>`` /
     ``<end_of_turn>`` / ``<|eot_id|>`` appears, generation stops.
     The same loop gives per-token progress (no-progress stall
     watchdog + real TTFT), live ``on_delta`` text for TTS, and
     cooperative interrupts (barge-in breaks the loop at the next
     token — no zombie generation).

mlx-lm is imported **lazily** — the package isn't a hard dependency,
so importing this module on a non-Apple-Silicon host must not raise.
Tests inject a ``runner`` to bypass the import entirely; production
injects the already-loaded ``model``/``tokenizer`` pair from
:class:`jaeger_os.core.models.mlx_client.MlxClient` so weights load
once, not twice.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable

from jaeger_ai.agent.dialects import (
    detect_family,
    detect_reasoning,
    extract_tool_calls,
    render_tools_for,
    strip_reasoning_channels,
    strip_think_blocks,
    textify_tool_history,
)
from jaeger_ai.agent.loop.interrupt import (
    AgentInterrupted,
    CallProgress,
    interruptible_call,
)
from jaeger_ai.agent.schemas.message_types import Message, ToolCall
from jaeger_os.core.tools.tool_schema import ToolDef
from .base import ProviderAdapter
from .hermes_xml import HERMES_TOOL_INSTRUCTIONS, _render_tools_block

_FEATURES: frozenset[str] = frozenset()

# Sampling defaults handed to mlx-lm. ``max_tokens`` is the per-call
# generation ceiling — the stop-sequence loop usually ends generation
# long before it's reached.
_MLX_DEFAULTS: dict[str, Any] = {
    "max_tokens": 4096,
}

# Per-family end-of-turn markers the stream loop watches for, on top of
# the tokenizer's own EOS handling. A family missing here just relies
# on EOS — worst case is the old run-to-budget behaviour, never breakage.
_FAMILY_STOPS: dict[str, tuple[str, ...]] = {
    "chatml": ("<|im_end|>",),
    "qwen": ("<|im_end|>",),
    "hermes": ("<|im_end|>",),
    "llama3": ("<|eot_id|>", "<|end_of_text|>"),
    "gemma": ("<end_of_turn>",),
    "mistral": ("</s>",),
    "harmony": ("<|return|>", "<|call|>"),
}
_DEFAULT_STOPS: tuple[str, ...] = ("<|im_end|>",)


class MLXAdapter(ProviderAdapter):
    """In-process MLX adapter — native chat template, native tool
    dialect, early stop, streamed progress.

    Construction options:

      * ``model`` / ``tokenizer`` — an already-loaded ``mlx_lm`` pair
        (the production path: :class:`MlxClient` loaded them at boot;
        don't pay the load twice).
      * ``model_path`` — HF repo id or local MLX directory; loaded
        lazily on first call when no pair was injected.
      * ``runner`` — ``(prompt, kwargs) -> str`` closure for tests; the
        streaming machinery is bypassed and stop sequences are
        post-trimmed.
      * ``defaults`` — kwargs merged into every generation call
        (``max_tokens`` etc.); per-call kwargs win.
      * ``inject_tool_instructions`` — embed the tool catalogue in the
        system prompt (default on; MLX has NO structured tools channel,
        so turning this off means the model never sees tools).
      * ``stop_sequences`` — extra stop markers on top of the family's.
    """

    name = "mlx"

    def __init__(
        self,
        *,
        model: Any = None,
        tokenizer: Any = None,
        model_name: str = "",
        model_path: str | None = None,
        runner: Callable[[str, dict[str, Any]], str] | None = None,
        defaults: dict[str, Any] | None = None,
        inject_tool_instructions: bool = True,
        stop_sequences: tuple[str, ...] = (),
        mlx_executor: Any = None,
        is_vlm: bool = False,
        vlm_config: Any = None,
    ) -> None:
        self._model = model
        self._tokenizer = tokenizer
        self.model_path = model_path
        # mlx-vlm path: the multimodal/unified MLX models that text-only
        # mlx-lm can't load. ``_tokenizer`` is then an mlx-vlm processor
        # and generation runs through ``mlx_vlm`` (separate, incompatible
        # ``stream_generate`` + chat-template entry points). ``vlm_config``
        # is the model's loaded config.json, needed by mlx-vlm's template.
        self._is_vlm = bool(is_vlm)
        self._vlm_config = vlm_config
        self.model_name = model_name or (model_path or "mlx")
        self._explicit_runner = runner
        # Single-worker executor that owns the MLX thread (model load +
        # warmup + every generation). MLX pins GPU streams per-thread, so
        # decode MUST run here, not on a fresh interruptible_call thread.
        self._mlx_executor = mlx_executor
        self.defaults = {**_MLX_DEFAULTS, **(defaults or {})}
        self.inject_tool_instructions = bool(inject_tool_instructions)
        self.extra_stop_sequences = tuple(stop_sequences)
        # Resolved lazily from the model name + chat template — drives
        # the tool-prose dialect, the history textification, and the
        # stop markers.
        self._tool_family: str | None = None
        self._is_reasoning: bool | None = None
        # Per-token progress beacon (stall watchdog + TTFT), reset per
        # call — same contract as LocalLlamaAdapter.
        self._progress = CallProgress()
        # Diagnostics for /runtime + tests.
        self.last_raw_response: str | None = None
        self.last_usage: dict[str, Any] | None = None
        self.last_ttft_s: float | None = None

    # ── family / template plumbing ──────────────────────────────────

    def _chat_template_str(self) -> str:
        tok = self._tokenizer
        if tok is None:
            return ""
        template = getattr(tok, "chat_template", "") or ""
        return template if isinstance(template, str) else ""

    def _resolve_tool_family(self) -> str:
        if self._tool_family is None:
            name = self.model_name or self.model_path or ""
            template = self._chat_template_str()
            self._tool_family = detect_family(name, template)
            self._is_reasoning = detect_reasoning(name, template)
        return self._tool_family

    def _stops(self) -> tuple[str, ...]:
        family = self._resolve_tool_family()
        stops = _FAMILY_STOPS.get(family, _DEFAULT_STOPS)
        return tuple(dict.fromkeys((*stops, *self.extra_stop_sequences)))

    # ── conversion ──────────────────────────────────────────────────

    def format_messages(
        self,
        messages: list[Message],
        tools: list[ToolDef],
        system: str,
    ) -> dict[str, Any]:
        """Build the wire-message list, tools presented in the MODEL'S
        OWN dialect.

        MLX is text-completion only — there is no structured ``tools=``
        channel — so the prose block in the system prompt is the ONLY
        way the model learns its tools. Families without a native
        prose renderer (gemma/unknown) fall back to the Hermes-XML
        instruction block rather than getting nothing (the old
        adapter's bug class #1)."""
        family = self._resolve_tool_family()

        system_parts: list[str] = []
        if system:
            system_parts.append(system)
        if self.inject_tool_instructions and tools:
            addition = render_tools_for(family, tools)
            if not addition:
                addition = (
                    HERMES_TOOL_INSTRUCTIONS.strip()
                    + "\n\n" + _render_tools_block(tools)
                )
            system_parts.append(addition)

        wire: list[dict[str, Any]] = []
        if system_parts:
            wire.append({
                "role": "system", "content": "\n\n".join(system_parts),
            })
        for m in messages:
            role = m.get("role")
            if role == "system":
                extra = m.get("content") or ""
                if extra and wire and wire[0]["role"] == "system":
                    wire[0]["content"] += f"\n\n{extra}"
                elif extra:
                    wire.insert(0, {"role": "system", "content": extra})
                continue
            entry: dict[str, Any] = {
                "role": role, "content": m.get("content"),
            }
            if m.get("tool_calls"):
                entry["tool_calls"] = m["tool_calls"]
            if m.get("tool_call_id"):
                entry["tool_call_id"] = m["tool_call_id"]
            wire.append(entry)

        # Tool history rides as native in-dialect TEXT — most chat
        # templates either crash on tool-role messages or render them
        # in a format the model wasn't trained on. ``textify`` keeps
        # the transcript in the same dialect the prose block taught.
        wire = textify_tool_history(
            wire, family if family in _FAMILY_STOPS else "chatml",
        )
        return {"messages": wire, "stop": list(self._stops())}

    def _render_prompt(self, wire: list[dict[str, Any]]) -> str:
        """The model's OWN chat template when a tokenizer is available
        (production); a plain ChatML rendering otherwise (injected
        test runners)."""
        # mlx-vlm models render through mlx-vlm's own chat-template helper
        # (the processor + config.json), not a bare tokenizer call.
        if self._is_vlm and self._tokenizer is not None:
            try:
                from mlx_vlm.prompt_utils import apply_chat_template as _vlm_tpl
                return _vlm_tpl(
                    self._tokenizer, self._vlm_config, wire,
                    add_generation_prompt=True, num_images=0,
                )
            except Exception:  # noqa: BLE001 — fall through to generic render
                pass
        tok = self._tokenizer
        if tok is not None and not self._is_vlm and hasattr(tok, "apply_chat_template"):
            try:
                return tok.apply_chat_template(
                    wire, add_generation_prompt=True, tokenize=False,
                )
            except Exception:  # noqa: BLE001 — fall through to plain render
                pass
        chunks = [
            f"<|im_start|>{m.get('role', 'user')}\n{m.get('content') or ''}"
            f"\n<|im_end|>"
            for m in wire
        ]
        chunks.append("<|im_start|>assistant\n")
        return "\n".join(chunks)

    # ── call ────────────────────────────────────────────────────────

    def _ensure_loaded(self) -> tuple[Any, Any]:
        if self._model is None or self._tokenizer is None:
            if self.model_path is None:
                raise ValueError(
                    "MLXAdapter needs ``model``+``tokenizer``, a "
                    "``model_path``, or an explicit ``runner``."
                )
            from mlx_lm import load
            self._model, self._tokenizer = load(self.model_path)
            # Template just became available — re-resolve the family.
            self._tool_family = None
        return self._model, self._tokenizer

    def call(
        self,
        formatted: Any,
        interrupt_event: threading.Event,
        *,
        stale_timeout: float | None = None,
        on_heartbeat: Any = None,
        on_delta: Any = None,
        **kwargs: Any,
    ) -> Any:
        """One generation, streamed token-by-token under OUR loop.

        The loop is what fixes bug class #2: generation ENDS the moment
        a family stop marker (or tokenizer EOS) appears, instead of
        running out the whole ``max_tokens`` budget. It also feeds the
        per-token progress beacon (so ``stale_timeout`` is a true
        no-token-gap watchdog), emits ``on_delta`` text for live
        consumers, and honours interrupts at token boundaries —
        breaking out of a pull-based generator is a clean stop, so no
        cooperative-abort flag is needed (unlike llama.cpp's shared
        KV cache)."""
        merged = {**(formatted or {}), **kwargs}
        wire = merged.pop("messages", [])
        stops = tuple(merged.pop("stop", ()) or self._stops())
        raw_params = {
            k: v for k, v in {**self.defaults, **merged}.items()
            if k in ("max_tokens", "temp", "top_p", "repetition_penalty")
            and v is not None
        }

        self._progress.reset()
        self.last_ttft_s = None
        started = time.perf_counter()

        # Injected test runner: plain text path, stop post-trimmed.
        if self._explicit_runner is not None:
            prompt = self._render_prompt(wire)
            raw = interruptible_call(
                lambda: self._explicit_runner(prompt, dict(raw_params)),
                interrupt_event,
                stale_timeout=stale_timeout,
                on_heartbeat=on_heartbeat,
                progress=self._progress,
            )
            text, _hit = _cut_at_stop(str(raw or ""), stops)
            self.last_raw_response = text
            return {"text": text, "finish_reason": "stop" if _hit else None}

        model, tokenizer = self._ensure_loaded()
        prompt = self._render_prompt(wire)
        progress = self._progress
        # mlx-lm ≥0.21 takes sampling via ``sampler=``, not bare
        # ``temp=`` kwargs — passing those through silently diverges
        # (or TypeErrors, version-dependent) from the llama.cpp
        # backend's sampling. Build the sampler explicitly; warn when
        # the helper is unavailable instead of silently ignoring.
        gen_kwargs: dict[str, Any] = {}
        if raw_params.get("max_tokens") is not None:
            gen_kwargs["max_tokens"] = raw_params["max_tokens"]
        sampler = _make_sampler(
            raw_params.get("temp"), raw_params.get("top_p"),
        )
        if sampler is not None:
            gen_kwargs["sampler"] = sampler

        def _stream() -> dict[str, Any]:
            # mlx-vlm and mlx-lm both yield ``GenerationResult`` objects
            # with ``.text`` / ``.finish_reason`` / token counts, so the
            # scanner loop below is identical — only the generator source
            # and its kwargs differ. mlx-vlm doesn't take the mlx-lm
            # ``sampler`` object, so the VLM path passes plain kwargs.
            if self._is_vlm:
                from mlx_vlm import stream_generate as _stream_gen
                vlm_kwargs: dict[str, Any] = {}
                if raw_params.get("max_tokens") is not None:
                    vlm_kwargs["max_tokens"] = raw_params["max_tokens"]
                if raw_params.get("temp") is not None:
                    vlm_kwargs["temperature"] = raw_params["temp"]
                chunk_iter = _stream_gen(model, tokenizer, prompt=prompt, **vlm_kwargs)
            else:
                from mlx_lm import stream_generate as _stream_gen
                chunk_iter = _stream_gen(model, tokenizer, prompt=prompt, **gen_kwargs)
            pieces: list[str] = []
            pending = ""
            finish: str | None = None
            usage: dict[str, Any] = {}
            for chunk in chunk_iter:
                piece = getattr(chunk, "text", "") or ""
                progress.touch()
                if piece:
                    # Holdback scanner: deltas are emitted ONLY once
                    # they can no longer be part of a stop marker, so
                    # a marker split across chunks never leaks its
                    # head into the delta stream (→ TTS).
                    emit, pending, stopped = _scan_stream_text(
                        pending, piece, stops,
                    )
                    if emit:
                        pieces.append(emit)
                        if on_delta is not None:
                            on_delta(emit)
                    if stopped:
                        finish = "stop"
                        break
                if interrupt_event.is_set():
                    raise AgentInterrupted("interrupted mid-generation")
                chunk_finish = getattr(chunk, "finish_reason", None)
                if chunk_finish:
                    finish = chunk_finish
                # Best-effort token accounting (newer mlx-lm exposes
                # these on each GenerationResponse).
                for attr, key in (
                    ("prompt_tokens", "prompt_tokens"),
                    ("generation_tokens", "completion_tokens"),
                ):
                    val = getattr(chunk, attr, None)
                    if isinstance(val, int):
                        usage[key] = val
            if pending and finish != "stop":
                # Stream ended on a held-back run that never became a
                # marker — it's real text; flush it.
                pieces.append(pending)
                if on_delta is not None:
                    on_delta(pending)
            return {
                "text": "".join(pieces),
                "finish_reason": finish,
                "usage": usage,
            }

        raw = interruptible_call(
            _stream,
            interrupt_event,
            stale_timeout=stale_timeout,
            on_heartbeat=on_heartbeat,
            progress=progress,
            executor=self._mlx_executor,
        )
        if progress.first is not None:
            self.last_ttft_s = max(0.0, progress.first - started)
        usage = raw.get("usage") if isinstance(raw, dict) else None
        if usage:
            self.last_usage = dict(usage)
        return raw

    # ── parse ───────────────────────────────────────────────────────

    def parse_response(self, raw: Any) -> Message:
        """Decode generated text → internal ``Message``, through the
        same drift pipeline the llama.cpp path uses: think-block strip,
        native-dialect tool-call extraction, envelope cleanup, and
        thinking-exhaustion tagging."""
        if isinstance(raw, dict):
            text = str(raw.get("text") or "")
            finish = raw.get("finish_reason")
        else:
            text = str(raw or "")
            finish = None
        self.last_raw_response = text

        had_think = "<think>" in text
        if had_think:
            text = strip_think_blocks(text)
        # Gemma 4 leaks malformed reasoning-channel markers
        # (``<|channel>thought\n<channel|>…``); strip them so the answer
        # surfaces clean instead of as a phantom "thought".
        if "channel" in text.lower():
            text = strip_reasoning_channels(text)

        tool_calls: list[ToolCall] = extract_tool_calls(text)
        cleaned = _strip_tool_envelopes(text).strip()
        if tool_calls and cleaned.startswith("{") and (
            '"name"' in cleaned or '"tool_name"' in cleaned
        ):
            cleaned = ""

        message: Message = {"role": "assistant", "content": cleaned or None}
        if tool_calls:
            message["tool_calls"] = tool_calls
        if finish == "length" or (
            finish is None and not cleaned and not tool_calls and had_think
        ):
            # A reasoning model that burned the budget inside <think>
            # without surfacing an answer — tag it so the loop reports
            # plainly instead of nudging for more thinking.
            if had_think and not cleaned and not tool_calls:
                message["finish_reason"] = "thinking_exhausted"
            elif finish:
                message["finish_reason"] = finish
        elif finish:
            message["finish_reason"] = finish
        return message

    # ── capabilities + diagnostics ──────────────────────────────────

    def supports(self, feature: str) -> bool:
        return feature in _FEATURES

    def health_check(self) -> dict[str, Any]:
        try:
            if self._explicit_runner is not None:
                self._explicit_runner("", {})
            else:
                self._ensure_loaded()
            return {"ok": True, "detail": "model loaded", "latency_s": 0.0}
        except Exception as exc:  # noqa: BLE001 — probe must never raise
            return {
                "ok": False,
                "detail": f"{type(exc).__name__}: {exc}"[:200],
                "latency_s": 0.0,
            }

    def describe(self) -> str:
        target = self.model_name or self.model_path or "runner"
        return f"mlx · {target}"


def _make_sampler(temp: Any, top_p: Any) -> Any:
    """Build an mlx-lm sampler for the given knobs, or ``None`` when no
    knobs were set / the helper is unavailable. The unavailable case
    WARNS — silently ignoring temperature diverges from the llama.cpp
    backend's behaviour for the same config (VoiceLLM field lesson)."""
    knobs: dict[str, Any] = {}
    if temp is not None:
        knobs["temp"] = float(temp)
    if top_p is not None:
        knobs["top_p"] = float(top_p)
    if not knobs:
        return None
    try:
        from mlx_lm.sample_utils import make_sampler
        return make_sampler(**knobs)
    except Exception as exc:  # noqa: BLE001 — degrade loudly, not silently
        print(
            f"[mlx] sampler unavailable ({exc}) — temperature/top_p "
            "ignored, using mlx-lm defaults",
            flush=True,
        )
        return None


def _scan_stream_text(
    pending: str, text: str, stops: tuple[str, ...],
) -> tuple[str, str, bool]:
    """Scan ``pending + text`` for stop markers. Returns
    ``(emit, new_pending, stopped)``.

    Any trailing run that is a PREFIX of a marker is held back in
    ``new_pending`` rather than emitted — a marker straddling two
    stream deltas otherwise leaks its already-emitted head
    (``<end_of``) into the delta stream, which TTS reads aloud
    (VoiceLLM field bug, ported with its fix). The caller flushes a
    leftover ``pending`` when the stream ends without a marker."""
    out = pending + text
    idxs = [i for i in (out.find(m) for m in stops) if i != -1]
    if idxs:
        return out[:min(idxs)], "", True
    max_holdback = max((len(m) for m in stops), default=1) - 1
    for k in range(min(len(out), max_holdback), 0, -1):
        suffix = out[-k:]
        if any(m.startswith(suffix) for m in stops):
            return out[:-k], suffix, False
    return out, "", False


def _cut_at_stop(text: str, stops: tuple[str, ...]) -> tuple[str, bool]:
    """Trim ``text`` at the earliest stop marker. Returns
    ``(trimmed, hit)``."""
    earliest = -1
    for s in stops:
        idx = text.find(s)
        if idx >= 0 and (earliest < 0 or idx < earliest):
            earliest = idx
    if earliest >= 0:
        return text[:earliest], True
    return text, False


def _strip_tool_envelopes(text: str) -> str:
    """Remove ``<tool_call>``-style envelopes from the visible text —
    same patterns as the llama.cpp path so the two local backends agree
    on the visible-text contract.

    Gemma's envelopes go through the dialect's ``NATIVE_PATTERNS`` so the
    inner ``<|"|>`` quote markers don't defeat the strip (the old
    ``call:[^<]*`` regex stopped at the first ``<`` and leaked the block)."""
    import re
    from jaeger_ai.agent.dialects import gemma
    out = text
    for pat in gemma.NATIVE_PATTERNS:
        out = pat.sub("", out)
    for p in (
        r"<tool_call>\s*.*?\s*</tool_call>",
        r"\[TOOL_CALLS\]\s*\[.*?\]",
    ):
        out = re.sub(p, "", out, flags=re.DOTALL)
    return out


__all__ = ["MLXAdapter"]
