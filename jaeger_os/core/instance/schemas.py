"""Pydantic v2 schemas for the on-disk files an instance owns.

Three files live at the root of every instance directory and are validated
against these models on every read. Hand-edits to the YAML are welcome —
the schemas exist so a typo doesn't silently corrupt runtime state.

  identity.yaml   → Identity   (name, role, personality, voice tone)
  config.yaml     → Config     (model endpoint, runtime knobs)
  manifest.json   → Manifest   (schema_version pin, instance_name, created_at)

The setup wizard writes all three; the agent loop reads them; the agent
itself is forbidden from editing identity/config/manifest by the
sandboxed file tools.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

# ``_setting``'s canonical definition moved to ``setting_meta.py`` at 0.8
# M1 so an engine-module's config slice (e.g. ``jaeger_os/nodes/
# kokoro_tts/config.py``) can carry catalog metadata without importing
# this file — breaking what would otherwise be a schemas <-> module
# circular import (see this file's ``Config`` import site, below).
# Re-exported here so every existing ``_setting(...)`` call in this file
# is unchanged.
from jaeger_os.core.instance.setting_meta import _setting


# Bumped whenever the on-disk shape of identity.yaml / config.yaml
# (or any other instance-side file) changes in a way that needs a
# migration.  Stored in manifest.json on instance creation; mismatch
# with the installed framework triggers the per-instance migration
# runner (see ``core/instance/migrations.py``).
#
# Naming convention (2026-06-09): SCHEMA_VERSION mirrors the
# framework version it ships with — ``0.X.Y``.  The previous
# two-version scheme (framework 0.4.0 + schema 1.2.0) was confusing
# overhead and got unified.  Per ``feedback-no-back-compat-pre-1.0``
# the pre-1.0 legacy migration chain (v1_0_0 → v1_1_0 → v1_2_0) was
# deleted at the same time.
#
# Future migrations are named for the framework version they ship
# with — e.g. ``v0_5_0_to_v0_6_0.py``.  Releases that don't change
# schema simply don't ship a migration file; the runner bumps the
# manifest at boot.
SCHEMA_VERSION = "0.5.0"


# ---------------------------------------------------------------------------
# identity.yaml
# ---------------------------------------------------------------------------
class Identity(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(..., min_length=1, max_length=64, description="Agent's display name")
    role: str = Field(..., min_length=1, max_length=256, description="One-line role description")
    personality: str = Field(..., min_length=1, max_length=2048)
    voice_tone: str = Field("neutral", max_length=64)
    # Kokoro voice identifier (e.g. ``am_michael`` for a male voice,
    # ``af_heart`` for a female voice). ``None`` falls back to the
    # plugin-level default. Picked per-instance so Jarvis and Lilith
    # don't share the same voice.
    voice_id: str | None = Field(None, max_length=64,
                                 description="Kokoro voice id (am_*, af_*)")
    # The instance's profile picture — the agent's OWN face, independent of
    # whatever character it's playing. Absolute, or relative to the instance
    # dir. ``None`` → surfaces fall back to the active character's card, so a
    # fresh instance always has a face; switching persona changes that default
    # only until the operator sets a picture here.
    avatar: str | None = Field(None, max_length=512,
                               description="Path to the instance profile picture")

    @field_validator("name")
    @classmethod
    def _no_path_chars(cls, v: str) -> str:
        if any(c in v for c in "/\\:*?\"<>|"):
            raise ValueError("name must not contain path-illegal characters")
        return v


# ---------------------------------------------------------------------------
# config.yaml
# ---------------------------------------------------------------------------
class ModelConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # In-process llama-cpp-python is the only adapter Jaeger M1 supports.
    # M2 may add OpenAI-compatible HTTP endpoints; the discriminator stays here
    # so we don't have to migrate config files later.
    # llama_cpp_python = GGUF via llama.cpp (default; broadest model
    #   support, the JROS 0.3.0 + 0.4.0 reference path).
    # mlx_lm = Apple-Silicon-native MLX backend (1.5–2× faster
    #   per-token on M-series; model_path points at an MLX model
    #   directory, NOT a GGUF — e.g.
    #   ``~/.lmstudio/models/mlx-community/Qwen3.5-9B-MLX-4bit/``).
    #   Dispatcher already routes to MlxClient in main.py; this
    #   Literal just makes the option config-visible.  Added 0.4.x.
    backend: Literal["llama_cpp_python", "mlx_lm"] = "llama_cpp_python"
    model_path: Path = Field(
        ...,
        description=(
            "Absolute path to model weights.  For llama_cpp_python: "
            "the GGUF file.  For mlx_lm: the model directory "
            "containing config.json + weight shards."
        ),
    )
    ctx: int = Field(
        8192, ge=512, le=131_072,
        json_schema_extra=_setting("model", restart=True),
        description="Context window (tokens) for the WORKER lane — the "
                    "agent loop's llama.cpp context. Bigger = longer "
                    "conversations before compaction, at the cost of KV "
                    "memory and cold-prefill time. Applies on restart.",
    )
    aux_ctx: int = Field(
        4096, ge=0, le=131_072,
        json_schema_extra=_setting("model", restart=True),
        description="Context window (tokens) for the AUX lane — a second "
                    "llama.cpp context on the SAME loaded model that runs "
                    "the bounded side-channel calls (persona output "
                    "filter, skip-final finalizer, reflection, deep-think "
                    "planning, memory review) so they never evict the "
                    "worker lane's warm KV prefix. Small on purpose: aux "
                    "prompts are bounded, and every aux token is KV "
                    "memory. 0 disables the lane (side calls then share "
                    "the worker context and re-trigger full re-prefills). "
                    "Applies on restart.",
    )
    gpu_layers: int = Field(-1, description="-1 = offload all, 0 = CPU-only")
    n_batch: int = 512
    n_ubatch: int = 512
    flash_attn: bool = True
    threads: int | None = None
    max_tokens: int = Field(
        4096, ge=16, le=32_768,
        json_schema_extra=_setting("model", restart=True),
        description="Per-turn output cap the in-process adapter passes "
                    "as ``max_tokens`` into ``create_chat_completion``. "
                    "Default 4096 matches 0.1.0 behaviour — leaves "
                    "headroom for reasoning models that legitimately "
                    "spend hundreds of tokens in a single turn. Lower "
                    "(1024-1536) for routing-heavy use to cut "
                    "wall-clock when the model would otherwise ramble "
                    "to the cap; raise only if a specific deep-think "
                    "model truncates short. Pure speed knob — no "
                    "effect on per-token rate.",
    )
    extra_gguf_dirs: list[str] = Field(
        default_factory=list,
        description="Extra directories to scan for local .gguf models, "
                    "beyond the repo models/, the JROS cache, and LM "
                    "Studio. Add/remove with the model_location tool; "
                    "persisted here so the agent can extend the scan set "
                    "without editing core code.",
    )
    stall_timeout_s: float | None = Field(
        None,
        description="Wall-clock seconds before the agent declares the "
                    "model call stalled and surfaces a recoverable error "
                    "(``stalled`` halt reason). ``None`` uses the backend "
                    "default — 120s for in-process llama-cpp (allows for "
                    "long cold prefills + 30B-class decode), 30s for HTTP "
                    "backends. The pathological Metal prefill hangs we've "
                    "seen are multi-minute, so 120s catches them without "
                    "false-positive on legitimate slow decodes. Lower the "
                    "value to surface stalls faster (risk: cutting off "
                    "legitimate long answers); raise it to be more "
                    "patient. Use ``jaeger kill`` from another terminal "
                    "to nuke a hung process irrespective of this value.",
    )


class DisplayConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    show_latency: bool = Field(
        False, json_schema_extra=_setting("display"),
        description="Show per-turn wall-clock latency after each reply.")
    show_tool_activity: bool = Field(
        True, json_schema_extra=_setting("display"),
        description="Show the agent's live tool-use activity during a turn.")
    show_help_on_start: bool = Field(
        True, json_schema_extra=_setting("display"),
        description="Print the help banner when a chat surface opens.")
    # The live activity stream (thoughts + tool use) shown DURING a turn, and
    # what becomes of it once the final reply lands:
    #   "full"    — keep the whole dimmed trace above the reply (default)
    #   "summary" — collapse it to one dimmed "N steps · …" line
    #   "clear"   — show it live, remove it when the reply arrives
    #   "off"     — no live stream (just the spinner)
    activity_trace: Literal["full", "summary", "clear", "off"] = Field(
        "full", json_schema_extra=_setting("display"),
        description="What becomes of the live thought/tool trace once the "
                    "reply lands: full (keep it), summary (collapse to one "
                    "line), clear (remove it), off (no live stream).")
    # Thin accent rule between turns in the windowed chat transcript
    # (operator-requested keeper, 2026-07-05). The TUI draws its own rules.
    turn_separators: bool = Field(
        True, json_schema_extra=_setting("display"),
        description="Draw a thin accent rule between turns in the windowed "
                    "chat transcript.")
    # What pressing Enter does while the agent is mid-turn (hermes parity):
    #   "interrupt" — cancel the running turn, run the new message now
    #   "queue"     — run the new message after the current turn finishes
    #   "steer"     — inject the message into the running turn as guidance
    busy_input_mode: Literal["interrupt", "queue", "steer"] = Field(
        "interrupt", json_schema_extra=_setting("display"),
        description="What pressing Enter does mid-turn: interrupt (cancel + "
                    "run now), queue (run after), steer (inject as guidance).")


class RetentionConfig(BaseModel):
    """M3 will wire log rotation + memory cap to these; M1 just persists them."""
    model_config = ConfigDict(extra="forbid")
    logs_keep_days: int = Field(
        30, ge=1, json_schema_extra=_setting("retention"),
        description="Days of logs to keep before rotation prunes them.")
    logs_max_total_mb: int = Field(
        1024, ge=16, json_schema_extra=_setting("retention"),
        description="Hard cap (MB) on total log size before oldest are pruned.")
    memory_max_mb: int = Field(
        1024, ge=16, json_schema_extra=_setting("retention"),
        description="Hard cap (MB) on the agent's memory store.")


class SkillsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled_base_skills: list[str] = Field(default_factory=list,
        description="Empty = enable all; otherwise allowlist by skill folder name.")
    disabled_playbooks: list[str] = Field(default_factory=list,
        description="Playbook-skill names to hide from discovery and the prompt index.")
    hot_reload: bool = False
    run_smoke_tests: bool = True
    include_self_improvement_contract: bool = Field(
        default=False,
        description=(
            "Inject the full v2 self-improvement contract (skill versioning, "
            "smoke tests, rollback rules) into the system prompt. Off by "
            "default — adds ~900 words and only matters when the agent is "
            "actively authoring new skills. Routing benchmarks run leaner "
            "without it."
        ),
    )


class DeepThinkConfig(BaseModel):
    """Deep Think autonomous-mode settings. See docs/deep_think_design.md."""

    model_config = ConfigDict(extra="forbid")
    coder_model: str = Field(
        "gemma-4-26b-a4b-it-qat-q4_0",
        json_schema_extra=_setting("autonomy", advanced=True),
        description="Model swapped in for Deep Think skill authoring.",
    )
    auto_idle_minutes: int = Field(
        30, ge=0, le=240,
        json_schema_extra=_setting("autonomy"),
        description=(
            "Minutes of no user input before the TUI auto-enters Deep "
            "Think (when there's approved queued work) — the Jaeger uses "
            "free time to work its own queue. Default 30. 0 = OFF: Deep "
            "Think only starts via /deepthink start."
        ),
    )


class RuntimeConfig(BaseModel):
    """Per-format inference-engine selection — JROS's equivalent of LM
    Studio's Settings → Runtime panel.

    Each model FORMAT (detected from the weights on disk: a ``.gguf``
    file vs an MLX directory) maps to a chosen ENGINE. ``"auto"`` lets
    :func:`jaeger_os.core.models.engine_registry.resolve_engine` pick the
    best installed engine for the format (and, for MLX, route the
    ``*_unified`` builds that only ``mlx-vlm`` can load).

    Engine ids come from the registry:
      • GGUF →  ``llama-cpp-python``
      • MLX  →  ``mlx-lm`` (text) · ``mlx-vlm`` (multimodal / unified)
    """

    model_config = ConfigDict(extra="forbid")
    gguf_engine: str = Field(
        "auto",
        description="Engine for GGUF models: 'auto' | 'llama-cpp-python'.",
    )
    mlx_engine: str = Field(
        "auto",
        description="Engine for MLX models: 'auto' | 'mlx-lm' | 'mlx-vlm'.",
    )


class VoiceConfig(BaseModel):
    """Always-on voice settings.

    A Jaeger is embodied — like a person, it can always listen — but
    the always-on mic without ``speexdsp`` for acoustic echo
    cancellation picks up background podcast/youtube audio nearby and
    feeds it to the agent. VOICE-1 in docs/ROADMAP_0.2.0.md flips
    ``enabled`` to OFF by default so a fresh install doesn't surprise
    a user with an open mic. Voice still works — flip ``enabled`` on
    in config.yaml or via ``/voice on`` after first run, after
    confirming the speexdsp story for your setup.

    Every field is tunable live from the TUI with ``/voice`` and
    persisted back to config.yaml.
    """

    # ``ignore`` (not ``forbid``): the LLM voice gate was removed
    # 2026-06-16, dropping the ``llm_gate`` / ``pending_queue`` /
    # ``follow_up_retry`` / ``pending_turn_max_age_s`` fields.  Tolerate
    # those stale keys in existing config.yaml files instead of failing
    # to load.
    model_config = ConfigDict(extra="ignore")
    enabled: bool = Field(
        False,
        json_schema_extra=_setting("voice"),
        description="Mic live from TUI boot. Off (default) = text-only TUI.",
    )
    speak_replies: bool = Field(
        True,
        json_schema_extra=_setting("voice"),
        description=(
            "Speaker default: read each agent reply aloud (TTS) in the chat/"
            "avatar windows. On by default; the window's speaker toggle mirrors "
            "this and can flip it per-window."
        ),
    )
    wake_word: bool = Field(
        True,
        json_schema_extra=_setting("voice"),
        description=(
            "Require a wake phrase ('hey <name>') to address the agent. "
            "On (default) = the wake phrase is the addressed-to-me gate "
            "for the always-on mic; without it every VAD-segmented "
            "utterance (incl. TV / ambient chatter) would be sent to the "
            "agent.  This replaced the in-brain LLM <reply>/<ignore> gate "
            "(removed 2026-06-16 — it shared the model with tool-calling "
            "and suppressed it).  Disable for push-to-talk / quiet rooms."
        ),
    )
    follow_up: bool = Field(
        True,
        json_schema_extra=_setting("voice"),
        description=(
            "After a reply, open a short window where the user can speak "
            "again without re-saying the wake word."
        ),
    )
    barge_in: bool = Field(
        False,
        json_schema_extra=_setting("voice"),
        description=(
            "Allow interrupting the agent mid-sentence by speaking. Uses "
            "echo cancellation (speexdsp) so the open mic doesn't hear the "
            "agent itself; falls back to mic-pause when speexdsp is absent.  "
            "Off (default) = mic-paused-during-TTS — matches the proven "
            "VoiceLLM reference's self-speech rejection strategy."
        ),
    )
    follow_up_seconds: float = Field(
        10.0, ge=2.0, le=120.0,
        json_schema_extra=_setting("voice"),
        description=(
            "Length of the no-wake-word follow-up window.  Reduced from "
            "15s to 10s in 0.4.x to match the proven reference (shorter "
            "window = less time for stale noise between turns)."
        ),
    )
    speech_engine: Literal["kokoro", "apple"] = Field(
        "kokoro",
        json_schema_extra=_setting("tts"),
        description=(
            "Which synthesizer speaks agent replies in the native app. "
            "'kokoro' (default) = the agent's REAL voice: the Python-side "
            "Kokoro TTS node, using the active character's configured "
            "voice_id — the Swift shell routes its speaker button through "
            "the bridge's 'speak' command.  'apple' = the shell's local "
            "AVSpeechSynthesizer (also the automatic fallback whenever the "
            "bridge is down)."
        ),
    )
    audio_backend: Literal["sounddevice", "avaudio"] = Field(
        "sounddevice",
        json_schema_extra=_setting("tts", advanced=True),
        description=(
            "Persistent TTS output backend. "
            "'sounddevice' = PortAudio via sounddevice (default; routes "
            "to the live macOS system default device, falls back to "
            "PortAudio's default on other OSes).  "
            "'avaudio' = PyObjC AVAudioEngine (macOS only; Apple-native, "
            "bypasses PortAudio and the Pa_Terminate-at-exit segfault "
            "class).  Override per-run with JAEGER_AUDIO_BACKEND env var."
        ),
    )
    self_speech_filter: bool = Field(
        True,
        json_schema_extra=_setting("voice", advanced=True),
        description=(
            "Self-speech rejection via similarity filter.  Compares "
            "each new transcribed phrase to the agent's most recent "
            "spoken reply using ``difflib.SequenceMatcher.ratio()``; "
            "drops the phrase if similarity exceeds "
            "``self_speech_threshold``.  Defence-in-depth on TOP of "
            "mic-pause-during-TTS — catches the case where the mic "
            "still picks up the agent's own voice through the air "
            "(speaker bleed when mic-pause flickers).  Pattern "
            "absorbed from VoiceLLM's M3 orchestrator.  Default ON "
            "so always-on voice has the same defence-in-depth as the "
            "reference implementation."
        ),
    )
    self_speech_threshold: float = Field(
        0.75, ge=0.5, le=1.0,
        json_schema_extra=_setting("voice", advanced=True),
        description=(
            "Similarity ratio (0–1) above which a transcribed phrase "
            "is treated as the agent's own voice and dropped.  Only "
            "consulted when ``self_speech_filter=True``.  0.75 is "
            "the VoiceLLM reference value — aggressive enough to catch "
            "speaker bleed without relying on exact transcript matches."
        ),
    )


class ExternalModelConfig(BaseModel):
    """Opt-in external-model pipeline. Jaeger is local-first — this is
    OFF by default. When ``enabled``, the agent's brain runs on an
    external provider instead of the in-process llama-cpp model.

    Providers:
      • ``lmstudio``     — a local LM Studio server (OpenAI-compatible HTTP)
      • ``ollama``       — a local Ollama server (OpenAI-compatible HTTP)
      • ``ollama-cloud`` — Ollama Cloud (https://ollama.com/v1), an
                           OpenAI-compatible cloud endpoint; needs a key
      • ``openai``       — any OpenAI-compatible cloud / self-hosted endpoint
      • ``anthropic``    — Claude via the Anthropic API
      • ``gemini``       — Google Gemini via its OpenAI-compatible endpoint

    ``lmstudio`` and ``ollama`` are both still on-device — a separate
    local server, used to A/B against the in-process model when
    troubleshooting whether the local llama-cpp model is at fault.
    ``ollama-cloud``, ``openai``, ``anthropic`` and ``gemini`` are true
    cloud brains (the agent phones out) — off by default, like the rest
    of this block.

    The API key is NEVER stored in this file. It is read from the
    instance's credentials/ store by the name in ``api_key_credential``
    (the sanctioned secret path), falling back to the ``api_key_env``
    environment variable. A local LM Studio server needs no real key.
    """

    model_config = ConfigDict(extra="forbid")
    enabled: bool = False
    provider: Literal[
        "lmstudio", "ollama", "ollama-cloud", "openai", "anthropic", "gemini",
    ] = "lmstudio"
    base_url: str = Field(
        "http://localhost:1234/v1",
        description=("OpenAI-compatible endpoint (lmstudio / ollama / openai). "
                     "LM Studio: :1234/v1 · Ollama: :11434/v1. Ignored for anthropic."),
    )
    model: str = Field(
        "local-model",
        description="Model id the provider expects (a 'claude-…' id, or an LM Studio model name).",
    )
    api_key_credential: str = Field(
        "external_model_api_key",
        description="Credential name holding the API key (looked up in credentials/).",
    )
    api_key_env: str = Field(
        "",
        description="Env var to read the key from when the credential is absent.",
    )
    max_tokens: int = Field(1024, ge=16, le=32_768)
    timeout_s: float = Field(60.0, gt=0, le=600)


class WarmupConfig(BaseModel):
    """Boot-time warmup — pre-load the heavy plugins so a Jaeger is
    fully operational the moment boot finishes, not on first use.

    A deployed robot runs TTS and STT constantly, so those default ON —
    the first ``text_to_speech`` / ``listen`` should be instant, not a
    cold model load mid-conversation. Vision pulls a multi-GB model, so
    it defaults OFF — flip it on per-instance when the robot needs it.
    Set a flag false to trim boot time on a dev box that won't use it.
    """

    model_config = ConfigDict(extra="forbid")
    tts: bool = True       # warm Kokoro TTS at boot
    stt: bool = True       # warm Whisper STT at boot
    vision: bool = False   # warm the Moondream2 VLM — heavy, opt-in


class PluginsConfig(BaseModel):
    """Messaging / integration plugins (telegram, discord, …).

    ``autostart`` names the plugins to bring live in-process at boot. Only
    those whose credential is already in the instance store actually start
    (a missing credential is logged and skipped). Empty by default — auto-start
    is opt-in: otherwise a plugin goes live when the agent calls
    ``activate_plugin``, the operator clicks Activate in Studio, or a
    ``/plugins activate <name>`` slash command."""
    model_config = ConfigDict(extra="forbid")
    autostart: list[str] = Field(default_factory=list)


class PermissionsConfig(BaseModel):
    """How the agent handles tier-gated actions — running code,
    controlling the computer, installing packages.

      • ``confirm`` — the agent asks before each tier-gated action.
      • ``allow``   — auto-approve; nothing prompts (a trusted,
                      unattended robot).

    Chosen during first-boot setup and persisted here, so the posture
    survives every restart. Change it any time by editing this field.
    Tier-0 reads are always free; this governs tiers 1-4.
    """

    model_config = ConfigDict(extra="forbid")
    mode: Literal["confirm", "allow"] = Field(
        "confirm", json_schema_extra=_setting("permissions"),
        description="confirm — ask before each tier-gated action; "
                    "allow — auto-approve everything (trusted robot).")


class SecurityConfig(BaseModel):
    """Security posture toggles.

    ``allow_lazy_installs`` — when an optional feature backend (Kokoro
    TTS, a vision model, the ddgs search client) is missing, may the
    framework pip-install it into the instance venv on first use?
    OFF by default: a missing backend returns a clean "feature
    unavailable, run X" message instead of installing silently.
    """

    model_config = ConfigDict(extra="forbid")
    allow_lazy_installs: bool = Field(
        False, json_schema_extra=_setting("permissions"),
        description="Allow the framework to pip-install a missing optional "
                    "backend (Kokoro TTS, a vision model, the search client) "
                    "into the instance venv on first use.")


class DistributionConfig(BaseModel):
    """Provenance for ONE instance — install source + framework
    version. Written by the wizard at first run; rewritten by
    ``jaeger update`` (``last_updated_with_framework``) and by
    ``jaeger restore`` (``install_method='imported'`` +
    ``restored_from``).

    Purely informational. Used by ``jaeger instance inspect``,
    bug-report dumps, and (in 0.3.0+) by the migration runner so
    it can refuse downgrades against an instance created by a newer
    framework.
    """

    model_config = ConfigDict(extra="forbid")
    created_with_framework: str = Field(
        ..., min_length=1, max_length=64,
        description="Framework version that created this instance.",
    )
    last_updated_with_framework: str = Field(
        ..., min_length=1, max_length=64,
        description="Most recent framework version that booted this instance.",
    )
    install_method: Literal["pip", "pipx", "dev-checkout",
                            "imported", "unknown"] = "unknown"
    install_source: str | None = Field(
        None, max_length=512,
        description="PyPI / git URL / restore archive path / etc.",
    )
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )
    restored_from: str | None = Field(
        None, max_length=512,
        description="Set by ``jaeger restore`` to the archive path.",
    )


class WorkspaceConfig(BaseModel):
    """Where the agent's general scratch + output files live
    (INST-11). Defaults to ``<instance>/workspace/`` — keeps
    everything self-contained for backup / restore / move.

    Setting ``location`` to an absolute path moves the workspace
    elsewhere — useful when the user wants easy Finder /
    Spotlight access to generated reports / outputs without
    digging into ``~/.jaeger/``. Examples:

      workspace:
        location: ~/Documents/Jaeger Outputs

      workspace:
        location: /Volumes/External/jaeger-work

    When ``location`` is unset the path is computed from the
    instance root, so ``jaeger backup`` includes the workspace
    automatically. An external ``location`` is NOT included in
    backup (it lives outside the instance dir); the user is
    expected to back it up alongside their other documents.
    """

    model_config = ConfigDict(extra="forbid")
    location: str | None = Field(
        None, max_length=512,
        description=(
            "Override the default ``<instance>/workspace/`` location. "
            "Absolute path or ``~``-prefixed; null = default."
        ),
    )


# 0.2.6: UserConfig removed. The 0.2.1 User layer (separate ``user.dir``
# for persona / skills / prompts) collapsed into the per-instance dir
# at ``<install_root>/.jaeger_os/instances/<name>/``. Each agent is
# self-contained — its persona, skills, prompts, files, memory, logs,
# and credentials all live under one folder. See dev docs/architecture
# /system_runtime_user.md → "0.2.6: two layers" for the rationale.


class InteractionConfig(BaseModel):
    """How the user prefers to talk to this Jaeger by default.

    Chosen during first-boot setup and persisted here so launchers
    (the menu-bar tray's "Open" action, future ``jaeger`` no-arg
    behaviour) can pick the right surface without re-asking every
    time. Three modes today:

      • ``tui``   — open ``jaeger tui`` (0.1.0 in-process Rich REPL).
                    Default when nothing is set.
      • ``gui``   — open the floating PyQt6 chat window
                    (``jaeger gui`` — landing in Group 3).
      • ``voice`` — always-on mic + spoken responses
                    (experimental in 0.2.0; needs ``speexdsp`` for
                    AEC or it picks up background podcast audio).

    Future modes (``rich-tui``, ``attach``, …) can extend the
    Literal as they ship. ``extra="forbid"`` keeps a typo from
    silently writing a config that nobody reads.
    """

    model_config = ConfigDict(extra="forbid")
    default_mode: Literal["tui", "gui", "voice"] = Field(
        "tui", json_schema_extra=_setting("interaction"),
        description="Which surface a bare launch opens: tui (terminal REPL), "
                    "gui (windowed chat), or voice (always-on mic).")
    ui: Literal["pyside6", "swift"] = Field(
        "swift",
        json_schema_extra=_setting("interaction"),
        description=(
            "Windowed-app UI toolkit. 'swift' = the native SwiftUI app "
            "(interfaces/swift/); 'pyside6' = the Qt app. launch.py builds+runs "
            "the Swift app when set to 'swift', falling back to PySide6 if the "
            "Swift build/binary is unavailable."
        ),
    )


class AvatarConfig(BaseModel):
    """0.5: AnimationNode + FrameBridge configuration.

    Controls whether the avatar pipeline auto-starts at boot.

    **Default OFF (2026-06-14):** the avatar / animation node (the
    Lilith face) is a beta, dev-mode feature — its ``set_avatar_state``
    /timeline tools are ``beta``-gated (visible only under
    ``JAEGER_DEV_MODE=1``) and the MathScript renderer is still a
    prototype. So the daily-driver agent does NOT warm the AnimationNode
    by default. Set ``avatar.enabled = true`` in the instance config to
    spin up the AnimationNode + WebSocket bridge when developing it;
    promote to default-on once the renderer is stable.

    ``./launch --no-avatar`` also forces it off regardless of config.
    """
    model_config = ConfigDict(extra="forbid")
    enabled: bool = False
    bridge_host: str = "127.0.0.1"
    bridge_port: int = Field(8765, ge=1024, le=65535)
    # Default emotion the wizard suggests; AnimationNode will publish
    # this on boot when set_avatar_state hasn't been called yet.
    default_emotion: str = "neutral"


class HardwareConfig(BaseModel):
    """Hardware package selection (dev/docs/JROS_HARDWARE_FRAMEWORK_PLAN.md).

    ``package`` names a directory under ``jaeger_os/hardware/packages/``
    (e.g. ``"jp01"``); empty string = no robot attached (the default —
    JROS boots exactly as before). When set, boot loads the package's
    topology, opens its links (simulated controllers get mock wires),
    runs its nodes on the bus, and registers its capability tools —
    which stay ``beta``-gated (visible only under ``JAEGER_DEV_MODE=1``)
    until each capability is hardware-walked.
    """
    model_config = ConfigDict(extra="forbid")
    enabled: bool = True
    package: str = ""


class PersonaConfig(BaseModel):
    """Station 3 of the standard runner (dev/docs/agentic_runners.md):
    workers execute vanilla (a character in the execution context costs a
    4B ~7 bench points, measured); the character's voice is applied to the
    FINAL answer by one bounded clean-context call at the user-facing
    boundary. Fail-open — any filter failure returns the plain answer."""
    model_config = ConfigDict(extra="forbid")

    output_filter: bool = Field(
        True,
        description="Restyle final answers in the active character's voice "
                    "(one extra bounded model call per user-facing turn). "
                    "The execution loop always runs persona-free either way.",
    )
    max_chars: int = Field(
        1600, ge=0, le=20000,
        description="Answers longer than this pass through unstyled — "
                    "rewriting long reports risks mangling content and "
                    "doubles latency where it hurts most. 0 disables "
                    "styling entirely.",
    )


# 0.8 M1: kokoro_tts is the first "engine-module" — its config model
# (``KokoroTTSConfig``) lives beside its node/engine code in
# ``jaeger_os/nodes/kokoro_tts/config.py``, not here. Importing it here
# to nest it into ``Config`` (below) pulls in ``jaeger_os.nodes`` (this
# import forces that package's ``__init__.py`` to run, which imports
# ``jaeger_os.nodes.kokoro_tts``). The FIRST cut of this had
# ``config.py`` import ``_setting`` straight from this file — a
# textbook two-file cycle (schemas -> module -> schemas) that broke
# with an ``ImportError`` on whichever side happened to import first.
# Fixed by moving ``_setting`` to ``setting_meta.py``, a zero-dependency
# leaf both sides import from — ``jaeger_os/nodes/kokoro_tts/config.py``
# has no import-time dependency on this file, so this import direction
# is now a plain one-way edge, not a cycle. Any FUTURE engine-module
# nested here the same way should follow the same shape: its config.py
# imports catalog metadata from ``setting_meta.py``, never from
# ``schemas.py`` directly.
try:
    from jaeger_os.nodes.kokoro_tts.config import KokoroTTSConfig
except ImportError:
    # 0.8 M2a: the kokoro_tts directory (config.py included) can be
    # deleted entirely. This stand-in is structurally identical to the
    # real leaf (same fields/defaults) so an existing config.yaml's
    # ``kokoro_tts:`` block — or the default_factory below — still
    # parses cleanly under ``extra="forbid"``; the values are inert
    # since nothing can synthesize speech without the module present.
    class KokoroTTSConfig(BaseModel):  # type: ignore[no-redef]
        model_config = ConfigDict(extra="forbid")
        voice: str = "af_heart"
        lang: str = "a"
        sample_rate: int = 24000


# 0.8 M2b Task B: whisper_stt is the second engine-module nested this
# way (see the kokoro_tts import block above for the full import-cycle
# rationale — same shape, same ``setting_meta`` leaf, same guarded
# ImportError fallback so a deleted ``nodes/whisper_stt/`` directory
# degrades instead of breaking config load).
try:
    from jaeger_os.nodes.whisper_stt.config import WhisperSTTConfig
except ImportError:
    # Structurally identical to the real leaf (same fields/defaults) so
    # an existing config.yaml's ``whisper_stt:`` block — or the
    # default_factory below — still parses cleanly under
    # ``extra="forbid"``; the values are inert since nothing can listen
    # without the module present.
    class WhisperSTTConfig(BaseModel):  # type: ignore[no-redef]
        model_config = ConfigDict(extra="forbid")
        stt_mode: str = "two_pass"
        fast_model_name: str = "base.en"
        accurate_model_name: str = "medium.en"


class Config(BaseModel):
    model_config = ConfigDict(extra="forbid")

    instance_name: str = Field(..., min_length=1, max_length=64)
    model: ModelConfig
    runtime: RuntimeConfig = Field(default_factory=RuntimeConfig)
    display: DisplayConfig = Field(default_factory=DisplayConfig)
    skills: SkillsConfig = Field(default_factory=SkillsConfig)
    retention: RetentionConfig = Field(default_factory=RetentionConfig)
    deep_think: DeepThinkConfig = Field(default_factory=DeepThinkConfig)
    voice: VoiceConfig = Field(default_factory=VoiceConfig)
    avatar: AvatarConfig = Field(default_factory=lambda: AvatarConfig())
    external_model: ExternalModelConfig = Field(default_factory=ExternalModelConfig)
    warmup: WarmupConfig = Field(default_factory=WarmupConfig)
    plugins: PluginsConfig = Field(default_factory=PluginsConfig)
    permissions: PermissionsConfig = Field(default_factory=PermissionsConfig)
    security: SecurityConfig = Field(default_factory=SecurityConfig)
    interaction: InteractionConfig = Field(default_factory=InteractionConfig)
    workspace: WorkspaceConfig = Field(default_factory=WorkspaceConfig)
    hardware: HardwareConfig = Field(default_factory=HardwareConfig)
    persona: PersonaConfig = Field(default_factory=PersonaConfig)
    kokoro_tts: KokoroTTSConfig = Field(default_factory=KokoroTTSConfig)
    whisper_stt: WhisperSTTConfig = Field(default_factory=WhisperSTTConfig)
    # 0.2.6: ``user: UserConfig`` field removed. Per-instance content
    # (persona, custom skills, prompt overlays, files) lives inside
    # the runtime instance dir; nothing meaningful was shared across
    # the User-layer boundary. See dev docs for the rationale.

    @field_validator("instance_name")
    @classmethod
    def _safe_instance_name(cls, v: str) -> str:
        if any(c in v for c in "/\\:*?\"<>|. "):
            raise ValueError("instance_name must be path-safe (no /, \\, spaces, dots, etc.)")
        return v


# ---------------------------------------------------------------------------
# manifest.json
# ---------------------------------------------------------------------------
class Manifest(BaseModel):
    """Per-instance metadata. Pins the core version that owns this instance
    so a future core upgrade can decide whether to migrate or refuse."""
    model_config = ConfigDict(extra="forbid")

    instance_name: str
    schema_version: str = SCHEMA_VERSION
    # The character this instance is BOUND to — its canonical identity, set at
    # creation and changed only by an explicit rebind (Studio asks to confirm).
    # active_character_id() falls back to this, so the unit defaults to its own
    # persona, not the global default. Empty = unbound (free-swap dev box).
    bound_character: str = ""
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))
    last_started_at: str | None = None

    def with_started_now(self) -> "Manifest":
        return self.model_copy(update={"last_started_at": datetime.now(timezone.utc).isoformat(timespec="seconds")})


# ---------------------------------------------------------------------------
# Generic helpers — write+read with validation
# ---------------------------------------------------------------------------
def _atomic_write(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(payload, encoding="utf-8")
    import os
    os.replace(tmp, path)


def dump_yaml(path: Path, model: BaseModel) -> None:
    import yaml
    data = model.model_dump(mode="json")
    _atomic_write(path, yaml.safe_dump(data, sort_keys=False, allow_unicode=True))


def load_yaml(path: Path, model_cls: type[BaseModel]) -> Any:
    import yaml
    with path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    return model_cls.model_validate(raw)


def dump_json(path: Path, model: BaseModel) -> None:
    _atomic_write(path, model.model_dump_json(indent=2))


def load_json(path: Path, model_cls: type[BaseModel]) -> Any:
    import json
    with path.open("r", encoding="utf-8") as fh:
        return model_cls.model_validate(json.load(fh))
