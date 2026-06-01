"""External-model pipeline — run the agent on a non-local brain.

Jaeger-OS is local-first: the default brain is the in-process
llama-cpp model wrapped by :class:`jaeger_os.core.llm_model.LlamaCppModel`.
This module is the opt-in alternative — when ``config.external_model``
is enabled, the agent runs on an external provider instead:

  • ``lmstudio``     — a local LM Studio server (OpenAI-compatible HTTP).
                       Still on-device, just a separate process / GUI.
  • ``ollama``       — a local Ollama server (OpenAI-compatible HTTP).
  • ``ollama-cloud`` — Ollama's hosted endpoint (needs an API key).
  • ``openai``       — any OpenAI-compatible cloud / self-hosted endpoint.
  • ``anthropic``    — Claude via the Anthropic API.
  • ``gemini``       — Google Gemini via its OpenAI-compatible endpoint.

The agent loop (``agent.iter()``, skip-final, the fix loop, Deep Think)
is model-agnostic — it only needs (a) a pydantic-ai ``Model`` for the
tool-calling loop and (b) a ``.chat()`` shim for the bounded
fast-finalize / thinking passes. :class:`ExternalModelClient` provides
both, mirroring the surface of ``LlamaCppPythonClient`` so the rest of
``main.py`` doesn't branch on backend.

Security / local-first invariants:
  • Disabled by default — a fresh instance never phones home.
  • API keys are read from the instance ``credentials/`` store (the
    sanctioned secret path), or an env var. They are never written to
    ``config.yaml`` and never logged.
  • Local model swap for Deep Think (``switch_model``) is a llama-cpp
    feature; when an external brain is active Deep Think keeps using
    that same external model (no local coder swap).
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any

from jaeger_os.core.instance.schemas import ExternalModelConfig


# OpenAI-compatible providers all speak the same /chat/completions wire
# format; only anthropic is its own shape. ``ollama-cloud`` is Ollama's
# hosted endpoint (https://ollama.com/v1) — same protocol as local
# ollama, but a real API key is required. ``gemini`` is Google's
# OpenAI-compatible endpoint (generativelanguage.googleapis.com/v1beta/
# openai/) — so it rides the same path as openai, no native adapter.
_OPENAI_COMPATIBLE = {"lmstudio", "ollama", "ollama-cloud", "openai", "gemini"}

# The conventional environment variable each provider's key lives in,
# checked last by :func:`resolve_api_key`.
_CONVENTIONAL_ENV = {
    "openai": "OPENAI_API_KEY",
    "lmstudio": "OPENAI_API_KEY",
    "ollama-cloud": "OLLAMA_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "gemini": "GEMINI_API_KEY",
}


@dataclass
class ExtChatResult:
    """Completion shape the fast-finalize / thinking passes expect —
    duck-compatible with ``main._ChatResult``."""

    text: str
    latency_s: float
    ttft_s: float = 0.0


class ExternalModelError(RuntimeError):
    """Raised when an external model can't be built or reached."""


# ---------------------------------------------------------------------------
# Key resolution
# ---------------------------------------------------------------------------
def resolve_api_key(ext: ExternalModelConfig, layout: Any | None) -> str:
    """Resolve the provider API key, in priority order:

      1. the instance credential named ``ext.api_key_credential``
      2. the environment variable named ``ext.api_key_env``
      3. the provider's conventional env var (OPENAI_API_KEY /
         ANTHROPIC_API_KEY)

    Returns ``""`` when nothing is found — fine for a local LM Studio
    server, which accepts any placeholder key.
    """
    if layout is not None and ext.api_key_credential:
        try:
            from jaeger_os.core import credentials as creds

            return creds.get_credential(layout, ext.api_key_credential)
        except Exception:  # noqa: BLE001 — missing credential is expected
            pass
    if ext.api_key_env:
        val = os.environ.get(ext.api_key_env, "")
        if val:
            return val
    conventional = _CONVENTIONAL_ENV.get(ext.provider, "")
    return os.environ.get(conventional, "") if conventional else ""


