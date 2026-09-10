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
  • ``xai``          — xAI Grok via its OpenAI-compatible endpoint.
  • ``cli``          — an installed agent CLI (claude / codex / grok /
                       gemini / hermes) used as the brain. Jaeger keeps
                       the loop; this is not ``delegate_task``.

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

from jaeger_ai.core.instance.schemas import ExternalModelConfig


# OpenAI-compatible providers all speak the same /chat/completions wire
# format; only anthropic is its own shape. ``ollama-cloud`` is Ollama's
# hosted endpoint (https://ollama.com/v1) — same protocol as local
# ollama, but a real API key is required. ``gemini`` is Google's
# OpenAI-compatible endpoint (generativelanguage.googleapis.com/v1beta/
# openai/) — so it rides the same path as openai, no native adapter.
_OPENAI_COMPATIBLE = {
    "lmstudio", "ollama", "ollama-cloud", "openai", "gemini", "xai",
    "openrouter", "groq", "deepseek", "vllm", "together",
}

# Providers whose endpoint is off-box. A failure here is an auth or
# network problem the operator can fix; a failure on a LOCAL server
# (lmstudio / ollama) usually just means the server isn't running.
_CLOUD_PROVIDERS = {
    "ollama-cloud", "openai", "anthropic", "gemini", "xai",
    "openrouter", "groq", "deepseek", "together",
}

# The conventional environment variable each provider's key lives in,
# checked by :func:`resolve_api_key`. Supports multiple fallback aliases.
_CONVENTIONAL_ENV: dict[str, tuple[str, ...]] = {
    "openai": ("OPENAI_API_KEY",),
    "lmstudio": ("OPENAI_API_KEY",),
    "ollama": ("OLLAMA_API_KEY",),
    "ollama-cloud": ("OLLAMA_API_KEY", "OLLAMA_CLOUD_API_KEY", "OLLAMA_KEY"),
    "anthropic": ("ANTHROPIC_API_KEY",),
    "gemini": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
    "xai": ("XAI_API_KEY", "GROK_API_KEY"),
    "openrouter": ("OPENROUTER_API_KEY",),
    "groq": ("GROQ_API_KEY",),
    "deepseek": ("DEEPSEEK_API_KEY",),
    "vllm": ("VLLM_API_KEY",),
    "together": ("TOGETHER_API_KEY",),
}

