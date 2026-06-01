"""Lazy dependency loading — optional feature backends.

JROS ships lean: heavy / optional backends (Kokoro TTS, a vision
model, an image generator, the ddgs search client) are not hard
dependencies of the framework. This module is the single registry of
what each optional feature needs, plus :func:`ensure` — call it before
touching a backend.

  • dependency importable        → ``ensure`` is a no-op.
  • dependency missing           → ``ensure`` raises
                                   :class:`FeatureUnavailable`, which
                                   carries a precise remediation string
                                   — so the tool returns a clean
                                   "feature unavailable, run X" result
                                   instead of leaking a raw ImportError.

Auto-install: when ``config.security.allow_lazy_installs`` is on, a
missing dependency is ``pip install``-ed into the running interpreter
on first use. It is **off by default** — installing packages mid-turn
is a deliberate posture, never silent.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from dataclasses import dataclass


@dataclass(frozen=True)
class FeatureSpec:
    """What an optional feature needs to work."""
    feature: str                 # stable id, e.g. "search.ddgs"
    probe: str                   # import name to test, e.g. "ddgs"
    pip: tuple[str, ...]         # pip install argument(s)
    summary: str                 # human description


# The curated allowlist — the only packages lazy-install will ever
# touch. Keyed by feature id (``area.backend``).
LAZY_DEPS: dict[str, FeatureSpec] = {
    "search.ddgs": FeatureSpec(
        "search.ddgs", "ddgs", ("ddgs",),
        "DuckDuckGo web search client"),
    "tts.kokoro": FeatureSpec(
        "tts.kokoro", "kokoro", ("kokoro", "soundfile"),
        "Kokoro neural text-to-speech"),
    "stt.whisper": FeatureSpec(
        "stt.whisper", "faster_whisper", ("faster-whisper",),
        "faster-whisper speech-to-text"),
    "vision.moondream": FeatureSpec(
        "vision.moondream", "moondream", ("moondream",),
        "Moondream vision model"),
    "image.diffusers": FeatureSpec(
        "image.diffusers", "diffusers", ("diffusers", "torch"),
        "diffusers image generation (SDXL-Turbo)"),
    "macos.background": FeatureSpec(
        "macos.background", "ApplicationServices",
        ("pyobjc-framework-ApplicationServices", "pyobjc-framework-Quartz",
         "pyobjc-framework-Cocoa"),
        "macOS background automation (PyObjC Accessibility bridge)"),
}


class FeatureUnavailable(RuntimeError):
    """An optional feature's backend isn't installed.

    Carries the :class:`FeatureSpec` so callers can surface a clean,
    actionable message rather than a raw ImportError."""

    def __init__(self, spec: FeatureSpec) -> None:
        self.spec = spec
        super().__init__(self.remediation)

    @property
    def remediation(self) -> str:
        return (
            f"{self.spec.summary} is not installed. "
            f"Install it with:  pip install {' '.join(self.spec.pip)}  "
            f"(or set security.allow_lazy_installs: true in config.yaml "
            f"to let JROS install optional backends automatically)."
        )


def _importable(module: str) -> bool:
    """True if ``module`` can be imported — a fast check, no real import."""
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError, ModuleNotFoundError):
        return False


def available(feature: str) -> bool:
    """Whether ``feature``'s backend is importable right now."""
    spec = LAZY_DEPS.get(feature)
    if spec is None:
        return True   # unknown feature — nothing to gate
    return _importable(spec.probe)


def _allow_lazy_installs() -> bool:
    """Read ``config.security.allow_lazy_installs`` from the live
    pipeline. Defaults to False on any error (fail-safe)."""
    try:
        from jaeger_os.main import _pipeline
        cfg = _pipeline.get("config")
        return bool(getattr(getattr(cfg, "security", None),
                            "allow_lazy_installs", False))
    except Exception:  # noqa: BLE001
        return False


def _pip_install(spec: FeatureSpec, timeout_s: float = 600.0) -> bool:
    """pip-install ``spec`` into the running interpreter. True on success."""
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pip", "install", *spec.pip],
            capture_output=True, text=True, timeout=timeout_s,
        )
        return proc.returncode == 0
    except (subprocess.SubprocessError, OSError):
        return False


def ensure(feature: str) -> None:
    """Make sure ``feature``'s backend is usable. No-op when it already
    is. Raises :class:`FeatureUnavailable` (with remediation) when the
    backend is missing and cannot be installed.

    Auto-install happens only when ``security.allow_lazy_installs`` is
    on; otherwise a missing backend always raises."""
    spec = LAZY_DEPS.get(feature)
    if spec is None or _importable(spec.probe):
        return
    if _allow_lazy_installs() and _pip_install(spec):
        importlib.invalidate_caches()
        if _importable(spec.probe):
            return
    raise FeatureUnavailable(spec)
