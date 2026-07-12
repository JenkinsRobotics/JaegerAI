"""MLX-VLM backend client — the in-process loader for Apple MLX models
that the text-only ``mlx-lm`` can't construct: the multimodal / unified
gemma-4 builds (``model_type: gemma4_unified``, etc.).

Same surface as :class:`~jaeger_os.core.models.mlx_client.MlxClient`
(``kind``, ``model_name``, ``chat``, ``describe``, ``_mlx_model``,
``_tokenizer``, ``_executor``) so the agent loop's MLX adapter and the
``runtime_bridge`` wiring treat it like any other in-process MLX client.
The difference is purely the loader + generator: ``mlx_vlm`` instead of
``mlx_lm``. JROS uses these models for text routing — images/audio are
not fed in — so generation runs the text-only path of ``mlx_vlm``.

``mlx-vlm`` is imported lazily so importing this module never drags the
wheel in; the import only fails when you actually construct the client
without ``mlx-vlm`` on the venv (``pip install mlx-vlm``).
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class _ChatResult:
    text: str
    elapsed_s: float


class MlxVlmClient:
    """Loads a multimodal/unified MLX model via ``mlx-vlm`` and exposes the
    same client surface as :class:`MlxClient`. ``model_path`` is the
    directory holding ``config.json`` + ``*.safetensors``.

    ``is_vlm = True`` flags the adapter to route generation through
    ``mlx_vlm`` rather than ``mlx_lm`` (the two libraries have separate,
    incompatible ``stream_generate`` entry points)."""

    kind = "local"
    is_vlm = True

    def __init__(self, model_path: str | Path, *, warmup: bool = True) -> None:
        try:
            from mlx_vlm import load  # type: ignore[import-not-found]
            from mlx_vlm.utils import load_config  # type: ignore[import-not-found]
        except ImportError as exc:
            raise RuntimeError(
                "MLX-VLM backend requires the mlx-vlm wheel — "
                "`pip install mlx-vlm` (Apple Silicon)."
            ) from exc

        resolved = Path(str(model_path)).expanduser()
        if not resolved.is_dir():
            raise FileNotFoundError(
                f"MLX model directory not found: {resolved}. MLX models "
                "are directories holding config.json + *.safetensors."
            )

        # MLX pins each GPU stream to the creating thread — the model, its
        # warmup, and every generation must share ONE thread. This
        # single-worker executor IS that thread (same contract as
        # MlxClient); the MLX adapter routes generation through it too.
        self._executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="mlx-vlm",
        )

        self.model_name = resolved.name
        print(f"[jaeger] loading MLX-VLM model {self.model_name}…", flush=True)
        started = time.perf_counter()
        self._mlx_model, self._processor = self._executor.submit(
            load, str(resolved),
        ).result()
        self._config = load_config(str(resolved))
        # ``_tokenizer`` alias so the adapter / runtime_bridge — which read
        # ``_tokenizer`` off MLX clients — find the processor uniformly.
        self._tokenizer = self._processor
        print(
            f"[jaeger] loaded in {time.perf_counter() - started:.1f}s.",
            flush=True,
        )
        if warmup:
            self._executor.submit(self._warmup).result()

    def describe(self) -> str:
        return f"local · mlx-vlm · {self.model_name}"

    def _warmup(self) -> None:
        """One tiny generation to prime mlx-vlm's compilation caches."""
        try:
            from mlx_vlm import generate
            from mlx_vlm.prompt_utils import apply_chat_template
            prompt = apply_chat_template(
                self._processor, self._config, "hi", num_images=0,
            )
            generate(self._mlx_model, self._processor, prompt,
                     max_tokens=1, verbose=False)
        except Exception as exc:  # noqa: BLE001
            print(f"[jaeger] MLX-VLM warmup skipped: {exc}", flush=True)

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        max_tokens: int = 512,
        temperature: float = 0.0,
        top_p: float = 0.95,
        stream: bool = False,         # accepted for parity, ignored
        grammar: str | None = None,   # ditto
        tools: list[dict[str, Any]] | None = None,  # ditto
    ) -> _ChatResult:
        """Minimal text chat-completion — same shape as ``MlxClient.chat``.
        Renders the messages through mlx-vlm's chat template (no images)
        and runs one text generation on the affine executor thread."""
        del stream, grammar, tools, top_p
        from mlx_vlm import generate
        from mlx_vlm.prompt_utils import apply_chat_template
        try:
            prompt = apply_chat_template(
                self._processor, self._config, messages, num_images=0,
            )
        except Exception:  # noqa: BLE001
            prompt = "\n".join(
                f"{m.get('role', '?')}: {m.get('content', '')}" for m in messages
            )
        kwargs: dict[str, Any] = {"max_tokens": max_tokens, "verbose": False}
        if temperature > 0:
            kwargs["temperature"] = temperature
        started = time.perf_counter()
        result = self._executor.submit(
            generate, self._mlx_model, self._processor, prompt, **kwargs,
        ).result()
        text = getattr(result, "text", None)
        if text is None:
            text = result if isinstance(result, str) else str(result)
        return _ChatResult(text=text or "", elapsed_s=time.perf_counter() - started)
