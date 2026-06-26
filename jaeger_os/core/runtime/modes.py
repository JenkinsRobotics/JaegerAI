"""Agent modes — switch the conversational model + voice as one unit.

  normal      — small realtime model (gemma-4-12B) + voice on   (default)
  high        — larger model (gemma-4-26B), voice off            (heavier reasoning, frees the voice RAM)
  deep-sleep   — high model, voice off, + drains the Deep Think task queue

Switching swaps the resident LLM via ``main.switch_model`` (slow — the same
~60-90s unload→load→prewarm), and toggles a voice flag the audio path honours.
The active mode is published as a :class:`ModeState` so surfaces (tray, chat
header) show it. The user flips modes with the ``set_mode`` tool, a ``/mode``
slash command on any channel, or "switch to high mode" in plain text.

State is process-global (one resident model per instance). Idempotent: setting
the current mode is a no-op (no needless 60-90s swap).
"""

from __future__ import annotations

from typing import Any

# preset → resident model (registry key), whether voice is allowed, and
# whether entering it should drain the Deep Think queue.
MODES: dict[str, dict[str, Any]] = {
    "normal":     {"model": "gemma-4-12b-it-q4_k_m",     "voice": True,  "deep_sleep": False},
    "high":       {"model": "gemma-4-26b-a4b-it-q4_k_m", "voice": False, "deep_sleep": False},
    "deep-sleep": {"model": "gemma-4-26b-a4b-it-q4_k_m", "voice": False, "deep_sleep": True},
}
DEFAULT_MODE = "normal"

# Tracked live: the active mode + the model that's actually resident (so we
# don't re-swap to a model we're already running).
_state: dict[str, Any] = {"mode": DEFAULT_MODE, "model": None}


def current_mode() -> str:
    return _state["mode"]


def list_modes() -> list[str]:
    return list(MODES)


def voice_enabled() -> bool:
    """The audio path checks this — voice is suppressed in high / deep-sleep."""
    return bool(MODES.get(_state["mode"], {}).get("voice", True))


def _resident_model() -> str:
    """The model registry key currently loaded. Tracked across switches;
    seeded from the instance config's boot model on first call."""
    if _state["model"] is None:
        try:
            from jaeger_os.main import _pipeline
            cfg = _pipeline.get("config")
            _state["model"] = getattr(getattr(cfg, "model", None), "model_path", None)
        except Exception:  # noqa: BLE001
            _state["model"] = None
    return _state["model"] or ""


def _publish(mode: str) -> None:
    try:
        from jaeger_os.core.messages import ModeState
        from jaeger_os.main import _pipeline
        bus = _pipeline.get("chassis_bus")
        if bus is not None:
            bus.publish(ModeState(mode=mode))
    except Exception:  # noqa: BLE001 — status is best-effort
        pass


def set_mode(name: str) -> dict:
    """Switch to a preset mode: swap the resident model if it differs, toggle
    voice, publish the new mode. Returns a status dict; never raises.

    The model swap is slow (~60-90s) and RAM-aware (``switch_model`` drops the
    old weights before loading the new). No-op if already in the target mode."""
    target = (name or "").strip().lower()
    if target not in MODES:
        return {"ok": False, "error": f"unknown mode {target!r}; choose from {list(MODES)}"}
    if target == _state["mode"]:
        return {"ok": True, "mode": target, "unchanged": True}

    preset = MODES[target]
    want_model = preset["model"]
    if want_model != _resident_model():
        try:
            from jaeger_os.main import _pipeline, switch_model
            # Serialize the swap with turns: wait for any in-flight generation
            # and block new turns while the weights unload/load (swapping
            # mid-generation would corrupt the KV cache).
            lock = _pipeline.get("llm_lock")
            if lock is not None:
                with lock:
                    switch_model(want_model)
            else:
                switch_model(want_model)
            _state["model"] = want_model
        except Exception as exc:  # noqa: BLE001 — surface, don't crash the turn
            return {"ok": False, "error": f"model swap to {want_model!r} failed: "
                                          f"{type(exc).__name__}: {exc}"}

    _state["mode"] = target
    _publish(target)
    if preset["deep_sleep"]:
        _engage_deep_think()
    return {"ok": True, "mode": target, "model": want_model, "voice": preset["voice"]}


def _engage_deep_think() -> None:
    """Best-effort: nudge the Deep Think runner to drain its queue now that
    we're on the big model. The runner also auto-engages on idle; this is the
    explicit entry. Wiring the immediate kick is a follow-up — for now the
    mode is set + the big model resident, and the idle runner picks it up."""
    # ponytail: deep-sleep currently swaps the model + flags the mode; the
    # immediate queue-drain kick rides the existing idle trigger. Add a direct
    # runner.run_pending() call here when the runner exposes one.
    return
