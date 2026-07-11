"""jaeger_os.nodes.kokoro_tts.config — the module's own settings-catalog
schema slice.

0.8 M1: "the module IS the engine" — its config schema lives beside its
node/engine code, not in ``core/instance/schemas.py``. It's nested into
the central ``Config`` model as ``Config.kokoro_tts`` (one line in
``schemas.py``); the settings-catalog walk (``core/settings/catalog.py``)
then renders the ``kokoro_tts`` group automatically — zero catalog-side
edits, matching ``module.yaml``'s ``config: kokoro_tts`` pointer.

Voice resolution order is unchanged from pre-0.8: the active character's
/ instance's ``Identity.voice_id`` wins when set; ``voice`` below is only
the fallback default (see ``agent/tools/speak.py::_resolve_voice``).

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
    """Settings-catalog-visible defaults for the ``kokoro_tts`` engine
    module. All three fields are exposed under the ``kokoro_tts`` group
    the moment this model is nested into ``Config`` — no catalog code
    changes needed (see module docstring)."""

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
    sample_rate: int = Field(
        24000, ge=8000, le=48000,
        json_schema_extra=_setting("kokoro_tts", advanced=True),
        description=(
            "Kokoro's native output sample rate (Hz). This must match "
            "what the loaded Kokoro model actually produces — it is NOT "
            "a free-form audio-quality knob; changing it without a "
            "matching model change will distort playback."
        ),
    )


__all__ = ["KokoroTTSConfig"]
