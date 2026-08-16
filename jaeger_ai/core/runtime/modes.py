"""Agent modes — switch the conversational model + voice as one unit.

  normal      — e4b realtime model + voice on   (default; 12B = voice backup)
  high        — 26B-A4B QAT, voice off           (heavier reasoning, frees the voice RAM)
  deep-sleep   — high model, voice off, + drains the Deep Think task queue

Model picks set from the 0.6 clean-batch benchmark (corpus 1.2, 32 GB host):
e4b is fastest + smallest so it co-loads with voice; the 26B-A4B QAT ties the
plain 26B on capability but is 2.4 GB smaller (more context headroom voice-off).
The dense 12B stays the voice-mode BACKUP — slower but 5/5 on the safety /
no-hallucination tier (vs e4b's 3/5); switch to it when honesty > latency.

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
    "normal":     {"model": "gemma-4-e4b-it-q4_k_m",       "voice": True,  "deep_sleep": False},
    "high":       {"model": "gemma-4-26b-a4b-it-qat-q4_0", "voice": False, "deep_sleep": False},
    "deep-sleep": {"model": "gemma-4-26b-a4b-it-qat-q4_0", "voice": False, "deep_sleep": True},
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


def serving_brain() -> dict[str, Any]:
    """The model that is actually answering turns right now.

    ``normal`` / ``high`` name the LOCAL llama.cpp/MLX presets. When
    ``external_model`` is serving (Ollama Cloud, Anthropic, …) those
    presets are idle — reporting them as "the model" is how the
    status bar said DeepSeek while ``get_mode`` said Gemma.
    """
    try:
        from pathlib import Path

        from jaeger_ai.main import _pipeline

        client = _pipeline.get("client")
        cfg = _pipeline.get("config")
        ext = getattr(cfg, "external_model", None) if cfg is not None else None
        # Prefer the live client — that is what THIS session's turn
        # is talking to. Fall back to the session row if the client
        # has not been built yet (History / pre-boot).
        if client is not None and getattr(client, "kind", "local") == "external":
            ctx = int(getattr(client, "loaded_ctx", 0) or 0)
            if not ctx:
                try:
                    from jaeger_ai.main import _context_budget_for
                    budgeted, _reserve = _context_budget_for(cfg)
                    ctx = int(budgeted or 0)
                except Exception:  # noqa: BLE001
                    ctx = int(getattr(ext, "ctx", 0) or 0) if ext is not None else 0
            return {
                "kind": "external",
                "provider": getattr(client, "provider", None)
                or (getattr(ext, "provider", None) if ext is not None else None),
                "model": getattr(client, "model_name", None)
                or (getattr(ext, "model", None) if ext is not None else None),
                "ctx": ctx or None,
            }
        if client is None:
            # Pre-boot / History: use the model THIS session last used.
            try:
                from jaeger_ai.core.sessions import get_store

                sid = str(_pipeline.get("current_session") or "")
                store = get_store()
                if store is not None and sid:
                    stamped = store.brain(sid)
                    if stamped.get("model"):
                        kind = (
                            "external"
                            if stamped.get("provider")
                            and stamped.get("provider") != "local"
                            else "local"
                        )
                        return {
                            "kind": kind,
                            "provider": stamped.get("provider"),
                            "model": stamped.get("model"),
                            "ctx": None,
                        }
            except Exception:  # noqa: BLE001
                pass
        model_path = getattr(getattr(cfg, "model", None), "model_path", "") if cfg else ""
        name = Path(str(model_path)).name if model_path else ""
        if not name:
            name = str(getattr(client, "model_name", "") or "")
        ctx = int(getattr(client, "loaded_ctx", 0) or 0) if client is not None else 0
        if not ctx and cfg is not None:
            try:
                from jaeger_ai.main import _context_budget_for
                budgeted, _reserve = _context_budget_for(cfg)
                ctx = int(budgeted or 0)
            except Exception:  # noqa: BLE001
                ctx = int(getattr(getattr(cfg, "model", None), "ctx", 0) or 0)
        return {
            "kind": "local",
            "provider": "local",
            "model": name or None,
            "ctx": ctx or None,
        }
    except Exception:  # noqa: BLE001
        return {"kind": "unknown", "provider": None, "model": None, "ctx": None}


def mode_info() -> dict:
    """The CURRENT mode + the model that is actually serving.

    ``model`` is the serving brain (external when one is on). The local
    preset name stays on ``local_preset_model`` so "what mode am I in?"
    and "which LLM is answering?" cannot disagree.
    """
    m = _state["mode"]
    preset = MODES.get(m, {})
    brain = serving_brain()
    return {
        "mode": m,
        "model": brain.get("model") or preset.get("model"),
        "provider": brain.get("provider"),
        "kind": brain.get("kind"),
        "ctx": brain.get("ctx"),
        "serving": brain,
        "local_preset_model": preset.get("model"),
        "voice": bool(preset.get("voice", True)),
        "options": list(MODES),
    }


def _resident_model() -> str:
    """The model registry key currently loaded. Tracked across switches;
    seeded from the instance config's boot model on first call."""
    if _state["model"] is None:
        try:
            from jaeger_ai.main import _pipeline
            cfg = _pipeline.get("config")
            _state["model"] = getattr(getattr(cfg, "model", None), "model_path", None)
        except Exception:  # noqa: BLE001
            _state["model"] = None
    return _state["model"] or ""


def _publish(mode: str) -> None:
    try:
        from jaeger_ai.core.messages import ModeState
        from jaeger_ai.core.runtime.autonomy import current_autonomy
        from jaeger_ai.main import _pipeline
        bus = _pipeline.get("chassis_bus")
        if bus is not None:
            bus.publish(ModeState(mode=mode, autonomy=current_autonomy()))
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
    brain = serving_brain()
    if brain.get("kind") == "external":
        return {
            "ok": False,
            "error": (
                f"an external brain is serving ({brain.get('provider')} · "
                f"{brain.get('model')}). normal/high only swap the local "
                "llama.cpp/MLX lane — use /model to change the active brain."
            ),
            "serving": brain,
        }
    if target == _state["mode"]:
        return {"ok": True, "mode": target, "unchanged": True}

    preset = MODES[target]
    want_model = preset["model"]
    if want_model != _resident_model():
        try:
            from jaeger_ai.main import _pipeline, switch_model
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
