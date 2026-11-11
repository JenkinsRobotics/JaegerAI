"""Model feature passport: open weights, tools, thinking, and effort modes.

Resolution order (later layers fill gaps; live probe wins on conflicts):
  1. Built-in family / model catalog
  2. Name + provider heuristics
  3. Certification overlay (REACT pass implies tool_use)
  4. Live provider fields (Ollama capabilities / thinking metadata)

This module never invents a certification PASS. It only describes what a
model is known or observed to support so pickers and adapters can decide.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Iterable, Mapping

# Effort ladder shared with ExternalModelConfig.ReasoningEffort (minus auto/provider).
EFFORT_LADDER: tuple[str, ...] = (
    "none",
    "minimal",
    "low",
    "medium",
    "high",
    "xhigh",
    "max",
)

THINKING_NONE = "none"
THINKING_STANDARD = "standard_cot"
THINKING_EXTENDED = "extended_thinking"
THINKING_REASONING_TOKENS = "reasoning_tokens"
THINKING_DELIBERATE = "deliberate_react"
THINKING_ADAPTIVE = "adaptive"

WEIGHTS_OPEN = "open_weights"
WEIGHTS_PROPRIETARY = "proprietary"
WEIGHTS_UNKNOWN = "unknown"

_LOCAL_PROVIDERS = frozenset({
    "ollama",
    "ollama-local",
    "lmstudio",
    "local",
    "vllm",
    "mlx",
    "gguf",
    "in-process",
})
_CLOUD_HOSTED_PROVIDERS = frozenset({
    "ollama-cloud",
    "ollama_cloud",
    "ollamacloud",
    "openai",
    "anthropic",
    "gemini",
    "xai",
    "openrouter",
    "groq",
    "deepseek",
    "together",
    "cli",
})

# Substring families known to publish downloadable weights.
_OPEN_WEIGHT_MARKERS: tuple[str, ...] = (
    "llama",
    "mistral",
    "mixtral",
    "qwen",
    "gemma",
    "phi-",
    "phi3",
    "phi4",
    "deepseek",
    "yi-",
    "yi:",
    "command-r",
    "nemotron",
    "granite",
    "smollm",
    "olmo",
    "falcon",
    "stablelm",
    "zephyr",
    "hermes",
    "nous-",
    "openchat",
    "vicuna",
    "wizardlm",
    "codellama",
    "codegemma",
    "starcoder",
    "solar-",
    "dbrx",
    "internlm",
    "baichuan",
    "chatglm",
    "glm-4",
    "glm4",
    "minicpm",
    "moonshot",  # some Kimi weights are open; still mark open when local
)

_PROPRIETARY_MARKERS: tuple[str, ...] = (
    "gpt-",
    "gpt4",
    "gpt5",
    "o1-",
    "o1",
    "o3-",
    "o3",
    "o4-",
    "claude",
    "gemini",
    "grok-",
    "grok",
    "chatgpt",
    "davinci",
    "sonar-",  # perplexity hosted
)

_VISION_MARKERS: tuple[str, ...] = (
    "vision",
    "vl",
    "4o",
    "4-omni",
    "gemini",
    "claude-3",
    "claude-4",
    "gpt-4",
    "gpt-5",
    "llava",
    "moondream",
    "pixtral",
    "qwen2-vl",
    "qwen2.5-vl",
    "qwen3-vl",
    "gemma-3",
    "minicpm-v",
)

_REASONING_MARKERS: tuple[str, ...] = (
    "o1",
    "o3",
    "o4",
    "r1",
    "reasoner",
    "thinking",
    "qwq",
    "deepseek-r",
    "gpt-5",
)


@dataclass(frozen=True)
class ModelFeaturePassport:
    """Operator-facing capability summary for one model id."""

    model_id: str
    provider_id: str = ""
    open_weights: bool | None = None
    weights_class: str = WEIGHTS_UNKNOWN
    tool_use: bool | None = None
    tool_call_format: str = "openai_function_call"
    parallel_tool_support: bool | None = None
    vision: bool | None = None
    thinking_mode: str = THINKING_NONE
    effort_modes: tuple[str, ...] = ()
    effort_param: str = ""
    context_length: int | None = None
    sources: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()
    live_capabilities: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        # Stable JSON-friendly shapes.
        data["effort_modes"] = list(self.effort_modes)
        data["sources"] = list(self.sources)
        data["notes"] = list(self.notes)
        data["live_capabilities"] = list(self.live_capabilities)
        return data

    @property
    def supports_thinking(self) -> bool:
        return self.thinking_mode not in {THINKING_NONE, ""}

    @property
    def supports_effort(self) -> bool:
        return bool(self.effort_modes)


# Explicit catalog keyed by normalized model id (lowercase, no @provider prefix).
# Keep entries sparse: family heuristics cover the long tail.
_FEATURE_CATALOG: dict[str, dict[str, Any]] = {
    "gpt-4o": {
        "open_weights": False,
        "weights_class": WEIGHTS_PROPRIETARY,
        "tool_use": True,
        "parallel_tool_support": True,
        "vision": True,
        "thinking_mode": THINKING_NONE,
        "tool_call_format": "openai_function_call",
        "context_length": 128000,
    },
    "gpt-4.1": {
        "open_weights": False,
        "weights_class": WEIGHTS_PROPRIETARY,
        "tool_use": True,
        "parallel_tool_support": True,
        "vision": True,
        "thinking_mode": THINKING_NONE,
        "tool_call_format": "openai_function_call",
    },
    "gpt-5": {
        "open_weights": False,
        "weights_class": WEIGHTS_PROPRIETARY,
        "tool_use": True,
        "parallel_tool_support": True,
        "vision": True,
        "thinking_mode": THINKING_REASONING_TOKENS,
        "effort_modes": ("none", "minimal", "low", "medium", "high", "xhigh"),
        "effort_param": "reasoning_effort",
        "tool_call_format": "openai_function_call",
    },
    "o1": {
        "open_weights": False,
        "weights_class": WEIGHTS_PROPRIETARY,
        "tool_use": True,
        "thinking_mode": THINKING_REASONING_TOKENS,
        "effort_modes": ("low", "medium", "high"),
        "effort_param": "reasoning_effort",
    },
    "o1-mini": {
        "open_weights": False,
        "weights_class": WEIGHTS_PROPRIETARY,
        "tool_use": False,
        "thinking_mode": THINKING_REASONING_TOKENS,
        "effort_modes": ("low", "medium", "high"),
        "effort_param": "reasoning_effort",
    },
    "o3-mini": {
        "open_weights": False,
        "weights_class": WEIGHTS_PROPRIETARY,
        "tool_use": True,
        "thinking_mode": THINKING_REASONING_TOKENS,
        "effort_modes": ("low", "medium", "high"),
        "effort_param": "reasoning_effort",
    },
    "claude-3-7-sonnet-20250219": {
        "open_weights": False,
        "weights_class": WEIGHTS_PROPRIETARY,
        "tool_use": True,
        "parallel_tool_support": True,
        "vision": True,
        "thinking_mode": THINKING_EXTENDED,
        "effort_modes": ("none", "low", "medium", "high", "max"),
        "effort_param": "thinking",
        "tool_call_format": "anthropic_tools",
        "context_length": 200000,
    },
    "claude-sonnet-4-6": {
        "open_weights": False,
        "weights_class": WEIGHTS_PROPRIETARY,
        "tool_use": True,
        "parallel_tool_support": True,
        "vision": True,
        "thinking_mode": THINKING_ADAPTIVE,
        "effort_modes": ("none", "low", "medium", "high", "max"),
        "effort_param": "thinking",
        "tool_call_format": "anthropic_tools",
    },
    "claude-opus-4": {
        "open_weights": False,
        "weights_class": WEIGHTS_PROPRIETARY,
        "tool_use": True,
        "parallel_tool_support": True,
        "vision": True,
        "thinking_mode": THINKING_ADAPTIVE,
        "effort_modes": ("none", "low", "medium", "high", "max"),
        "effort_param": "thinking",
        "tool_call_format": "anthropic_tools",
    },
    "gemini-2.0-flash": {
        "open_weights": False,
        "weights_class": WEIGHTS_PROPRIETARY,
        "tool_use": True,
        "vision": True,
        "thinking_mode": THINKING_NONE,
        "tool_call_format": "openai_function_call",
    },
    "gemini-2.5-pro": {
        "open_weights": False,
        "weights_class": WEIGHTS_PROPRIETARY,
        "tool_use": True,
        "vision": True,
        "thinking_mode": THINKING_EXTENDED,
        "effort_modes": ("low", "medium", "high"),
        "effort_param": "thinking_config",
        "tool_call_format": "openai_function_call",
    },
    "grok-3": {
        "open_weights": False,
        "weights_class": WEIGHTS_PROPRIETARY,
        "tool_use": True,
        "thinking_mode": THINKING_STANDARD,
        "effort_modes": ("low", "high"),
        "effort_param": "reasoning_effort",
        "tool_call_format": "openai_function_call",
    },
    "grok-4": {
        "open_weights": False,
        "weights_class": WEIGHTS_PROPRIETARY,
        "tool_use": True,
        "thinking_mode": THINKING_REASONING_TOKENS,
        "effort_modes": ("low", "high"),
        "effort_param": "reasoning_effort",
        "tool_call_format": "openai_function_call",
    },
    "deepseek-reasoner": {
        "open_weights": True,
        "weights_class": WEIGHTS_OPEN,
        "tool_use": False,
        "thinking_mode": THINKING_REASONING_TOKENS,
        "effort_param": "reasoning_effort",
        "tool_call_format": "openai_function_call",
    },
    "deepseek-chat": {
        "open_weights": True,
        "weights_class": WEIGHTS_OPEN,
        "tool_use": True,
        "thinking_mode": THINKING_NONE,
        "tool_call_format": "openai_function_call",
    },
    "deepseek-r1": {
        "open_weights": True,
        "weights_class": WEIGHTS_OPEN,
        "tool_use": False,
        "thinking_mode": THINKING_REASONING_TOKENS,
    },
    "kimi-k2.7-code:cloud": {
        "open_weights": False,
        "weights_class": WEIGHTS_PROPRIETARY,
        "tool_use": True,
        "parallel_tool_support": True,
        "vision": True,
        "thinking_mode": THINKING_DELIBERATE,
        "tool_call_format": "openai_function_call",
        "context_length": 32768,
    },
    "glm-5.3-flash:cloud": {
        "open_weights": False,
        "weights_class": WEIGHTS_PROPRIETARY,
        "tool_use": False,
        "thinking_mode": THINKING_STANDARD,
        "effort_modes": ("none", "minimal", "low", "medium", "high", "xhigh", "max"),
        "effort_param": "reasoning_effort",
    },
    "qwen2.5-coder:7b": {
        "open_weights": True,
        "weights_class": WEIGHTS_OPEN,
        "tool_use": True,
        "parallel_tool_support": False,
        "thinking_mode": THINKING_NONE,
        "tool_call_format": "openai_function_call",
        "context_length": 16384,
    },
    "gemma-4-26b:latest": {
        "open_weights": True,
        "weights_class": WEIGHTS_OPEN,
        "tool_use": None,
        "thinking_mode": THINKING_NONE,
    },
}


def normalize_model_id(model_name: str, provider_id: str = "") -> tuple[str, str]:
    """Strip picker prefixes; return (model_id, provider_hint)."""
    raw = str(model_name or "").strip()
    provider = str(provider_id or "").strip().lower()
    if raw.startswith("@"):
        raw = raw[1:]
    if ":" in raw:
        head, tail = raw.split(":", 1)
        head_l = head.lower()
        if head_l in {
            "ollama", "ollama-cloud", "ollama-local", "ollama_cloud", "openai",
            "anthropic", "gemini", "xai", "lmstudio", "openrouter", "groq",
            "deepseek", "vllm", "together", "cli", "local",
        }:
            if not provider:
                provider = head_l
            raw = tail
    return raw, provider


def _catalog_match(model_id: str) -> dict[str, Any] | None:
    key = model_id.strip().lower()
    if key in _FEATURE_CATALOG:
        return dict(_FEATURE_CATALOG[key])
    # Prefix / family soft match (longest key wins).
    best: tuple[int, dict[str, Any]] | None = None
    for catalog_key, payload in _FEATURE_CATALOG.items():
        if key.startswith(catalog_key) or catalog_key.startswith(key):
            score = len(catalog_key)
            if best is None or score > best[0]:
                best = (score, dict(payload))
    return best[1] if best else None


def _contains_any(text: str, markers: Iterable[str]) -> bool:
    return any(m in text for m in markers)


def _heuristic_weights(model_id: str, provider_id: str, *, remote_host: str | None) -> tuple[bool | None, str]:
    low = model_id.lower()
    prov = provider_id.lower()
    if remote_host or prov in _CLOUD_HOSTED_PROVIDERS - {"deepseek", "openrouter", "together", "groq"}:
        if _contains_any(low, _PROPRIETARY_MARKERS):
            return False, WEIGHTS_PROPRIETARY
        if _contains_any(low, _OPEN_WEIGHT_MARKERS):
            # Hosted open-weight model (e.g. deepseek via API, qwen on ollama cloud).
            return True, WEIGHTS_OPEN
        if prov in {"openai", "anthropic", "gemini", "xai"}:
            return False, WEIGHTS_PROPRIETARY
        return None, WEIGHTS_UNKNOWN
    if prov in _LOCAL_PROVIDERS or low.endswith((".gguf",)):
        if _contains_any(low, _PROPRIETARY_MARKERS):
            return False, WEIGHTS_PROPRIETARY
        return True, WEIGHTS_OPEN
    if _contains_any(low, _PROPRIETARY_MARKERS):
        return False, WEIGHTS_PROPRIETARY
    if _contains_any(low, _OPEN_WEIGHT_MARKERS):
        return True, WEIGHTS_OPEN
    return None, WEIGHTS_UNKNOWN


def _heuristic_vision(model_id: str) -> bool:
    return _contains_any(model_id.lower(), _VISION_MARKERS)


def _heuristic_thinking(model_id: str, provider_id: str) -> tuple[str, tuple[str, ...], str]:
    low = model_id.lower()
    prov = provider_id.lower()
    if "claude" in low or prov == "anthropic":
        if any(x in low for x in ("sonnet", "opus", "3-7", "4")):
            return THINKING_ADAPTIVE, ("none", "low", "medium", "high", "max"), "thinking"
    if any(x in low for x in ("o1", "o3", "o4", "gpt-5")):
        return THINKING_REASONING_TOKENS, ("none", "minimal", "low", "medium", "high", "xhigh"), "reasoning_effort"
    if "deepseek-r" in low or "reasoner" in low or "r1" in low:
        return THINKING_REASONING_TOKENS, (), "reasoning_effort"
    if "qwq" in low or "thinking" in low:
        return THINKING_EXTENDED, ("low", "medium", "high"), "think"
    if "glm-5" in low or "glm5" in low:
        return THINKING_STANDARD, tuple(EFFORT_LADDER), "reasoning_effort"
    if "grok" in low:
        return THINKING_REASONING_TOKENS, ("low", "high"), "reasoning_effort"
    if _contains_any(low, _REASONING_MARKERS):
        return THINKING_STANDARD, (), ""
    return THINKING_NONE, (), ""


def _heuristic_tools(model_id: str, provider_id: str) -> bool | None:
    low = model_id.lower()
    if any(x in low for x in ("o1-mini", "deepseek-reasoner", "deepseek-r1", "r1-distill")):
        return False
    if provider_id in {"openai", "anthropic", "gemini", "xai", "openrouter", "groq"}:
        return True
    if any(x in low for x in ("coder", "instruct", "chat", "sonnet", "opus", "gpt-", "claude", "kimi", "qwen")):
        return True
    return None


def _tool_format_for(provider_id: str, model_id: str) -> str:
    if provider_id == "anthropic" or model_id.lower().startswith("claude"):
        return "anthropic_tools"
    return "openai_function_call"


def _merge_bool(current: bool | None, incoming: bool | None) -> bool | None:
    if incoming is None:
        return current
    return incoming


def _normalize_effort_modes(values: Iterable[Any]) -> tuple[str, ...]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in values:
        if raw is True:
            token = "medium"
        elif raw is False:
            token = "none"
        else:
            token = str(raw).strip().lower()
        if not token or token in seen:
            continue
        seen.add(token)
        out.append(token)
    return tuple(out)


def resolve_model_features(
    model_name: str,
    *,
    provider_id: str = "",
    live: Mapping[str, Any] | None = None,
    state_root: Any = None,
) -> ModelFeaturePassport:
    """Build a feature passport from catalog, heuristics, certs, and live probe."""
    model_id, provider = normalize_model_id(model_name, provider_id)
    live = dict(live or {})
    sources: list[str] = []
    notes: list[str] = []

    open_weights: bool | None = None
    weights_class = WEIGHTS_UNKNOWN
    tool_use: bool | None = None
    parallel: bool | None = None
    vision: bool | None = None
    thinking_mode = THINKING_NONE
    effort_modes: tuple[str, ...] = ()
    effort_param = ""
    context_length: int | None = None
    tool_format = _tool_format_for(provider, model_id)

    catalog = _catalog_match(model_id)
    if catalog:
        sources.append("catalog")
        open_weights = catalog.get("open_weights", open_weights)
        weights_class = str(catalog.get("weights_class") or weights_class)
        tool_use = catalog.get("tool_use", tool_use)
        parallel = catalog.get("parallel_tool_support", parallel)
        vision = catalog.get("vision", vision)
        thinking_mode = str(catalog.get("thinking_mode") or thinking_mode)
        effort_modes = _normalize_effort_modes(catalog.get("effort_modes") or ())
        effort_param = str(catalog.get("effort_param") or effort_param)
        if catalog.get("context_length"):
            context_length = int(catalog["context_length"])
        if catalog.get("tool_call_format"):
            tool_format = str(catalog["tool_call_format"])

    # Heuristics fill gaps.
    sources.append("heuristic")
    remote_host = live.get("remote_host")
    h_open, h_class = _heuristic_weights(model_id, provider, remote_host=remote_host)
    if open_weights is None:
        open_weights = h_open
    if weights_class == WEIGHTS_UNKNOWN:
        weights_class = h_class
    if vision is None:
        vision = _heuristic_vision(model_id)
    if tool_use is None:
        tool_use = _heuristic_tools(model_id, provider)
    if thinking_mode == THINKING_NONE and not effort_modes:
        t_mode, t_efforts, t_param = _heuristic_thinking(model_id, provider)
        thinking_mode = t_mode
        effort_modes = t_efforts
        effort_param = t_param or effort_param

    # Certification overlay — REACT pass means tools are expected to work.
    try:
        from jaeger_ai.core.entity.model_capabilities import role_status, PASS
        react = role_status(model_id, "react", state_root)
        chat = role_status(model_id, "chat", state_root)
        vision_role = role_status(model_id, "vision", state_root)
        if react == PASS:
            tool_use = True
            sources.append("certification")
            notes = notes + ("react_certified_pass",)
        elif react == "fail":
            # Explicit fail does not force tool_use False (operator may still pick it),
            # but records the cert signal.
            sources.append("certification")
            notes = notes + ("react_certified_fail",)
        if vision_role == PASS:
            vision = True
            if "certification" not in sources:
                sources.append("certification")
        if chat == PASS and "certification" not in sources:
            sources.append("certification")
    except Exception:
        pass

    # Live probe fields win.
    live_caps_raw = live.get("capabilities") or live.get("live_capabilities") or []
    live_caps = tuple(str(c).lower() for c in live_caps_raw if c)
    if live_caps:
        sources.append("live_probe")
        if "tools" in live_caps or "tool" in live_caps:
            tool_use = True
        if "vision" in live_caps or "image" in live_caps or "multimodal" in live_caps:
            vision = True
        if "thinking" in live_caps or "reasoning" in live_caps:
            if thinking_mode == THINKING_NONE:
                thinking_mode = THINKING_EXTENDED

    thinking_meta = live.get("thinking")
    if isinstance(thinking_meta, Mapping):
        sources.append("live_thinking")
        values = thinking_meta.get("values") or []
        normalized = _normalize_effort_modes(values)
        if normalized:
            effort_modes = normalized
            if thinking_mode == THINKING_NONE:
                thinking_mode = THINKING_EXTENDED
            effort_param = effort_param or "think"
        default = thinking_meta.get("default")
        if default is not None and not effort_param:
            effort_param = "think"

    if live.get("context_length") or live.get("context_window"):
        try:
            context_length = int(live.get("context_length") or live.get("context_window"))
        except (TypeError, ValueError):
            pass

    # Local non-cloud Ollama weights are on-device even when family is unknown.
    if provider in {"ollama", "ollama-local", "lmstudio", "local", "vllm", "mlx"} and not remote_host:
        if open_weights is None:
            open_weights = True
        if weights_class == WEIGHTS_UNKNOWN:
            weights_class = WEIGHTS_OPEN

    # Cloud :cloud suffix without remote_host still means hosted.
    if model_id.endswith(":cloud") or model_id.endswith("-cloud"):
        if open_weights is None and not _contains_any(model_id.lower(), _OPEN_WEIGHT_MARKERS):
            open_weights = False
            weights_class = WEIGHTS_PROPRIETARY if weights_class == WEIGHTS_UNKNOWN else weights_class

    # Deduplicate sources while preserving order.
    seen_src: set[str] = set()
    ordered_sources = []
    for s in sources:
        if s not in seen_src:
            seen_src.add(s)
            ordered_sources.append(s)

    return ModelFeaturePassport(
        model_id=model_id,
        provider_id=provider,
        open_weights=open_weights,
        weights_class=weights_class,
        tool_use=tool_use,
        tool_call_format=tool_format,
        parallel_tool_support=parallel,
        vision=vision,
        thinking_mode=thinking_mode,
        effort_modes=effort_modes,
        effort_param=effort_param,
        context_length=context_length,
        sources=tuple(ordered_sources),
        notes=tuple(notes),
        live_capabilities=live_caps,
    )


def features_dict_for_inventory(
    model_name: str,
    *,
    provider_id: str = "",
    live: Mapping[str, Any] | None = None,
    state_root: Any = None,
) -> dict[str, Any]:
    """Compact feature block for inventory / API payloads."""
    passport = resolve_model_features(
        model_name,
        provider_id=provider_id,
        live=live,
        state_root=state_root,
    )
    return {
        "open_weights": passport.open_weights,
        "weights_class": passport.weights_class,
        "tool_use": passport.tool_use,
        "tool_call_format": passport.tool_call_format,
        "parallel_tool_support": passport.parallel_tool_support,
        "vision": passport.vision,
        "thinking_mode": passport.thinking_mode,
        "supports_thinking": passport.supports_thinking,
        "effort_modes": list(passport.effort_modes),
        "effort_param": passport.effort_param or None,
        "context_length": passport.context_length,
        "sources": list(passport.sources),
        "live_capabilities": list(passport.live_capabilities),
    }


def supported_effort_modes(
    model_name: str,
    *,
    provider_id: str = "",
    live: Mapping[str, Any] | None = None,
) -> tuple[str, ...]:
    return resolve_model_features(
        model_name, provider_id=provider_id, live=live,
    ).effort_modes


def validate_effort_for_model(
    model_name: str,
    effort: str | None,
    *,
    provider_id: str = "",
    live: Mapping[str, Any] | None = None,
) -> str | None:
    """Return normalized effort or None for auto/provider.

    Raises ValueError when the model advertises a closed set that excludes
    the requested level. Unknown sets accept the global ladder.
    """
    value = str(effort or "auto").strip().lower()
    if value in {"", "auto", "provider"}:
        return None
    if value not in EFFORT_LADDER:
        raise ValueError(f"Unsupported reasoning effort: {effort}")
    modes = supported_effort_modes(model_name, provider_id=provider_id, live=live)
    if modes and value not in modes:
        raise ValueError(
            f"{model_name} does not support reasoning effort {value!r}; "
            f"supported: {', '.join(modes)}"
        )
    return value


def probe_ollama_show(
    model_name: str,
    *,
    base_url: str | None = None,
    timeout: float = 2.0,
) -> dict[str, Any]:
    """Fetch Ollama /api/show metadata used for thinking + capability enrichment.

    Never raises — empty dict on any failure.
    """
    try:
        import requests
        from jaeger_ai.contract.ports import OLLAMA_URL
        root = (base_url or OLLAMA_URL).rstrip("/")
        resp = requests.post(
            f"{root}/api/show",
            json={"model": model_name},
            timeout=timeout,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    out: dict[str, Any] = {}
    caps = data.get("capabilities")
    if isinstance(caps, list):
        out["capabilities"] = [str(c) for c in caps]
    thinking = data.get("thinking")
    if isinstance(thinking, dict):
        out["thinking"] = thinking
    # Some builds nest details under model_info / details.
    details = data.get("details") if isinstance(data.get("details"), dict) else {}
    families = details.get("families") or data.get("families")
    if families:
        out["families"] = families
    model_info = data.get("model_info") if isinstance(data.get("model_info"), dict) else {}
    for key in ("general.architecture", "llama.context_length", "qwen2.context_length"):
        if key in model_info and "context_length" not in out:
            try:
                if "context_length" in key:
                    out["context_length"] = int(model_info[key])
            except (TypeError, ValueError):
                pass
    return out
