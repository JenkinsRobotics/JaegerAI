"""MLX backend client — the in-process Apple-Silicon alternative to
``LlamaCppPythonClient``. Same surface (``kind``, ``model``, ``chat``,
``describe``, ``model_name``) so the agent loop, fast-finalize, and
thinking-runner code paths in ``main.py`` work against either backend.

mlx-lm is imported lazily so this module loads cleanly on Linux or on a
Mac without the wheel installed; the import only fails when you try to
actually construct an :class:`MlxClient` without ``mlx-lm`` on the venv.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any



@dataclass
class _ChatResult:
    text: str
    elapsed_s: float


class MlxClient:
    """Loads an MLX model once and exposes the same client interface as
    :class:`~jaeger_os.main.LlamaCppPythonClient`. ``model_path`` is the
    directory containing the MLX model's ``config.json`` and weight
    shards (e.g. ``~/.lmstudio/models/mlx-community/Qwen3.5-9B-MLX-4bit``).
    """

    kind = "local"

    def __init__(self, model_path: str | Path, *, warmup: bool = True) -> None:
        try:
            from mlx_lm import load  # type: ignore[import-not-found]
        except ImportError as exc:
            raise RuntimeError(
                "MLX backend requires the mlx-lm wheel — "
                "`pip install mlx-lm` (Apple Silicon)."
            ) from exc

        resolved = Path(str(model_path)).expanduser()
        if not resolved.is_dir():
            raise FileNotFoundError(
                f"MLX model directory not found: {resolved}. "
                "MLX models are directories holding config.json + "
                "*.safetensors, not single files like GGUF."
            )

        self.model_name = resolved.name
        print(f"[jaeger] loading MLX model {self.model_name}…", flush=True)
        started = time.perf_counter()
        self._mlx_model, self._tokenizer = load(str(resolved))
        print(
            f"[jaeger] loaded in {time.perf_counter() - started:.1f}s.",
            flush=True,
        )
        if warmup:
            self._warmup()

    def describe(self) -> str:
        return f"local · mlx · {self.model_name}"

    def _warmup(self) -> None:
        """One tiny generation to prime mlx-lm's compilation caches so the
        first user-facing turn doesn't pay the cold-start tax."""
        try:
            from mlx_lm import generate  # type: ignore[import-not-found]
            generate(
                self._mlx_model, self._tokenizer,
                prompt="hi", max_tokens=1, verbose=False,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"[jaeger] MLX warmup skipped: {exc}", flush=True)

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        max_tokens: int = 512,
        temperature: float = 0.0,
        top_p: float = 0.95,
        stream: bool = False,         # accepted for interface parity, ignored
        grammar: str | None = None,   # ditto
        tools: list[dict[str, Any]] | None = None,  # ditto
    ) -> _ChatResult:
        """Minimal chat-completion wrapper — same shape as
        ``LlamaCppPythonClient.chat`` so fast-finalize / ThinkingRunner
        work uniformly. Renders messages through the tokenizer's chat
        template and runs ``mlx_lm.generate`` once."""
        del stream, grammar, tools  # not used; kept for surface parity
        from mlx_lm import generate  # type: ignore[import-not-found]
        try:
            prompt = self._tokenizer.apply_chat_template(
                messages, add_generation_prompt=True, tokenize=False,
            )
        except Exception:  # noqa: BLE001
            prompt = "\n".join(
                f"{m.get('role', '?')}: {m.get('content', '')}" for m in messages
            )
        kwargs: dict[str, Any] = {
            "prompt": prompt, "max_tokens": max_tokens, "verbose": False,
        }
        if temperature > 0:
            kwargs["temp"] = temperature
        del top_p  # mlx-lm samplers vary by version; skip until stable
        started = time.perf_counter()
        text = generate(self._mlx_model, self._tokenizer, **kwargs)
        return _ChatResult(text=text or "", elapsed_s=time.perf_counter() - started)
