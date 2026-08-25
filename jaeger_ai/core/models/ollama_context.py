"""Ollama / Ollama Cloud context-window autodetection.

The OpenAI-compat ``/v1/models`` catalogue does not carry a context
length. Jaeger has to learn the window some other way or the context
guard budgets a cloud model against the local llama.cpp default
(8192) and refuses turns that would have fit.

Resolution, in order:

  1. An explicit ``external_model.ctx`` above the local default leak
     (8192) — the operator / a previous probe wrote it on purpose.
  2. Live ``POST /api/show`` against the native Ollama root
     (``https://ollama.com/api/show`` for Cloud, ``:11434/api/show``
     locally). Hosted models report GGUF ``model_info.*.context_length``
     as the real max; local models report the Modelfile ``num_ctx``
     they will actually allocate.
  3. A name-based estimate for known families (qwen / kimi / gpt-oss / …).
  4. Whatever leftover number the caller already had (local ``model.ctx``).

Local Ollama's OpenAI-compat path defaults to a small window unless
the request sends ``options.num_ctx``. Cloud models already load at
their maximum — sending a leftover local number would shrink them —
so injection is local-only, and only when ``/api/show`` actually
reported a Modelfile ``num_ctx``.
"""

from __future__ import annotations

import time
from typing import Any

# Local llama.cpp / wizard default. A cloud ``external_model.ctx`` of
# this size (or smaller) is treated as a leftover, not an override.
_LOCAL_DEFAULT_CTX = 8192
_MIN_CTX = 1024
_SHOW_TIMEOUT_S = 3.0
_SHOW_TTL_S = 3600.0

_ShowCache = dict[tuple[str, str], tuple[float, dict[str, Any]]]
_SHOW_CACHE: _ShowCache = {}


def native_ollama_root(base_url: str) -> str:
    """Strip a trailing ``/v1`` so ``/api/show`` hits the native root."""
    url = (base_url or "").rstrip("/")
    if url.endswith("/v1"):
        url = url[:-3]
    return url or "http://localhost:11434"


def is_hosted_ollama(
    provider: str = "",
    base_url: str = "",
    model: str = "",
) -> bool:
    """True for Ollama Cloud, including ``:cloud`` tags on a local server."""
    if (provider or "").lower() in {"ollama-cloud", "ollama_cloud"}:
        return True
    host = (base_url or "").lower()
    if "ollama.com" in host:
        return True
    name = (model or "").lower()
    return name.endswith(":cloud") or name.endswith("-cloud")


def estimate_model_context_length(model_name: str) -> int:
    """Infer a context window from the model family / size token.

    Used when ``/api/show`` is unreachable (no key, offline, 400).
    Conservative on unknown names: 128K, which is the common Ollama
    Cloud floor, not the local 8K default.
    """
    m = str(model_name or "").lower().strip()
    if not m:
        return _LOCAL_DEFAULT_CTX
    # DeepSeek V4 (Flash / Pro) is a 1M-window family. Check it before
    # the generic "deepseek" 64K bucket that older V2/V3 cards used.
    if "deepseek-v4" in m or "deepseek_v4" in m:
        return 1_048_576
    if "gemini" in m or "1m" in m:
        return 1_048_576
    if "kimi" in m or "256k" in m:
        return 262_144
    if "qwen3-coder" in m or "qwen3.5" in m or "qwen3" in m or "128k" in m:
        return 131_072
    if "llama-3" in m or "mistral" in m or "gpt-oss" in m:
        return 131_072
    if "sonnet" in m or "opus" in m or "haiku" in m or "claude" in m:
        return 200_000
    if "gpt-4" in m or "200k" in m:
        return 200_000
    if "deepseek" in m or "64k" in m:
        return 65_536
    if "32k" in m:
        return 32_768
    if "16k" in m:
        return 16_384
    return 131_072


def parse_show_context(data: dict[str, Any], *, hosted: bool) -> tuple[int | None, str]:
    """Pull a context length out of an ``/api/show`` payload.

    Returns ``(tokens, source)`` where ``source`` is ``"model_info"``
    (GGUF training max) or ``"num_ctx"`` (Modelfile runtime) or
    ``""`` when nothing usable was present.

    Hosted / Cloud: ``model_info`` wins — the user cannot set
    ``num_ctx``, and the operator-side default may be a cap.
    Local: ``num_ctx`` wins — that is the KV cache Ollama will
    actually allocate; using the training max would let the guard
    grow past the runtime window.
    """
    from_info = _context_from_model_info(data)
    from_params = _context_from_parameters(data)
    if hosted:
        if from_info is not None:
            return from_info, "model_info"
        if from_params is not None:
            return from_params, "num_ctx"
        return None, ""
    if from_params is not None:
        return from_params, "num_ctx"
    if from_info is not None:
        return from_info, "model_info"
    return None, ""


def query_ollama_show(
    model: str,
    base_url: str,
    api_key: str = "",
    *,
    timeout_s: float = _SHOW_TIMEOUT_S,
) -> dict[str, Any] | None:
    """``POST {root}/api/show``. Cached per ``(root, model)``. Never raises."""
    name = (model or "").strip()
    if not name:
        return None
    root = native_ollama_root(base_url)
    cache_key = (root, name)
    now = time.monotonic()
    hit = _SHOW_CACHE.get(cache_key)
    if hit is not None and (now - hit[0]) < _SHOW_TTL_S:
        return hit[1]

    headers: dict[str, str] = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    try:
        import requests

        resp = requests.post(
            f"{root}/api/show",
            json={"name": name},
            headers=headers,
            timeout=timeout_s,
        )
        if resp.status_code != 200:
            return None
        data = resp.json()
    except Exception:  # noqa: BLE001 — probe is best-effort
        return None
    if not isinstance(data, dict):
        return None
    _SHOW_CACHE[cache_key] = (now, data)
    return data


