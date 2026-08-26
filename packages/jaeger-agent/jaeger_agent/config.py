"""jaeger_agent.config — the module's own settings-catalog schema slice.

Same shape and rationale as ``kokoro_tts/config.py`` and
``whisper_stt/config.py``: the module IS the engine, so its config model
lives beside its node/runtime code rather than in a host application's
``schemas.py``. An app nests this as one line (``Config.agent``) and the
settings-catalog walk renders the ``agent`` group automatically —
matching ``module.yaml``'s ``config: agent`` pointer.

Import-cycle note: ``_setting`` comes from the zero-dependency
``setting_meta`` leaf in JaegerOS, never from any application's
``schemas.py``, so this module has no import-time dependency on a host.

These fields describe WHICH MODEL to talk to and HOW HARD to try. They
deliberately do NOT describe tools, prompts, memory, or persona — those
belong to the application embedding this module. A robot that wants a
brain sets ``provider``/``model`` here and registers its own tools.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from jaeger_os.core.instance.setting_meta import _setting


class AgentConfig(BaseModel):
    """Validated defaults shown in the ``agent`` settings group."""

    model_config = ConfigDict(extra="forbid")

    provider: str = Field(
        "llama_cpp",
        json_schema_extra=_setting("agent"),
        description=(
            "Where the model runs. 'llama_cpp' (the default) loads a GGUF "
            "in-process — no server, no account, no network — and needs "
            "'model_path'. 'anthropic' uses the Anthropic Messages API. "
            "'openai', 'ollama', 'lmstudio' and 'gemini' all ride the "
            "OpenAI-compatible surface; set 'base_url' for the local ones."
        ),
    )
    model_path: str = Field(
        "",
        json_schema_extra=_setting("agent"),
        description=(
            "Path to the .gguf weights. Required by 'llama_cpp' and "
            "ignored by every other provider — a served model is named, "
            "not located."
        ),
    )
    model: str = Field(
        "",
        json_schema_extra=_setting("agent"),
        description=(
            "Model id as the provider names it (e.g. 'claude-sonnet-4-6', "
            "'gpt-4o-mini', 'qwen3:8b'). Empty uses the adapter's own "
            "default, which is rarely what you want in production. Under "
            "'llama_cpp' this is only a label — 'model_path' picks the "
            "weights — and defaults to the GGUF's filename."
        ),
    )
    base_url: str = Field(
        "",
        json_schema_extra=_setting("agent"),
        description=(
            "Override the provider endpoint — required for local servers "
            "(Ollama: http://localhost:11434/v1, LM Studio: "
            "http://localhost:1234/v1). Empty uses the provider default."
        ),
    )
    api_key_env: str = Field(
        "",
        json_schema_extra=_setting("agent"),
        description=(
            "NAME of the environment variable holding the API key — never "
            "the key itself, so a config file stays safe to commit and "
            "share. Empty falls back to the provider's conventional var "
            "(ANTHROPIC_API_KEY / OPENAI_API_KEY). Local servers need none."
        ),
    )
    system_prompt: str = Field(
        "",
        json_schema_extra=_setting("agent"),
        description=(
            "Base system prompt for the agent loop. An application that "
            "assembles its own persona/prompt leaves this empty and passes "
            "the built prompt in programmatically instead."
        ),
    )
    max_tokens: int = Field(
        4096, ge=1, le=200_000,
        json_schema_extra=_setting("agent", advanced=True),
        description="Maximum tokens the model may generate per model call.",
    )
    temperature: float = Field(
        0.0, ge=0.0, le=2.0,
        json_schema_extra=_setting("agent", advanced=True),
        description=(
            "Sampling temperature. 0.0 is the default because tool routing "
            "degrades fast with sampling noise — raise it for chat-only use."
        ),
    )
    timeout_s: float = Field(
        60.0, ge=1.0, le=600.0,
        json_schema_extra=_setting("agent", advanced=True),
        description="Per-request timeout for HTTP providers, in seconds.",
    )
    max_iterations: int = Field(
        24, ge=1, le=100,
        json_schema_extra=_setting("agent", advanced=True),
        description=(
            "Tool-call rounds allowed in one turn before the loop backstop "
            "halts it. Guards against a model that never stops calling tools."
        ),
    )
    turn_max_elapsed_s: float = Field(
        0.0, ge=0.0, le=86_400.0,
        json_schema_extra=_setting("agent", advanced=True),
        description="Whole-turn wall-clock ceiling in seconds. 0 disables it; in-flight side effects are never killed.",
    )
    turn_max_tokens: int = Field(
        0, ge=0, le=10_000_000,
        json_schema_extra=_setting("agent", advanced=True),
        description="Cumulative provider-reported token ceiling per turn. 0 disables it.",
    )
    turn_max_tool_cost: float = Field(
        0.0, ge=0.0, le=1_000_000.0,
        json_schema_extra=_setting("agent", advanced=True),
        description="Normalized tool-cost ceiling per turn. 0 disables it.",
    )

    # ── llama_cpp only ───────────────────────────────────────────────
    # Defaults match jaeger_agent.adapters.local_llama._LLAMA_DEFAULTS,
    # which in turn match JaegerAI's LlamaCppPythonClient — so a robot
    # embedding this module and the application it came from load the
    # same weights the same way, and benchmarks stay comparable.
    ctx: int = Field(
        8192, ge=512, le=1_000_000,
        json_schema_extra=_setting("agent", advanced=True),
        description=(
            "Context window to allocate, in tokens. Bigger costs RAM at "
            "load time whether or not a turn ever fills it."
        ),
    )
    gpu_layers: int = Field(
        -1, ge=-1,
        json_schema_extra=_setting("agent", advanced=True),
        description=(
            "Layers to offload to the GPU. -1 offloads all of them "
            "(correct on Apple Silicon); 0 forces CPU-only."
        ),
    )


__all__ = ["AgentConfig"]
