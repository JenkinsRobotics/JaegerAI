"""Operator-facing configuration for the Kokoro TTS module.

Kokoro always emits 24 kHz mono audio. That fact is a module constant, not
an editable quality control; exposing it as configuration previously made
it possible to label 24 kHz samples as another rate and produce slow,
fast, or pitched playback.

Voice resolution order is unchanged from pre-0.8: the active character's
/ instance's ``Identity.voice_id`` wins when set; ``voice`` below is only
the fallback default (see ``core/voice/voice_resolution.py::resolve_voice``).

Import-cycle note: ``schemas.py`` imports THIS module's ``KokoroTTSConfig``
to nest it into ``Config`` (``Config.kokoro_tts``). A naive two-file cycle
(``schemas`` -> this module -> ``schemas``, for ``_setting``) would break
depending on which side of the app happens to import first — proven by
hitting exactly that ``ImportError`` while wiring this up. Fixed by
splitting ``_setting`` out into ``jaeger_os/core/instance/setting_meta.py``,
a zero-dependency leaf both this module and ``schemas.py`` import from —
this module has NO import-time dependency on ``schemas.py`` at all now.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from jaeger_os.core.instance.setting_meta import _setting


class KokoroTTSConfig(BaseModel):
    """Validated defaults shown in the ``kokoro_tts`` settings group."""

    model_config = ConfigDict(extra="forbid")

    voice: str = Field(
        "af_heart",
        json_schema_extra=_setting("kokoro_tts"),
        description=(
            "Default Kokoro voice id (af_* = female, am_* = male). Used "
            "ONLY when the active instance's Identity.voice_id (and the "
            "active character's voice_id) are both unset — a per-instance "
            "voice always wins over this module-level default."
        ),
    )
    lang: str = Field(
        "a",
        json_schema_extra=_setting("kokoro_tts"),
        description="Kokoro KPipeline language code ('a' = American "
                    "English — see the kokoro library for the full set).",
    )
    warm: bool = Field(
        True,
        json_schema_extra=_setting("kokoro_tts", advanced=True),
        description="Load and prime Kokoro in the background at node start.",
    )
    queue_maxsize: int = Field(
        32, ge=1, le=256,
        json_schema_extra=_setting("kokoro_tts", advanced=True),
        description="Maximum queued speech requests before overload rejection.",
    )
    max_text_chars: int = Field(
        4000, ge=1, le=50000,
        json_schema_extra=_setting("kokoro_tts", advanced=True),
        description="Maximum characters accepted in one speech request.",
    )


__all__ = ["KokoroTTSConfig"]
