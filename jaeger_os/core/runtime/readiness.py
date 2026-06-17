"""System readiness — warm + health-probe every heavy backend, loudly.

One registry of the systems a Jaeger instance depends on (LLM, TTS, STT,
vision, memory, avatar, hardware). Each declares whether it's *applicable*
for the active instance, how to *warm* it (download + load into memory),
and how to *probe* its live *health*. Three callers share this:

  * boot (``main.warm_plugins``) — warm every applicable system, surface
    failures loudly, and stash the report so the agent knows status at
    turn one. Warming a node is decoupled from voice *mode* (active
    listening): we warm TTS/STT so the tools are instant, without opening
    the mic.
  * the setup wizard — download + warm + verify before completing setup;
    "all systems go" or a clear list of what failed.
  * the ``diagnostics`` tool + ``./run.sh doctor`` — live per-system
    status the agent can read instead of guessing.

A system is **online** when it warmed/probed clean, **offline** when it
errored (with the reason), or **skipped** when it isn't applicable to this
instance (e.g. hardware with no package configured).
"""

from __future__ import annotations

import dataclasses
import time
from typing import Any, Callable


# ── status model ──────────────────────────────────────────────────

ONLINE = "online"
OFFLINE = "offline"
SKIPPED = "skipped"


@dataclasses.dataclass
class SystemStatus:
    """One system's outcome from a warm or a health probe."""
    name: str
    status: str                 # ONLINE | OFFLINE | SKIPPED
    elapsed_s: float = 0.0
    detail: str = ""            # error text (offline) or reason (skipped)

    @property
    def ok(self) -> bool:
        return self.status == ONLINE

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "elapsed_s": round(self.elapsed_s, 2),
            "detail": self.detail,
        }


@dataclasses.dataclass
class System:
    """A warm-able / probe-able backend."""
    name: str
    # Given the instance config, is this system used here at all?
    applicable: Callable[[Any], bool]
    # Download + load into memory. Raise on failure.
    warm: Callable[[], Any]
    # Live probe → (ok, detail). Best-effort; defaults to "warmed == online".
    health: Callable[[], tuple[bool, str]] | None = None
    skip_reason: str = "not configured for this instance"


# ── the registry ──────────────────────────────────────────────────

def _always(_config: Any) -> bool:
    return True


def _avatar_enabled(config: Any) -> bool:
    import sys
    if "--no-avatar" in sys.argv[1:]:
        return False
    cfg = getattr(config, "avatar", None)
    return bool(cfg is not None and getattr(cfg, "enabled", True))


def _hardware_enabled(config: Any) -> bool:
    cfg = getattr(config, "hardware", None)
    return bool(cfg is not None and getattr(cfg, "enabled", True)
                and (getattr(cfg, "package", "") or "").strip())


def _vision_enabled(config: Any) -> bool:
    # Heavy VLM. Warmed when the instance opts in (warmup.vision) — the one
    # system that stays opt-in by weight; everything else warms by default.
    w = getattr(config, "warmup", None)
    return bool(w is not None and getattr(w, "vision", False))


def _warm_tts() -> Any:
    from jaeger_os.agent.tools.speak import warm_kokoro
    return warm_kokoro()


def _warm_stt() -> Any:
    from jaeger_os.agent.tools.listen import warm_listen
    return warm_listen()


def _warm_vision() -> Any:
    from jaeger_os.agent.tools.vision import warm_vision
    return warm_vision()


def _warm_avatar() -> Any:
    from jaeger_os.agent.tools.avatar import warm_avatar
    return warm_avatar()


def _warm_hardware_for(config: Any) -> Callable[[], Any]:
    pkg = (getattr(getattr(config, "hardware", None), "package", "") or "").strip()

    def _boot() -> Any:
        from jaeger_os.hardware.boot import boot_hardware
        from jaeger_os.nodes import runtime as nodes_runtime
        return boot_hardware(pkg, bus=nodes_runtime.get_bus())
    return _boot


def _health_tts() -> tuple[bool, str]:
    from jaeger_os.nodes import runtime
    synth = runtime.get_synth()
    if synth is None:
        return False, "TTS node has no synth (Kokoro not loaded)"
    warmed = bool(getattr(synth, "warmed", True))
    return (warmed, "Kokoro warm" if warmed else "Kokoro present but not warm")


