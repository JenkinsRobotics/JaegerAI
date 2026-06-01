"""Text-to-speech tool shims — delegate to the kokoro_tts plugin.

  • speak(text=, path=) — synthesize + play through the default output;
                          pass `path` to narrate a workspace file instead
  • warm_kokoro()       — pre-load the Kokoro pipeline at startup

Under the vocabulary contract, the actual Kokoro pipeline + sounddevice
playback lives in `jaeger_os/plugins/kokoro_tts/` (it bridges to an
external library + hardware → Plugin). The functions in THIS file are the
agent-callable Tool surface — `main.py` registers `speak()` (which takes
either literal `text` or a workspace-file `path`) with the agent, and
that wrapper calls into here. `warm_kokoro()` is startup-only.

The sandbox check for the `path` branch of `speak()` stays in core
because the file resolution must be enforced regardless of which TTS
backend is active (today: kokoro_tts plugin; future: a different TTS
plugin won by override-via-versioning).

Module-level constants are re-exported from the plugin so callers can
import them from either location during the transition.
"""

from __future__ import annotations

from typing import Any

from ._common import SandboxError, _require_layout, _resolve_under

# Re-export plugin constants so existing imports keep working.
from ...plugins.kokoro_tts import (
    KOKORO_LANG,
    KOKORO_SAMPLE_RATE,
    KOKORO_VOICE,
    KokoroTTS,
)


# Single shared instance — Kokoro's pipeline isn't designed for concurrent
# use, and the agent's tool surface serializes through the LLM lock anyway.
_tts: KokoroTTS | None = None
_tts_voice: str | None = None  # voice the cached _tts was built with


def _resolve_voice() -> str:
    """Read the active instance's identity.yaml for a ``voice_id``
    override, falling back to the plugin's KOKORO_VOICE default.

    This lets Jarvis (default instance) use a male voice while Lilith
    uses a female one without each speak() call needing to know which
    instance is active — we just read identity.yaml at TTS init time."""
    try:
        layout = _require_layout()
    except Exception:
        return KOKORO_VOICE
    from jaeger_os.core.instance.schemas import Identity, load_yaml
    try:
        identity = load_yaml(layout.identity_path, Identity)
    except Exception:
        return KOKORO_VOICE
    voice_id = (identity.voice_id or "").strip()
    return voice_id or KOKORO_VOICE


def _get_tts() -> KokoroTTS:
    global _tts, _tts_voice
    desired = _resolve_voice()
    if _tts is None or _tts_voice != desired:
        # Voice changed (e.g. /instance switched from default to lilith
        # mid-session). Rebuild the pipeline so the next speak() uses
        # the right voice. The old _tts is GC'd; Kokoro's weights stay
        # cached at the package level so this isn't a full reload.
        _tts = KokoroTTS(voice=desired, lang=KOKORO_LANG)
        _tts_voice = desired
    return _tts


def warm_kokoro() -> dict[str, Any]:
    """Pre-load Kokoro so the first speak() doesn't pay the ~3–5 s
    weight-load tax. Idempotent."""
    return _get_tts().warm()


def speak(text: str = "", path: str = "") -> dict[str, Any]:
    """Speak aloud through the default audio output via Kokoro TTS.

    Pass ``text`` to speak literal text, or ``path`` to narrate a file
    from <instance>/skills/ ("read X out loud", "narrate X"). When
    ``path`` is given it wins. Supports minimal SSML: <speak>,
    <break time="Xms"/>, <breath/>.

    The ``path`` branch is sandbox-resolved through the same logic as
    file_read — it must stay inside the instance's skills/ zone. The
    sandbox check lives here in core rather than in the plugin so
    swapping out the TTS backend can't relax file-access boundaries."""
    file_path = (path or "").strip()
    if file_path:
        layout = _require_layout()
        try:
            target = _resolve_under(layout.skills_dir, file_path)
        except SandboxError as exc:
            return {"spoken": False, "reason": str(exc), "path": file_path}
        if not target.exists() or not target.is_file():
            return {"spoken": False, "reason": "file not found", "path": file_path}
        result = _get_tts().speak(target.read_text(encoding="utf-8"))
        result["from_file"] = str(target.relative_to(layout.root))
        return result

    if not (text or "").strip():
        return {"spoken": False, "reason": "nothing to speak — pass text or path"}
    return _get_tts().speak(text)
