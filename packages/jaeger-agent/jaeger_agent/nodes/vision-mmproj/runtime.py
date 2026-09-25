"""Vision node: Gemma's mmproj projector; composes image+text message content.

Node of the agent brain. Config source of truth stays core/policy.py;
the manifest documents it."""
from __future__ import annotations

from pathlib import Path
from typing import Any

try:  # packaged engine
    from jaeger_agent.core.policy import MMPROJ
except ImportError:  # portable node folder loaded by the playground
    from policy import MMPROJ


class _PrefixContext:
    """Defer MTMD's unconditional clear until its first text chunk is known."""

    def __init__(self, owner: Any) -> None:
        self.owner = owner

    def kv_cache_clear(self) -> None:
        # reset() immediately precedes this call in MTMD. A native image
        # decode accesses ctx below, which forces a clear if no text preceded it.
        if not self.owner.pending:
            self.owner.llama._ctx.kv_cache_clear()

    @property
    def ctx(self) -> Any:
        self.owner.ensure_reset()
        return self.owner.llama._ctx.ctx

    def __getattr__(self, name: str) -> Any:
        return getattr(self.owner.llama._ctx, name)


class _PrefixLlama:
    """Reuse only exactly matching real text tokens before the first image.

    Never reuse synthetic image positions. The original MTMD handler still
    loads and evaluates every image and all text following the first image.
    This proxy avoids copying its native decoder or patching installed packages.
    """

    def __init__(self, llama: Any, limit: int) -> None:
        self.llama = llama
        self.limit = max(0, min(limit, llama.n_tokens))
        self.pending = False
        self.leading_tokens = 0
        self._ctx = _PrefixContext(self)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.llama, name)

    @property
    def n_tokens(self) -> int:
        return 0 if self.pending else self.llama.n_tokens

    @n_tokens.setter
    def n_tokens(self, value: int) -> None:
        self.ensure_reset()
        self.llama.n_tokens = value

    def reset(self) -> None:
        self.pending = True

    def ensure_reset(self) -> None:
        if self.pending:
            self.pending = False
            self.llama.reset()
            self.llama._ctx.kv_cache_clear()

    def eval(self, tokens: Any) -> None:
        if not self.pending:
            self.llama.eval(tokens)
            return
        common = 0
        while (common < min(self.limit, len(tokens))
               and self.llama.input_ids[common] == tokens[common]):
            common += 1
        if common and self.llama._ctx.kv_cache_seq_rm(0, common, -1):
            self.pending = False
            self.llama.n_tokens = common
        else:
            common = 0
            self.ensure_reset()
        if common < len(tokens):
            self.llama.eval(tokens[common:])
        self.leading_tokens = len(tokens)


class ModalityAwareChatHandler:
    """Keep text-prefix caching when a projector is attached to one Llama.

    llama.cpp's MTMD handler clears the entire KV cache before every call,
    even with no media. Delegate text-only histories to the model's original
    GGUF chat formatter, keeping its normal tool rendering and prefix reuse.
    Media anywhere in the history still uses MTMD. This selects the input
    decoder, not another model, runtime, agent loop or memory store.
    """

    def __init__(self, vision: Any) -> None:
        self.vision = vision
        self._last_was_media = False
        self._media_prefix_tokens = 0
        self._prefix_context = None

    def __getattr__(self, name: str) -> Any:
        # Preserve the projector lifecycle contract (notably _exit_stack).
        return getattr(self.vision, name)

    def __call__(self, *, llama: Any, messages: list[dict], **kwargs: Any) -> Any:
        has_media = any(
            not isinstance(part, dict) or part.get("type") != "text"
            for message in messages
            if isinstance(message.get("content"), list)
            for part in message["content"]
        )
        if has_media:
            prior_media = self._last_was_media
            self._last_was_media = True
            if (hasattr(llama, "input_ids") and hasattr(llama, "n_tokens")
                    and callable(getattr(llama._ctx, "kv_cache_seq_rm", None))):
                limit = llama.n_tokens
                if prior_media:
                    limit = self._media_prefix_tokens if self._prefix_context is llama._ctx else 0
                proxy = _PrefixLlama(llama, limit)
                try:
                    result = self.vision(llama=proxy, messages=messages, **kwargs)
                    proxy.ensure_reset()
                except Exception:
                    llama.reset()
                    llama._ctx.kv_cache_clear()
                    self._media_prefix_tokens = 0
                    raise
                self._media_prefix_tokens = proxy.leading_tokens
                self._prefix_context = llama._ctx
                return result
            return self.vision(llama=llama, messages=messages, **kwargs)

        # Preload the projector during engine warmup, even for a text prefix.
        # Do not execute the MTMD decode path: that is what discards the cache.
        self.vision._init_mtmd_context(llama)
        if self._last_was_media:
            # MTMD's synthetic image token positions must never be reused as
            # a text-only prefix. Invalidate once when leaving a media history.
            prefix = self._media_prefix_tokens if self._prefix_context is llama._ctx else 0
            if prefix and llama._ctx.kv_cache_seq_rm(0, prefix, -1):
                llama.n_tokens = min(prefix, llama.n_tokens)
            else:
                llama.reset()
                llama._ctx.kv_cache_clear()
            self._last_was_media = False
        # When Llama is constructed WITH a projector, its chat_format may be
        # the generic "llama-2" fallback even though a Gemma GGUF template is
        # registered. Prefer that actual model template in both construction
        # orders (standalone and late-attached application).
        handler = (
            llama._chat_handlers.get("chat_template.default")
            or llama._chat_handlers.get(llama.chat_format)
        )
        if handler is None:
            # No verified text formatter: preserve the original vision path
            # rather than accidentally changing the model's prompt dialect.
            return self.vision(llama=llama, messages=messages, **kwargs)
        return handler(llama=llama, messages=messages, **kwargs)


class VisionMmproj:
    def __init__(self) -> None:
        self.ready = False
        self.handler = None

    def load(self, want: bool, say=print, *, model_path: str | Path = MMPROJ):
        if not want:
            return None
        path = Path(model_path).expanduser()
        if path.is_file():
            from llama_cpp.llama_chat_format import Gemma4ChatHandler
            say(f"loading vision projector {path.name}…")
            self.handler = ModalityAwareChatHandler(
                Gemma4ChatHandler(clip_model_path=str(path), verbose=False)
            )
            self.ready = True
        else:
            say(f"no vision projector at {path} — text and audio only")
        return self.handler

    def close(self) -> None:
        """Release llama.cpp's lazily-created MTMD projector context.

        ``Gemma4ChatHandler`` owns that native context through a private
        ``ExitStack`` but currently exposes no public close method.  Leaving
        it for interpreter teardown keeps a second Metal device alive after
        the language model closes and can abort the process in ggml-metal.
        """
        handler, self.handler = self.handler, None
        self.ready = False
        if handler is None:
            return
        exit_stack = getattr(handler, "_exit_stack", None)
        close = getattr(exit_stack, "close", None)
        if callable(close):
            close()

    @staticmethod
    def content(user_text: str, image_uri):
        if image_uri is None:
            return user_text
        return [{"type": "image_url", "image_url": {"url": image_uri}},
                {"type": "text", "text": user_text or "What do you see?"}]


def build():
    return VisionMmproj()
