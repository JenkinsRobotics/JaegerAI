"""``MLXAdapter`` — in-process Apple MLX (mlx-lm).

mlx-lm's ``generate`` is a text-completion API, not chat-completion —
no structured ``tools`` parameter, no JSON ``tool_calls`` field on the
response. So the adapter rides the same shape as
:class:`HermesXMLAdapter`: prompt assembled as Hermes XML, the model
returns text, the drift parser pulls ``<tool_call>`` blocks back out.

Why a separate class instead of just using ``HermesXMLAdapter`` with an
``mlx_lm.generate`` runner: identity matters for the ``/runtime`` panel
and the model-picker history, and the MLX path has a couple of
backend-specific knobs (sampler config, the chat-template render via
the tokenizer's ``apply_chat_template``) that are worth surfacing
explicitly instead of hiding behind a generic runner.

mlx-lm is imported **lazily** — the package isn't a hard dependency,
so importing this module on a non-Apple-Silicon host (or a host without
``mlx_lm`` installed) must not raise. ``_ensure_runner`` does the
import on first call; tests inject the runner directly to bypass.
"""

from __future__ import annotations

from typing import Any, Callable

from .hermes_xml import HermesXMLAdapter


# mlx-lm's ``generate`` signature varies slightly across versions.
# ``max_tokens`` was renamed from ``max_new_tokens`` somewhere around
# 0.20; both names are accepted in current releases. We normalise to
# ``max_tokens`` on the wire and let the runner translate if needed.
_MLX_DEFAULTS: dict[str, Any] = {
    "max_tokens": 4096,
    "temp": 0.0,
    "top_p": 0.95,
    "repetition_penalty": None,
}


def _build_mlx_runner(
    model_path: str,
    *,
    defaults: dict[str, Any],
) -> Callable[[str, dict[str, Any]], str]:
    """Load the model + tokenizer once, return a closure the adapter
    can call as ``runner(prompt, kwargs) -> str``.

    Heavy on first call: ``mlx_lm.load`` reads weights off disk and
    converts to the MLX in-memory layout. Cache the loaded pair inside
    the closure so subsequent calls are cheap.
    """
    from mlx_lm import generate, load
    model, tokenizer = load(model_path)

    def _runner(prompt: str, kw: dict[str, Any]) -> str:
        params = {**defaults, **kw}
        # mlx-lm accepts ``max_tokens`` natively now; the legacy
        # ``max_new_tokens`` would land in **kw via the agent loop's
        # passthrough, so accept both for forward / backward compat.
        if "max_new_tokens" in params and "max_tokens" not in params:
            params["max_tokens"] = params.pop("max_new_tokens")
        # Stop sequences are tokenizer-applied; mlx-lm doesn't yet take
        # a ``stop`` kwarg, so let the caller post-trim if needed.
        params.pop("stop", None)
        return generate(model, tokenizer, prompt=prompt, **params)

    return _runner


class MLXAdapter(HermesXMLAdapter):
    """In-process MLX text-completion adapter.

    Construction options:

      * ``model_path`` — Hugging Face repo id or local path mlx-lm can
        load. Required unless ``runner`` is injected.
      * ``runner`` — pre-built ``(prompt, kwargs) -> str`` closure (e.g.
        a unit-test stub, or a runner that wraps ``mlx_lm.stream_generate``
        with token-level callbacks). When provided, ``model_path`` is
        ignored.
      * ``defaults`` — kwargs passed to ``mlx_lm.generate`` (``max_tokens``,
        ``temp``, ``top_p``). Merged with the agent loop's per-call kwargs;
        per-call wins.
      * ``inject_tool_instructions`` — same flag as :class:`HermesXMLAdapter`.
    """

    def __init__(
        self,
        *,
        model_path: str | None = None,
        runner: Callable[[str, dict[str, Any]], str] | None = None,
        defaults: dict[str, Any] | None = None,
        inject_tool_instructions: bool = True,
        stop_sequences: tuple[str, ...] = ("<|im_end|>",),
    ) -> None:
        # We override the runner the parent expects — but because the
        # underlying ``mlx_lm`` load is heavy, defer it to first call
        # by passing a lazy proxy.
        self.model_path = model_path
        self.defaults = {**_MLX_DEFAULTS, **(defaults or {})}
        self._explicit_runner = runner
        super().__init__(
            runner=self._lazy_runner,
            name="mlx",
            stop_sequences=stop_sequences,
            inject_tool_instructions=inject_tool_instructions,
        )

    def call(
        self,
        formatted: Any,
        interrupt_event: Any,
        *,
        stale_timeout: float | None = None,
        on_heartbeat: Any = None,
        **kwargs: Any,
    ) -> Any:
        """In-process MLX call — ``stale_timeout`` is forced to ``None``
        because abandoning the worker thread mid-``mlx_lm.generate``
        leaves the model state half-mutated; the next call then errors.
        Same reasoning as :class:`LocalLlamaAdapter.call`."""
        return super().call(
            formatted,
            interrupt_event,
            stale_timeout=None,
            on_heartbeat=on_heartbeat,
            **kwargs,
        )

    def _lazy_runner(self, prompt: str, kw: dict[str, Any]) -> str:
        """Indirection so the heavy ``mlx_lm.load`` doesn't fire at
        construction time. First call resolves the real runner; later
        calls hit the resolved closure directly."""
        if self._explicit_runner is not None:
            self.runner = self._explicit_runner
            return self._explicit_runner(prompt, kw)
        if self.model_path is None:
            raise ValueError(
                "MLXAdapter needs either ``model_path`` or an explicit "
                "``runner``."
            )
        resolved = _build_mlx_runner(self.model_path, defaults=self.defaults)
        # Swap the resolved runner in so future calls skip the dispatch
        # entirely. ``self.runner`` is the attribute the parent's
        # ``call()`` reads.
        self.runner = resolved
        return resolved(prompt, kw)

    def describe(self) -> str:
        target = self.model_path or "runner"
        return f"mlx · {target}"


__all__ = ["MLXAdapter"]