def query_ollama_active_context(
    model: str,
    base_url: str,
    api_key: str = "",
    *,
    timeout_s: float = _SHOW_TIMEOUT_S,
) -> int | None:
    """Return the context Ollama has *actually loaded* from ``/api/ps``.

    ``/api/show`` describes a model and its Modelfile. It cannot prove the
    scheduler honoured that window: Ollama may fit a smaller KV cache to the
    available GPU memory. ``/api/ps`` is therefore the authoritative runtime
    check once the model is resident. ``None`` means the model is not loaded
    (or the best-effort probe failed).
    """
    name = (model or "").strip()
    if not name:
        return None
    headers: dict[str, str] = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    try:
        import requests

        resp = requests.get(
            f"{native_ollama_root(base_url)}/api/ps",
            headers=headers,
            timeout=timeout_s,
        )
        if resp.status_code != 200:
            return None
        rows = resp.json().get("models") or []
    except Exception:  # noqa: BLE001 — diagnostics must not break boot
        return None
    for row in rows:
        if not isinstance(row, dict):
            continue
        loaded_name = str(row.get("name") or row.get("model") or "")
        if loaded_name == name:
            return _positive(row.get("context_length"))
    return None


def probe_ollama_context(
    model: str,
    base_url: str,
    api_key: str = "",
    *,
    provider: str = "",
) -> tuple[int | None, str]:
    """Live context for ``model`` at ``base_url``, plus the source tag."""
    data = query_ollama_show(model, base_url, api_key)
    if not data:
        return None, ""
    hosted = is_hosted_ollama(provider, base_url, model)
    return parse_show_context(data, hosted=hosted)


def should_inject_num_ctx(
    provider: str = "",
    base_url: str = "",
    model: str = "",
    *,
    source: str = "",
) -> bool:
    """Whether the OpenAI-compat request should send ``options.num_ctx``.

    Local Ollama defaults to a small window on ``/v1/chat/completions``
    unless the request says otherwise. Cloud (and ``:cloud`` tags
    routed through a local server) already load at the model max —
    sending a leftover local number would shrink them. Locally we inject
    either the Modelfile runtime value or an explicit operator setting.
    We deliberately do not inject a training maximum inferred from model
    metadata: that could allocate an unsafe KV cache on a laptop.
    """
    if is_hosted_ollama(provider, base_url, model):
        return False
    if (provider or "").lower() != "ollama":
        return False
    return source in {"num_ctx", "configured"}


def resolve_serving_context(
    *,
    provider: str,
    model: str,
    base_url: str,
    api_key: str = "",
    configured_ctx: int = 0,
    fallback_ctx: int | None = None,
) -> tuple[int | None, str]:
    """The window the context guard (and optional ``num_ctx``) should use.

    Returns ``(tokens, source)``. ``source`` is one of ``configured``,
    ``model_info``, ``num_ctx``, ``estimate``, ``fallback``, or ``""``.
    """
    configured = _positive(configured_ctx)
    hosted = is_hosted_ollama(provider, base_url, model)

    # An explicit number above the local default is the operator's
    # word — don't second-guess it with a probe.
    if configured is not None and configured > _LOCAL_DEFAULT_CTX:
        return configured, "configured"

    probed, source = probe_ollama_context(
        model, base_url, api_key, provider=provider,
    )
    if probed is not None:
        return probed, source

    if hosted and model:
        return estimate_model_context_length(model), "estimate"

    if configured is not None:
        return configured, "configured"

    fallback = _positive(fallback_ctx)
    if fallback is not None:
        return fallback, "fallback"
    if model:
        return estimate_model_context_length(model), "estimate"
    return None, ""


def clear_show_cache() -> None:
    """Test helper — drop the in-process ``/api/show`` cache."""
    _SHOW_CACHE.clear()


def _positive(value: Any) -> int | None:
    try:
        number = int(value or 0)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _context_from_model_info(data: dict[str, Any]) -> int | None:
    info = data.get("model_info") or {}
    if not isinstance(info, dict):
        return None
    for key, value in info.items():
        if "context_length" in str(key).lower() and isinstance(value, (int, float)):
            ctx = int(value)
            if ctx >= _MIN_CTX:
                return ctx
    return None


def _context_from_parameters(data: dict[str, Any]) -> int | None:
    params = data.get("parameters") or ""
    if not isinstance(params, str) or "num_ctx" not in params:
        return None
    for line in params.splitlines():
        if "num_ctx" not in line:
            continue
        parts = line.strip().split()
        if len(parts) < 2:
            continue
        try:
            ctx = int(parts[-1])
        except ValueError:
            continue
        if ctx >= _MIN_CTX:
            return ctx
    return None


__all__ = [
    "clear_show_cache",
    "estimate_model_context_length",
    "is_hosted_ollama",
    "native_ollama_root",
    "parse_show_context",
    "probe_ollama_context",
    "query_ollama_show",
    "query_ollama_active_context",
    "resolve_serving_context",
    "should_inject_num_ctx",
]
