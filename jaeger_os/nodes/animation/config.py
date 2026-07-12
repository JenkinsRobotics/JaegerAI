"""jaeger_os.nodes.animation.config — the module's own settings-catalog
schema slice.

0.8 M2c: "the module IS the engine" (kokoro_tts/whisper_stt precedent) —
``AvatarConfig`` moves here from ``core/instance/schemas.py`` VERBATIM
(same field names, defaults, and — deliberately — the SAME lack of
catalog exposure). It's nested into the central ``Config`` model as
``Config.avatar`` (one line in ``schemas.py``, guarded import).

Unlike ``KokoroTTSConfig``/``WhisperSTTConfig``, none of these fields
carry ``_setting()`` metadata: the avatar/animation pipeline is still a
beta, dev-mode feature (see the class docstring below), and
``core/settings/catalog.py``'s own module docstring names "the deferred
hardware/avatar/plugin blocks" as staying OUT of the catalog until their
own Phase-3 providers land. ``dev/tests/jaeger_os/core/
test_settings_catalog.py::test_unexposed_fields_are_absent`` pins
``avatar.enabled`` as hidden — this move must not change that. Import
``_setting`` from ``setting_meta`` (never ``schemas``) is still the
house rule for when/if avatar fields ARE promoted to the catalog later.

Import-cycle note: same shape as ``kokoro_tts/config.py`` — this module
must never import ``schemas.py``. ``_setting`` is simply not imported here
because no field is catalog-exposed yet; when one is, import it from
``setting_meta``.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from jaeger_os.contract.ports import ANIMATION_BRIDGE_DEFAULT_PORT


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
    bridge_port: int = Field(ANIMATION_BRIDGE_DEFAULT_PORT, ge=1024, le=65535)
    # Default emotion the wizard suggests; AnimationNode will publish
    # this on boot when set_avatar_state hasn't been called yet.
    default_emotion: str = "neutral"


__all__ = ["AvatarConfig"]
