"""jaeger_whisper_stt.config — the module's own settings-catalog
schema slice.

0.8 M2b Task B: "the module IS the engine" (kokoro_tts precedent, M1) —
this config schema lives beside its node/engine code, not in
``core/instance/schemas.py``. It's nested into the central ``Config``
model as ``Config.whisper_stt`` (one line in ``schemas.py``); the
settings-catalog walk (``core/settings/catalog.py``) then renders the
``whisper_stt`` group automatically — zero catalog-side edits, matching
``module.yaml``'s ``config: whisper_stt`` pointer.

Every field below reaches an engine constructor through the registry.  The
three setting groups correspond to WebRTC-VAD phrases, energy-segmented
phrases, and rolling streaming captions; irrelevant fields are harmlessly
ignored by the selected mode.

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
            "jaeger_whisper_stt.engine.registry.get(). "
            "'vad_segment' = VAD closes a phrase, one model commits it; "
            "'two_pass' = fast model gates, accurate model commits; "
            "'continuous' = single rolling model, energy-segmented; "
            "'phrase_word' = continuous plus live partials; "
            "'window' = rolling-window captions, no VAD; "
            "'local_agreement' = rolling window with word-cursor "
            "streaming commit. The last three publish is_final=False "
            "transcripts while the user is still speaking — that is a "
            "property of the mode, not a separate setting, so there is "
            "no 'emit partials' knob to get out of sync with it. "
            "`jaeger-whisper-stt list` prints the same table."
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
    language: str = Field(
        "en",
        min_length=2,
        max_length=16,
        json_schema_extra=_setting("whisper_stt"),
        description=(
            "Whisper transcription language code. Use 'en' with .en models; "
            "choose a multilingual model when selecting another language."
        ),
    )
    wake_match_threshold: float = Field(
        0.78, ge=0.0, le=1.0, json_schema_extra=_setting("whisper_stt"),
        description="Minimum fuzzy similarity for a configured wake phrase.",
    )

    # WebRTC-VAD settings: vad_segment and two_pass.
    vad_aggressiveness: int = Field(
        2, ge=0, le=3, json_schema_extra=_setting("whisper_stt"),
        description="WebRTC VAD aggressiveness (0 permissive, 3 strict).",
    )
    pre_roll_ms: int = Field(
        240, ge=0, le=2000, json_schema_extra=_setting("whisper_stt"),
        description="Audio retained before VAD detects speech.",
    )
    post_padding_ms: int = Field(
        250, ge=0, le=2000, json_schema_extra=_setting("whisper_stt"),
        description="Silence appended before Whisper decoding.",
    )
    silence_hangover_ms: int = Field(
        700, ge=100, le=5000, json_schema_extra=_setting("whisper_stt"),
        description="Trailing silence that closes a normal phrase.",
    )
    min_speech_ms: int = Field(
        400, ge=30, le=5000, json_schema_extra=_setting("whisper_stt"),
        description="Minimum voiced audio accepted as a phrase.",
    )
    max_speech_ms: int = Field(
        8000, ge=500, le=120000, json_schema_extra=_setting("whisper_stt"),
        description="Hard phrase cutoff that bounds latency and memory.",
    )
    barge_in_ms: int = Field(
        200, ge=30, le=3000, json_schema_extra=_setting("whisper_stt"),
        description="Sustained speech required before speech-start fires.",
    )
    short_phrase_max_ms: int = Field(
        1500, ge=0, le=10000, json_schema_extra=_setting("whisper_stt"),
        description="Utterances at or below this use the short hangover; 0 disables it.",
    )
    short_phrase_hangover_ms: int = Field(
        350, ge=100, le=5000, json_schema_extra=_setting("whisper_stt"),
        description="Trailing silence that closes a short phrase.",
    )

    # Energy-segmented settings: continuous and phrase_word.
    continuous_phrase_timeout_s: float = Field(
        1.0, gt=0, le=10, json_schema_extra=_setting("whisper_stt"),
        description="Quiet time that commits an energy-segmented phrase.",
    )
    continuous_max_phrase_s: float = Field(
        8.0, gt=0, le=120, json_schema_extra=_setting("whisper_stt"),
        description="Maximum energy-segmented phrase duration.",
    )
    continuous_transcribe_every_s: float = Field(
        0.6, gt=0, le=10, json_schema_extra=_setting("whisper_stt"),
        description="Rolling decode cadence for energy-segmented modes.",
    )
    continuous_min_transcribe_s: float = Field(
        0.4, gt=0, le=10, json_schema_extra=_setting("whisper_stt"),
        description="Minimum buffered speech before an energy-mode decode.",
    )
    continuous_energy_threshold: float = Field(
        0.005, ge=0, le=1, json_schema_extra=_setting("whisper_stt"),
        description="RMS speech threshold for energy-segmented modes.",
    )

    # Rolling streaming settings: window and local_agreement.
    stream_window_s: float = Field(
        7.0, gt=0, le=120, json_schema_extra=_setting("whisper_stt"),
        description="Recent audio retained for each streaming decode.",
    )
    stream_transcribe_every_s: float = Field(
        1.2, gt=0, le=10, json_schema_extra=_setting("whisper_stt"),
        description="Streaming partial decode cadence.",
    )
    stream_min_transcribe_s: float = Field(
        1.0, gt=0, le=10, json_schema_extra=_setting("whisper_stt"),
        description="Minimum audio required before a streaming decode.",
    )
    stream_energy_threshold: float = Field(
        0.008, ge=0, le=1, json_schema_extra=_setting("whisper_stt"),
        description="RMS speech threshold for rolling streaming modes.",
    )
    stream_min_commit_words: int = Field(
        1, ge=1, le=100, json_schema_extra=_setting("whisper_stt"),
        description="Minimum stable words emitted per LocalAgreement commit.",
    )
    stream_min_overlap_words: int = Field(
        2, ge=1, le=100, json_schema_extra=_setting("whisper_stt"),
        description="Word overlap required to align rolling transcripts.",
    )
    stream_max_commit_words: int = Field(
        28, ge=1, le=500, json_schema_extra=_setting("whisper_stt"),
        description="Maximum words emitted by one streaming commit.",
    )
    stream_resync_after_passes: int = Field(
        4, ge=1, le=100, json_schema_extra=_setting("whisper_stt"),
        description="Unaligned passes tolerated before cursor resynchronization.",
    )
    mic_queue_max_frames: int = Field(
        200, ge=1, le=10000, json_schema_extra=_setting("whisper_stt"),
        description="Bounded VAD-frame ingress queue; newest frames win.",
    )
    output_queue_max_phrases: int = Field(
        16, ge=1, le=1000, json_schema_extra=_setting("whisper_stt"),
        description="Bounded committed-output queue; newest phrases win.",
    )


__all__ = ["WhisperSTTConfig"]