# ---------------------------------------------------------------------------
# Provider validation
# ---------------------------------------------------------------------------
# Phase-9 cleanup: the legacy ``build_external_model`` constructed a
# pydantic-ai ``Model`` instance. After Phase 6.2 the agent layer drives
# providers directly via :mod:`jaeger_os.agent.adapters`, so the only
# work this layer needs to do is validate that the API key is present
# before the adapter tries to use it.


def validate_external_provider(ext: ExternalModelConfig, api_key: str) -> str:
    """Return the resolved API key for ``ext``, raising
    :class:`ExternalModelError` when a cloud provider is missing a key.

    Local OpenAI-compatible servers (LM Studio, local Ollama) accept
    any non-empty key; this helper injects a placeholder. True cloud
    endpoints (``openai`` / ``anthropic`` / ``ollama-cloud`` /
    ``gemini``) genuinely require a real key.
    """
    if ext.provider in _OPENAI_COMPATIBLE:
        _placeholder = {"lmstudio": "lm-studio", "ollama": "ollama"}
        key = api_key or _placeholder.get(ext.provider, "")
        if not key:
            env = ext.api_key_env or _CONVENTIONAL_ENV.get(
                ext.provider, "OPENAI_API_KEY",
            )
            raise ExternalModelError(
                f"provider {ext.provider!r} needs an API key — set the "
                f"{ext.api_key_credential!r} credential or the {env} "
                f"env var."
            )
        return key

    if ext.provider == "anthropic":
        if not api_key:
            raise ExternalModelError(
                "provider 'anthropic' needs an API key — set the "
                f"{ext.api_key_credential!r} credential or the "
                f"{ext.api_key_env or 'ANTHROPIC_API_KEY'} env var."
            )
        return api_key

    raise ExternalModelError(f"unknown provider {ext.provider!r}")


# ---------------------------------------------------------------------------
# Client — mirrors LlamaCppPythonClient's surface
# ---------------------------------------------------------------------------
def _merge_consecutive(messages: list[dict[str, str]]) -> list[dict[str, str]]:
    """Collapse consecutive same-role messages into one. The
    fast-finalize path sends two user turns in a row; Anthropic is
    strict about role alternation, so merge before sending."""
    out: list[dict[str, str]] = []
    for m in messages:
        if out and out[-1]["role"] == m["role"]:
            out[-1] = {"role": m["role"], "content": out[-1]["content"] + "\n\n" + m["content"]}
        else:
            out.append({"role": m["role"], "content": m["content"]})
    return out


