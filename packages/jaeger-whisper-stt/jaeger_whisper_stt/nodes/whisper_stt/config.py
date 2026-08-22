"""jaeger_whisper_stt.nodes.whisper_stt.config — the module's own settings-catalog
schema slice.

0.8 M2b Task B: "the module IS the engine" (kokoro_tts precedent, M1) —
this config schema lives beside its node/engine code, not in
``core/instance/schemas.py``. It's nested into the central ``Config``
model as ``Config.whisper_stt`` (one line in ``schemas.py``); the
settings-catalog walk (``core/settings/catalog.py``) then renders the
``whisper_stt`` group automatically — zero catalog-side edits, matching
``module.yaml``'s ``config: whisper_stt`` pointer.

Only fields that actually reach the engine are exposed here (no
spec-ahead-of-code). ``jaeger_whisper_stt.nodes.whisper_stt.engine.registry``'s
``_make_two_pass``/``_make_continuous`` factories forward exactly three
``AudioSessionConfig`` fields into ``WhisperSTTTwoPass``/
``WhisperSTTContinuous``: ``stt_mode`` (the registry key itself),
``fast_model_name``, ``accurate_model_name`` (plus wake/session fields
that are slot-generic, not engine-owned — see ``core/audio/session.py``).

The VAD/timing knobs considered for this task (``vad_aggressiveness``,
``silence_hangover_ms``, ``min_speech_ms``, ``max_speech_ms``,
``pre_roll_ms``) were traced through ``AudioSession._build_adapter`` ->
``registry.get(...).make(...)`` and do NOT reach
``WhisperSTTTwoPass.__init__`` today — the registry factories don't pass
them. Adding them here would be a purely decorative setting with no
wired effect, so they were left OUT of this model and remain the
engine's own hardcoded defaults in ``engine/two_pass/pipeline.py``.
Wiring them through is separate plumbing work, not this task.

Import-cycle note: same shape as ``kokoro_tts/config.py`` — ``_setting``
comes from the zero-dependency ``setting_meta`` leaf, never from
``schemas.py``, so this module has no import-time dependency on
``schemas.py``.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from jaeger_os.core.instance.setting_meta import _setting


class WhisperSTTConfig(BaseModel):
    """Settings-catalog-visible defaults for the ``whisper_stt`` engine
    module. All fields are exposed under the ``whisper_stt`` group the
    moment this model is nested into ``Config`` — no catalog code
    changes needed (see module docstring)."""

    model_config = ConfigDict(extra="forbid")

    stt_mode: str = Field(
        "two_pass",
        json_schema_extra=_setting("whisper_stt"),
        description=(
            "STT engine mode — the registry name flipped via "
            "jaeger_whisper_stt.nodes.whisper_stt.engine.registry.get() ('two_pass' "
            "= fast model gates, accurate model commits; 'continuous' = "
            "single rolling model; 'local_agreement' is an unavailable "
            "stub)."
        ),
    )
    fast_model_name: str = Field(
        "base.en",
        json_schema_extra=_setting("whisper_stt"),
        description=(
            "Whisper model used for the fast wake/gate pass in two_pass "
            "mode (or the only pass in continuous mode)."
        ),
    )
    accurate_model_name: str = Field(
        "medium.en",
        json_schema_extra=_setting("whisper_stt"),
        description=(
            "Whisper model used for the accurate commit pass in two_pass "
            "mode. Unused in continuous mode."
        ),
    )


__all__ = ["WhisperSTTConfig"]
