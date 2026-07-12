"""LLM transports for the agent — HTTP server AND in-process.

Two clients, same :class:`LLMResult` shape so :mod:`runner` doesn't
care which one is in use:

  - :class:`LlamaServerClient` — talks HTTP to an external
    ``llama-server`` process. Use for production deployments where
    the voice loop and the agent share one Gemma 4 across processes.
    Per-call overhead: ~50-200 ms of HTTP/SSE marshaling.

  - :class:`LlamaCppPythonClient` — loads Gemma 4 in-process via
    ``llama-cpp-python``. Use for benchmarks against the AgenticLLM
    reference (which uses in-process by default). Zero per-call
    transport overhead, ~17 GB of resident RAM. **Cannot coexist
    with a running llama-server on the same GPU** — caller must
    kill llama-server first to free Metal memory.

Both clients are intentionally <300 lines total with no transport
abstraction, no context_compressor, no custom_providers, no MCP
discovery: just chat-completions plus per-turn latency timing.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests


DEFAULT_BASE_URL = os.environ.get(
    "LILITH_LLM_BASE_URL", "http://127.0.0.1:8080/v1"
).rstrip("/")
"""Same env-var contract the launcher uses, so ``./lilith`` and the
agent both honor an explicit endpoint override (robot deployment may
relocate the server). Trailing ``/v1`` is normalized off so we can
re-add the OpenAI-compat suffix consistently below."""


@dataclass
class LLMResult:
    """Single chat-completion call result.

    - ``text`` is the joined assistant content (post-strip).
    - ``latency_s`` is wall-clock from request start to last chunk.
    - ``ttft_s`` is wall-clock from request start to FIRST non-empty
      delta. Important for voice UX: a snappy ttft hides slow decode
      because TTS can start synthesizing partial sentences.
    """

    text: str
    latency_s: float
    ttft_s: float = 0.0


class LlamaServerClient:
    """HTTP client targeting an llama-server OpenAI-compat endpoint.

    Bare minimum: chat (streaming and blocking), health probe. No
    schema caching, no provider negotiation, no fallback chains.
    """

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        model: str = "local",
        timeout_s: float = 120.0,
    ) -> None:
        # Tolerate both "http://host:port" and "http://host:port/v1"
        # forms — voice_minimal sets the env var with /v1 included.
        self.base_url = base_url.rstrip("/")
        if self.base_url.endswith("/v1"):
            self.base_url = self.base_url[:-3]
        self.model = model
        self.timeout_s = timeout_s
        # Persistent HTTPS session — reuses the underlying TCP
        # connection across calls so the agent doesn't pay a fresh
        # handshake per turn. The bench measured ~50-150 ms of
        # per-call HTTP overhead on the first agent run; pooling
        # cuts that to a fraction of the same.
        self._session = requests.Session()

    # ── Public API ────────────────────────────────────────────────

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        max_tokens: int,
        temperature: float = 0.0,
        top_p: float = 0.8,
        stream: bool = True,
    ) -> LLMResult:
        """Send messages to ``/v1/chat/completions`` and return the
        joined assistant text plus timing. Streams by default so
        ``ttft`` is measurable; ``stream=False`` returns the full
        body in one shot (slightly lower overhead per call but no
        ttft signal)."""
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "top_p": top_p,
            "max_tokens": max_tokens,
            "stream": stream,
        }
        started = time.perf_counter()
        if stream:
            text, ttft = self._stream_chat(payload, started)
        else:
            text = self._blocking_chat(payload)
            ttft = time.perf_counter() - started
        elapsed = time.perf_counter() - started
        return LLMResult(text=text.strip(), latency_s=elapsed, ttft_s=ttft)

    def health_check(self) -> bool:
        """``/health`` first (llama-server native), fall back to
        ``/v1/models`` (works on any OpenAI-compat server). Returns
        False on any network / non-2xx error."""
        try:
            response = self._session.get(f"{self.base_url}/health", timeout=3)
            if response.ok:
                return True
        except requests.RequestException:
            pass

        try:
            response = self._session.get(
                f"{self.base_url}/v1/models", timeout=3
            )
            return response.ok
        except requests.RequestException:
            return False

    # ── Internals ─────────────────────────────────────────────────

    def _blocking_chat(self, payload: dict[str, Any]) -> str:
        response = self._session.post(
            f"{self.base_url}/v1/chat/completions",
            json=payload,
            timeout=self.timeout_s,
        )
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"]

    def _stream_chat(
        self, payload: dict[str, Any], started: float
    ) -> tuple[str, float]:
        chunks: list[str] = []
        ttft = 0.0
        with self._session.post(
            f"{self.base_url}/v1/chat/completions",
            json=payload,
            timeout=self.timeout_s,
            stream=True,
        ) as response:
            response.raise_for_status()
            for raw_line in response.iter_lines(decode_unicode=True):
                if not raw_line:
                    continue
                line = raw_line.strip()
                # OpenAI-style SSE: ``data: {json}`` lines, terminated
                # by ``data: [DONE]``. llama-server emits both shapes.
                if line.startswith("data: "):
                    line = line[6:]
                if line == "[DONE]":
                    break
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue
                delta = data.get("choices", [{}])[0].get("delta", {})
                content = delta.get("content")
                if content:
                    if ttft == 0.0:
                        ttft = time.perf_counter() - started
                    chunks.append(content)
        return "".join(chunks), ttft


DEFAULT_GGUF_PATH = Path(
    os.environ.get(
        "LILITH_AGENT_GGUF",
        "/Users/jonathanjenkins/.lmstudio/models/lmstudio-community/"
        "gemma-4-26B-A4B-it-GGUF/gemma-4-26B-A4B-it-Q4_K_M.gguf",
    )
)
"""Default GGUF path for the in-process backend — mirrors the
reference's ``DEFAULT_MODEL_PATH``. Override via ``LILITH_AGENT_GGUF``
env or pass ``model_path=`` directly to the client constructor."""


class LlamaCppPythonClient:
    """In-process llama-cpp-python client.

    Mirrors the reference's
    ``references/AgenticLLM copy/hermes/llm_client.py
    .LlamaCppPythonClient`` exactly — same defaults, same warm-up,
    same streaming pattern — so a head-to-head bench against the
    reference is apples-to-apples on transport. The 2026-05-12
    bench measured the agent path's gap was almost entirely the
    HTTP/llama-server round-trip; in-process eliminates that.

    **Do not load this while ``llama-server`` is running** — both
    want the same Metal device and the second one will fail / OOM.
    The bench's ``_run_path_agent`` kills the port holder before
    loading this client.

    Defaults:
      - ``ctx=8192``       — matches reference; smaller than
                             voice_minimal's 65536 because the agent
                             doesn't need the long-context window
                             (and bigger KV cache = slower).
      - ``gpu_layers=-1``  — every layer on Metal.
      - ``batch=512``,
        ``ubatch=512``     — matches reference's prefill batch
                             tuning for Apple Silicon.
      - ``flash_attn=True``— faster attention.
      - warm with ``"hi"`` max_tokens=1 — pays graph-compile cost
        up front (same as reference).
    """

    def __init__(
        self,
        model_path: Path = DEFAULT_GGUF_PATH,
        *,
        ctx: int = 8192,
        gpu_layers: int = -1,
        batch: int = 512,
        ubatch: int = 512,
        flash_attn: bool = True,
        swa_full: bool = False,
        threads: int | None = None,
        warmup: bool = True,
    ) -> None:
        from llama_cpp import Llama

        path = model_path.expanduser()
        if not path.exists():
            raise FileNotFoundError(f"Model file not found: {path}")

        kwargs: dict[str, Any] = {
            "model_path": str(path),
            "n_ctx": ctx,
            "n_gpu_layers": gpu_layers,
            "n_batch": batch,
            "n_ubatch": ubatch,
            "flash_attn": flash_attn,
            "swa_full": swa_full,
            "verbose": False,
        }
        if threads is not None:
            kwargs["n_threads"] = threads

        print(f"[llama.cpp] Loading {path.name}...", flush=True)
        started = time.perf_counter()
        self.llm = Llama(**kwargs)
        print(
            f"[llama.cpp] Loaded in {time.perf_counter() - started:.1f}s.",
            flush=True,
        )

        # Record both the loaded ctx (what we allocated via n_ctx) and
        # the model's *trained* native max. The status bar shows the
        # former as the live denominator; surfacing the latter lets the
        # operator notice "you loaded Qwen3-Coder at 16K but it's a 262K
        # model — bump config.model.ctx if you need the headroom."
        self.loaded_ctx: int = int(ctx)
        try:
            # llama-cpp-python exposes both via methods on the Llama obj.
            self.native_ctx_max: int = int(self.llm.n_ctx_train())
        except Exception:  # noqa: BLE001 — older builds may not expose it
            self.native_ctx_max = int(ctx)

        if warmup:
            print("[llama.cpp] Warming up...", flush=True)
            started = time.perf_counter()
            self.llm.create_chat_completion(
                messages=[{"role": "user", "content": "hi"}],
                max_tokens=1,
                temperature=0.0,
            )
            print(
                f"[llama.cpp] Warm-up done in "
                f"{time.perf_counter() - started:.1f}s.\n",
                flush=True,
            )

    # ── Public API ────────────────────────────────────────────────

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        max_tokens: int,
        temperature: float = 0.0,
        top_p: float = 0.8,
        stream: bool = True,
    ) -> LLMResult:
        """Same signature as :class:`LlamaServerClient.chat` so the
        runner doesn't care which client is wired in."""
        kwargs: dict[str, Any] = {
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "top_p": top_p,
            "stream": stream,
        }
        started = time.perf_counter()
        completion = self.llm.create_chat_completion(**kwargs)
        if stream:
            text, ttft = self._collect_stream(completion, started)
        else:
            text = completion["choices"][0]["message"]["content"]
            ttft = time.perf_counter() - started
        elapsed = time.perf_counter() - started
        return LLMResult(text=text.strip(), latency_s=elapsed, ttft_s=ttft)

    def health_check(self) -> bool:
        """No-op for in-process — if ``__init__`` returned, we're up."""
        return True

    # ── Internals ─────────────────────────────────────────────────

    @staticmethod
    def _collect_stream(chunks: Any, started: float) -> tuple[str, float]:
        parts: list[str] = []
        ttft = 0.0
        for chunk in chunks:
            text = chunk["choices"][0].get("delta", {}).get("content", "")
            if text:
                if ttft == 0.0:
                    ttft = time.perf_counter() - started
                parts.append(text)
        return "".join(parts), ttft


__all__ = [
    "DEFAULT_BASE_URL",
    "DEFAULT_GGUF_PATH",
    "LLMResult",
    "LlamaServerClient",
    "LlamaCppPythonClient",
]