class ExternalModelClient:
    """External-brain client. Exposes the surface ``main.py`` reads:

      • ``.chat()``  — bounded completion for fast-finalize / thinking
      • ``.kind``    — ``"external"`` (vs ``"local"``)
      • ``.describe()`` — one-line human summary for the status panel
      • ``.ext`` / ``.provider`` / ``.model_name`` — config attributes
        the new agent layer's :func:`jaeger_os.agent.loop.runtime_bridge.
        _adapter_for_client` reads to pick the right adapter.
    """

    kind = "external"
    llm = None  # no in-process Llama — kept so `client.llm` access is safe

    def __init__(self, ext: ExternalModelConfig, layout: Any | None = None) -> None:
        self.ext = ext
        self._api_key = validate_external_provider(
            ext, resolve_api_key(ext, layout),
        )
        self.model_name = ext.model
        self.provider = ext.provider

    # -- bounded completion shim -------------------------------------------
    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        max_tokens: int = 512,
        temperature: float = 0.0,
        top_p: float = 0.95,
        stream: bool = False,
        grammar: str | None = None,
    ) -> ExtChatResult:
        """One-shot chat completion. ``stream`` / ``grammar`` are ignored
        (parity with ``LlamaCppPythonClient.chat``).

        Cloud calls are wrapped in :func:`cloud_errors.retry_call` — a
        rate-limit or transient 5xx is retried with jittered backoff; a
        bad key / unknown model is raised straight through (audit A8)."""
        from jaeger_os.core.runtime.cloud_errors import retry_call

        is_oai = self.provider in _OPENAI_COMPATIBLE

        def _call() -> str:
            if is_oai:
                return self._chat_openai(messages, max_tokens, temperature, top_p)
            return self._chat_anthropic(messages, max_tokens, temperature, top_p)

        started = time.perf_counter()
        text = retry_call(_call)
        return ExtChatResult(text=text.strip(), latency_s=time.perf_counter() - started)

    def _chat_openai(self, messages, max_tokens, temperature, top_p) -> str:
        from openai import OpenAI

        key = self._api_key or ("lm-studio" if self.provider == "lmstudio" else "")
        client = OpenAI(
            base_url=self.ext.base_url, api_key=key, timeout=self.ext.timeout_s,
        )
        completion = client.chat.completions.create(
            model=self.ext.model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            top_p=top_p,
        )
        return completion.choices[0].message.content or ""

    def _chat_anthropic(self, messages, max_tokens, temperature, top_p) -> str:
        from anthropic import Anthropic

        client = Anthropic(api_key=self._api_key, timeout=self.ext.timeout_s)
        system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
        convo = _merge_consecutive(
            [m for m in messages if m["role"] in ("user", "assistant")]
        )
        resp = client.messages.create(
            model=self.ext.model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system or None,
            messages=convo or [{"role": "user", "content": "(no input)"}],
        )
        return "".join(
            block.text for block in resp.content if getattr(block, "type", "") == "text"
        )

    # -- diagnostics -------------------------------------------------------
    def describe(self) -> str:
        where = self.ext.base_url if self.provider in _OPENAI_COMPATIBLE else "api.anthropic.com"
        return f"external · {self.provider} · {self.ext.model} · {where}"

    def connectivity_check(self) -> dict[str, Any]:
        """Confirm the endpoint answers. Returns ``{ok, detail, latency_s}``.

        For an OpenAI-compatible provider this is a cheap ``GET /models``
        — it proves the endpoint + API key work without paying for a
        generation. Critically, it does NOT generate: a *thinking*
        model (qwen3.5, …) legitimately returns an empty completion when
        a token-capped probe runs out of budget mid-reasoning, which the
        old chat-probe mistook for 'unreachable' and fell back to local.
        ``ok`` means the HTTP round-trip succeeded — reachability, not
        output quality."""
        started = time.perf_counter()
        try:
            if self.provider in _OPENAI_COMPATIBLE:
                import requests
                key = self._api_key or (
                    "lm-studio" if self.provider == "lmstudio" else "")
                headers = {"Authorization": f"Bearer {key}"} if key else {}
                resp = requests.get(
                    f"{self.ext.base_url.rstrip('/')}/models",
                    headers=headers, timeout=self.ext.timeout_s,
                )
                resp.raise_for_status()
                return {"ok": True, "detail": "endpoint reachable",
                        "latency_s": round(time.perf_counter() - started, 2)}
            # Anthropic — a small generation probe (no /models list).
            result = self.chat(
                [{"role": "user", "content": "Reply with: ok"}],
                max_tokens=64, temperature=0.0,
            )
            return {
                "ok": True,
                "detail": (result.text[:80].strip() or "reachable"),
                "latency_s": round(result.latency_s, 2),
            }
        except Exception as exc:  # noqa: BLE001
            # Classify the failure so the user sees "bad API key" rather
            # than a raw exception repr (audit A8).
            from jaeger_os.core.runtime.cloud_errors import classify_exception, friendly_message
            return {
                "ok": False,
                "detail": friendly_message(exc, provider=self.provider),
                "error_class": classify_exception(exc),
                "latency_s": 0.0,
            }