# Standard credential names per provider
_PROVIDER_CREDENTIAL_ALIASES: dict[str, tuple[str, ...]] = {
    "openai": ("openai_api_key", "external_model_api_key"),
    "lmstudio": ("lmstudio_api_key", "external_model_api_key"),
    "ollama": ("ollama_api_key", "external_model_api_key"),
    "ollama-cloud": ("ollama_cloud_api_key", "ollama_api_key", "external_model_api_key"),
    "anthropic": ("anthropic_api_key", "external_model_api_key"),
    "gemini": ("gemini_api_key", "google_api_key", "external_model_api_key"),
    "xai": ("xai_api_key", "grok_api_key", "external_model_api_key"),
    "openrouter": ("openrouter_api_key", "external_model_api_key"),
    "groq": ("groq_api_key", "external_model_api_key"),
    "deepseek": ("deepseek_api_key", "external_model_api_key"),
    "vllm": ("vllm_api_key", "external_model_api_key"),
    "together": ("together_api_key", "external_model_api_key"),
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


class ExternalModelSelectionError(ExternalModelError):
    """The operator SELECTED an external model and it cannot serve.

    Distinct from :class:`ExternalModelError` (which any probe may raise
    in passing) because this one is terminal by design: it is what
    ``make_client`` raises instead of quietly loading local weights the
    operator did not ask for. Its message is meant to be shown verbatim —
    see :func:`selection_failure_message`.
    """


def selection_failure_message(ext: ExternalModelConfig, reason: str) -> str:
    """The operator-facing explanation for a selection that can't serve.

    Names the selection (provider AND model, kept separate — they are two
    different choices and reading them back merged into one string is how
    "ollama-cloud/qwen3.5:397b" starts looking like a model name), states
    what went wrong, and lists the fixes that apply to THIS provider: a
    key for a cloud endpoint, a running server for a local one.
    """
    provider = str(getattr(ext, "provider", "") or "?")
    model = str(getattr(ext, "model", "") or "?")
    lines = [
        f"selected model cannot serve — provider {provider!r}, "
        f"model {model!r}: {reason}",
    ]
    if provider == "cli":
        lines.append(
            "  • install the CLI on PATH (`jaeger backends`) and retry"
        )
        lines.append(
            f"  • model id is the backend name (claude / codex / grok / "
            f"gemini / hermes), got {model!r}"
        )
    elif provider in _CLOUD_PROVIDERS:
        cred = str(getattr(ext, "api_key_credential", "") or "")
        envs = list(_CONVENTIONAL_ENV.get(provider, ()))
        env_named = str(getattr(ext, "api_key_env", "") or "")
        if env_named and env_named not in envs:
            envs.insert(0, env_named)
        lines.append(
            f"  • credentials: store one as `/key` (credential {cred!r}) "
            f"or export {' / '.join(envs) or 'the provider key'}"
        )
        lines.append(
            f"  • model id: confirm {model!r} exists on {provider} "
            f"(`/model list`)"
        )
    else:
        lines.append(
            f"  • start the {provider} server, then retry "
            f"(endpoint {getattr(ext, 'base_url', '?')})"
        )
    lines.append(
        "  • fix the selected provider/model — this process will not "
        "load a local GGUF/MLX as a substitute"
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Key resolution
# ---------------------------------------------------------------------------
def resolve_api_key(ext: ExternalModelConfig, layout: Any | None) -> str:
    """Resolve the provider API key, in priority order:

      1. the instance credential named ``ext.api_key_credential``
      2. provider-specific credential names (e.g. ``ollama_cloud_api_key``)
      3. generic ``external_model_api_key`` credential
      4. the environment variable named ``ext.api_key_env``
      5. the provider's conventional env vars (OPENAI_API_KEY /
         OLLAMA_CLOUD_API_KEY / ANTHROPIC_API_KEY, etc.)

    Returns ``""`` when nothing is found — fine for a local LM Studio /
    local Ollama server, which accepts any placeholder key.
    """
    if layout is not None:
        try:
            from pathlib import Path
            from jaeger_agent import credentials as creds

            # Collect candidate credential names to check in order
            candidates: list[str] = []
            if ext.api_key_credential:
                candidates.append(ext.api_key_credential)
            for alias in _PROVIDER_CREDENTIAL_ALIASES.get(ext.provider, ()):
                if alias not in candidates:
                    candidates.append(alias)

            for cred_name in candidates:
                try:
                    val = creds.get_credential(layout, cred_name)
                    if val:
                        return val
                except Exception:  # noqa: BLE001
                    pass

                try:
                    root = getattr(layout, "root", None) or getattr(layout, "credentials_dir", None) or Path(str(layout))
                    if hasattr(layout, "credentials_dir"):
                        cred_file = layout.credentials_dir / cred_name
                    else:
                        cred_file = Path(str(root)) / "credentials" / cred_name
                    if cred_file.is_file():
                        txt = cred_file.read_text(encoding="utf-8").strip()
                        if txt:
                            return txt
                except Exception:  # noqa: BLE001
                    pass
        except Exception:  # noqa: BLE001
            pass

    if ext.api_key_env:
        val = os.environ.get(ext.api_key_env, "").strip()
        if val:
            return val

    for env_var in _CONVENTIONAL_ENV.get(ext.provider, ()):
        val = os.environ.get(env_var, "").strip()
        if val:
            return val

    return ""


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
    ``gemini`` / ``xai``) genuinely require a real key.
    """
    if ext.provider in _OPENAI_COMPATIBLE:
        _placeholder = {"lmstudio": "lm-studio", "ollama": "ollama", "vllm": "vllm"}
        key = api_key or _placeholder.get(ext.provider, "")
        if not key:
            # ``_CONVENTIONAL_ENV`` holds a TUPLE of aliases per provider;
            # interpolating it raw printed "set the ('OLLAMA_API_KEY',
            # 'OLLAMA_CLOUD_API_KEY') env var" at the operator.
            envs = [ext.api_key_env] if ext.api_key_env else []
            envs += [e for e in _CONVENTIONAL_ENV.get(ext.provider, ())
                     if e not in envs]
            raise ExternalModelError(
                f"provider {ext.provider!r} needs an API key — set the "
                f"{ext.api_key_credential!r} credential or one of these "
                f"env vars: {', '.join(envs) or 'OPENAI_API_KEY'}."
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

    if ext.provider == "cli":
        # PATH-installed CLI — no API key at this layer. The binary
        # may still read ANTHROPIC_API_KEY / OPENAI_API_KEY itself.
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
        # Context-window autodetection for the TUI gauge + the
        # OpenAI-compat ``num_ctx`` injection. Local llama.cpp clients
        # already expose ``loaded_ctx``; we match that surface so the
        # status bar does not keep showing the leftover local 8K when
        # an Ollama Cloud model is serving.
        self.loaded_ctx = int(getattr(ext, "ctx", 0) or 0)
        self.num_ctx: int | None = None
        self._autodetect_ollama_context()

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
        from jaeger_agent.errors import retry_call

        is_oai = self.provider in _OPENAI_COMPATIBLE

        def _call() -> str:
            if self.provider == "cli":
                return self._chat_cli(messages, max_tokens, temperature, top_p)
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
        kwargs: dict[str, Any] = {
            "model": self.ext.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "top_p": top_p,
        }
        # Local Ollama's OpenAI-compat path ignores the model's
        # trained window unless the request sends ``options.num_ctx``.
        # Cloud already loads at max — ``self.num_ctx`` stays None there.
        if self.num_ctx:
            kwargs["extra_body"] = {"options": {"num_ctx": self.num_ctx}}
        completion = client.chat.completions.create(**kwargs)
        return completion.choices[0].message.content or ""

    def _autodetect_ollama_context(self) -> None:
        """Fill ``loaded_ctx`` / ``num_ctx`` from ``/api/show`` for Ollama."""
        if self.provider not in {"ollama", "ollama-cloud"}:
            return
        from jaeger_ai.core.models.ollama_context import (
            resolve_serving_context,
            should_inject_num_ctx,
        )

        detected, source = resolve_serving_context(
            provider=self.provider,
            model=self.model_name,
            base_url=self.ext.base_url,
            api_key=self._api_key,
            configured_ctx=int(getattr(self.ext, "ctx", 0) or 0),
        )
        if detected:
            self.loaded_ctx = detected
            # Keep the serving-lane config in lockstep so ARES / a
            # later ``_context_budget_for`` read sees the probed window
            # instead of a leftover 0 or local 8K.
            try:
                self.ext.ctx = detected
            except Exception:  # noqa: BLE001 — pydantic frozen / missing field
                pass
        if should_inject_num_ctx(
            self.provider, self.ext.base_url, self.model_name, source=source,
        ) and detected:
            self.num_ctx = detected

    def refresh_active_context(self) -> int | None:
        """Adopt Ollama's loaded window when the model is resident.

        This is deliberately separate from model-card discovery: the active
        scheduler allocation is the only value that can safely budget a turn.
        """
        if self.provider != "ollama":
            return None
        from jaeger_ai.core.models.ollama_context import query_ollama_active_context

        active = query_ollama_active_context(
            self.model_name, self.ext.base_url, self._api_key,
        )
        if active:
            self.loaded_ctx = active
            try:
                self.ext.ctx = active
            except Exception:  # noqa: BLE001
                pass
        return active

    def _chat_cli(self, messages, max_tokens, temperature, top_p) -> str:
        """One-shot completion through the installed agent CLI."""
        del max_tokens, temperature, top_p
        import threading

        from jaeger_agent.adapters.cli_backend import CliBackendAdapter
        from jaeger_agent.schemas.message_types import Message

        adapter = CliBackendAdapter(
            backend_id=self.ext.model,
            timeout_s=float(self.ext.timeout_s or 600.0),
        )
        formatted = adapter.format_messages(
            [Message(role=m["role"], content=m.get("content") or "") for m in messages],
            [],
            "",
        )
        raw = adapter.call(formatted, threading.Event())
        parsed = adapter.parse_response(raw)
        return str(parsed.get("content") or "")

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

    def unload(self) -> None:
        """No-op — an external brain holds no local weights.

        Present so teardown paths can call ``client.unload()`` without
        first asking what kind of client they hold. A ``hasattr`` guard
        at the call site is a place for the local case to get skipped by
        accident, which is the exact bug this whole lane is about."""

    # -- diagnostics -------------------------------------------------------
    def describe(self) -> str:
        if self.provider == "cli":
            return f"external · cli · {self.ext.model} · local-cli"
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
            if self.provider == "cli":
                from jaeger_agent.adapters.cli_backend import CliBackendAdapter
                result = CliBackendAdapter(
                    backend_id=self.ext.model,
                    timeout_s=min(float(self.ext.timeout_s or 60.0), 10.0),
                ).health_check()
                result.setdefault("latency_s", round(time.perf_counter() - started, 2))
                return result
            if self.provider in _OPENAI_COMPATIBLE:
                import requests

                key = self._api_key or (
                    "lm-studio" if self.provider == "lmstudio" else (
                        "ollama" if self.provider == "ollama" else ""
                    )
                )
                headers = {"Authorization": f"Bearer {key}"} if key else {}
                endpoint = self.ext.base_url.rstrip("/")
                probe_timeout = min(float(getattr(self.ext, "timeout_s", 60.0) or 60.0), 10.0)

                try:
                    resp = requests.get(
                        f"{endpoint}/models",
                        headers=headers,
                        timeout=probe_timeout,
                    )
                    resp.raise_for_status()
                except Exception as probe_err:
                    if "ollama" not in self.provider:
                        raise
                    # Ollama also answers its native ``/api/tags``, which
                    # some builds serve when the OpenAI-compat ``/models``
                    # route doesn't. Worth a second shot — but only as a
                    # second shot: if it fails too, the FIRST error is the
                    # one that explains the failure. Letting the /api/tags
                    # 404 propagate instead reported "404 Not Found" for
                    # what was actually a rejected API key.
                    root = endpoint[:-3] if endpoint.endswith("/v1") else endpoint
                    try:
                        resp2 = requests.get(
                            f"{root}/api/tags",
                            headers=headers,
                            timeout=probe_timeout,
                        )
                        resp2.raise_for_status()
                    except Exception:
                        raise probe_err from None

                active = self.refresh_active_context()
                detail = "endpoint reachable"
                if active:
                    detail += f"; active context {active:,}"
                return {"ok": True, "detail": detail,
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
            from jaeger_agent.errors import classify_exception, friendly_message
            return {
                "ok": False,
                "detail": friendly_message(exc, provider=self.provider),
                "error_class": classify_exception(exc),
                "latency_s": 0.0,
            }