def _registry(config: Any) -> list[System]:
    systems = [
        # STT BEFORE TTS — Kokoro's persistent player opens an AVAudioEngine
        # output stream during warm, which on macOS races with a just-loaded
        # Gemma (``error 2003329396``) if fired first; warming Whisper first
        # lets Metal settle. Integration-race fix, mirrored from the smoke test.
        System("STT (Whisper)", _always, _warm_stt),
        System("TTS (Kokoro)", _always, _warm_tts, _health_tts),
        System("vision (Moondream2)", _vision_enabled, _warm_vision,
               skip_reason="warmup.vision is off (heavy VLM — opt-in)"),
        System("avatar (animation node)", _avatar_enabled, _warm_avatar,
               skip_reason="avatar disabled in config"),
        System("hardware package", _hardware_enabled,
               _warm_hardware_for(config),
               skip_reason="no hardware package configured"),
    ]
    return systems


# ── warm + probe ──────────────────────────────────────────────────

def warm_all(config: Any) -> list[SystemStatus]:
    """Warm every applicable system. Never raises — each failure becomes an
    OFFLINE status with its error, so the caller can report the whole set."""
    out: list[SystemStatus] = []
    for sys_ in _registry(config):
        if not sys_.applicable(config):
            out.append(SystemStatus(sys_.name, SKIPPED, 0.0, sys_.skip_reason))
            continue
        started = time.perf_counter()
        try:
            sys_.warm()
            out.append(SystemStatus(sys_.name, ONLINE,
                                    time.perf_counter() - started))
        except Exception as exc:  # noqa: BLE001 — collect, don't crash boot
            out.append(SystemStatus(
                sys_.name, OFFLINE, time.perf_counter() - started,
                f"{type(exc).__name__}: {exc}"))
    return out


def probe_all(config: Any) -> list[SystemStatus]:
    """Live health probe (no warming). Systems without a probe report ONLINE
    if applicable (best-effort), SKIPPED otherwise."""
    out: list[SystemStatus] = []
    for sys_ in _registry(config):
        if not sys_.applicable(config):
            out.append(SystemStatus(sys_.name, SKIPPED, 0.0, sys_.skip_reason))
            continue
        if sys_.health is None:
            out.append(SystemStatus(sys_.name, ONLINE, 0.0, "no probe"))
            continue
        started = time.perf_counter()
        try:
            ok, detail = sys_.health()
            out.append(SystemStatus(
                sys_.name, ONLINE if ok else OFFLINE,
                time.perf_counter() - started, detail))
        except Exception as exc:  # noqa: BLE001
            out.append(SystemStatus(
                sys_.name, OFFLINE, time.perf_counter() - started,
                f"probe error: {type(exc).__name__}: {exc}"))
    return out


def summarize(statuses: list[SystemStatus]) -> str:
    """A loud, human-readable readiness block — never hides a failure."""
    online = [s for s in statuses if s.status == ONLINE]
    offline = [s for s in statuses if s.status == OFFLINE]
    skipped = [s for s in statuses if s.status == SKIPPED]
    lines = ["── system readiness ──────────────────────────────"]
    for s in statuses:
        mark = {"online": "✓", "offline": "✗", "skipped": "·"}[s.status]
        suffix = f"  ({s.detail})" if s.detail and s.status != ONLINE else (
            f"  {s.elapsed_s:.1f}s" if s.status == ONLINE else "")
        lines.append(f"  {mark} {s.name}: {s.status}{suffix}")
    if offline:
        names = ", ".join(s.name for s in offline)
        lines.append(f"  ⚠ {len(offline)} SYSTEM(S) OFFLINE: {names}")
    else:
        lines.append(f"  all systems go — {len(online)} online, "
                     f"{len(skipped)} skipped")
    lines.append("──────────────────────────────────────────────────")
    return "\n".join(lines)


def all_go(statuses: list[SystemStatus]) -> bool:
    """True when no applicable system is OFFLINE (skipped is fine)."""
    return not any(s.status == OFFLINE for s in statuses)


__all__ = [
    "SystemStatus", "System", "ONLINE", "OFFLINE", "SKIPPED",
    "warm_all", "probe_all", "summarize", "all_go",
]
