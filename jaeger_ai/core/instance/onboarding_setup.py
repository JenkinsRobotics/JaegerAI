"""Commit setup to the selected identity; reruns never recreate its directory."""
from __future__ import annotations

from typing import Any

from jaeger_ai.core.instance.schemas import Config, Identity, dump_yaml, load_yaml
from jaeger_ai.core.models.configuration import selected_model_config


def onboarding_blueprint(layout: Any) -> dict[str, Any]:
    """Return the coherent 10-step first-run onboarding blueprint with safe defaults.

    Distinguishes a brand-new installation (``fresh_install``) from a clean
    personal workspace migrated from an older dev profile (``migrated_clean_personal``)
    or an already established instance (``existing_instance``). Every optional step
    carries sensible defaults and may be skipped so users can talk to Truth right away.
    """
    from jaeger_ai.core.instance.first_boot import snapshot
    record = snapshot(layout) if layout is not None else {}
    install_mode = str(record.get("install_mode") or "")
    if not install_mode:
        if record.get("migrated"):
            install_mode = "existing_instance"
        elif layout is not None and getattr(layout, "exists", lambda: False)():
            install_mode = "existing_instance"
        else:
            install_mode = "fresh_install"

    return {
        "install_mode": install_mode,
        "default_companion": "Truth",
        "steps": [
            {"id": "companion_name", "title": "Companion name", "default": "Truth", "skippable": True},
            {"id": "avatar_voice", "title": "Avatar and preferred voice", "default": {"character_id": "truth", "voice_profile": "female"}, "skippable": True},
            {"id": "audio_devices", "title": "Microphone and speakers", "default": {"audio_input": "Insta360 Link 2", "audio_output": "Mac Studio Speakers"}, "skippable": True},
            {"id": "camera_vision", "title": "Camera and vision options", "default": {"camera_device": "Insta360 Link 2", "vision_enabled": True, "vision_model": "qwen3.5:9b"}, "skippable": True},
            {"id": "models", "title": "Local and cloud model preferences", "default": {"awake_provider": "ollama", "awake_model": "mistral-large-4:cloud", "local_fallback_model": "qwen3.5:9b"}, "skippable": False},
            {"id": "memory_privacy", "title": "Memory and privacy settings", "default": {"epistemic_memory": True, "privacy_local_only": False}, "skippable": True},
            {"id": "autonomy", "title": "Operating mode", "default": "auto", "options": ["ask", "scoped", "auto", "full"], "labels": {"ask": "Ask for approval", "scoped": "Approve for me", "auto": "Automatic", "full": "Full access"}, "skippable": True},
            {"id": "computer_access", "title": "Permitted computer and application access", "default": {"computer_use": True, "filesystem_write": True, "shell_mode": "confirm"}, "skippable": True},
            {"id": "heartbeat_notifications", "title": "Heartbeat, quiet hours, and notifications", "default": {"heartbeat_interval_minutes": 30, "quiet_start_hour": 22, "quiet_end_hour": 7, "digest_enabled": True}, "skippable": True},
            {"id": "personal_goals", "title": "Personal goals and optional human needs priorities", "default": {"disabled_dimensions": [], "initial_goals": []}, "skippable": True},
        ],
    }


def onboarding_identity(layout: Any) -> dict[str, str]:
    if layout is None or not layout.exists():
        return {}
    from jaeger_ai.features.personality.character import active_character_id
    from jaeger_ai.core.instance.first_boot import snapshot
    identity = load_yaml(layout.identity_path, Identity)
    state = snapshot(layout)
    return {"character_id": active_character_id(layout.root),
            "display_name": identity.name, "role": identity.role,
            "voice_id": identity.voice_id or "",
            "voice_profile": state.get("voice_profile") or ("male" if (identity.voice_id or "").startswith(("am_", "bm_")) else "female"),
            "interaction_posture": state.get("interaction_posture") or "attentive"}


def complete_setup(layout: Any, args: dict[str, Any]) -> Any:
    model = str(args.get("awake_model") or "").strip()
    provider = str(args.get("awake_provider") or "").strip()
    if not model or not provider:
        raise ValueError("Select a provider and model before starting your OS")
    character_id = str(args.get("character_id") or "").strip()
    if character_id:
        from jaeger_ai.core.instance.setup_wizard import _character_shim
        _character_shim(character_id)
    profile = str(args.get("voice_profile") or "").strip()
    if profile and profile not in {"female", "male"}:
        raise ValueError("Unknown voice profile")
    posture = str(args.get("interaction_posture") or "").strip()
    if posture and posture not in {"attentive", "pragmatic"}:
        raise ValueError("Unknown interaction posture")
    if layout is not None and layout.exists():
        config = load_yaml(layout.config_path, Config)
        updated, _, _ = selected_model_config(config, provider=provider, model=model)
        if args.get("autonomy") or args.get("permission_mode"):
            from jaeger_ai.core.runtime.autonomy import (
                AUTONOMY, permissions_mode_for, autonomy_from_permissions_mode,
            )
            autonomy = str(args.get("autonomy") or "").strip().lower()
            if autonomy not in AUTONOMY:
                autonomy = autonomy_from_permissions_mode(str(args.get("permission_mode") or ""))
            updated.automation.autonomy = autonomy
            updated.permissions.mode = permissions_mode_for(autonomy)
        if args.get("asleep_model"):
            updated.deep_think.coder_model = str(args["asleep_model"])
        if profile:
            updated.kokoro_tts.voice = "af_heart" if profile == "female" else "am_michael"
        edits_identity = any(args.get(key) for key in ("display_name", "role", "voice_profile", "interaction_posture"))
        identity = load_yaml(layout.identity_path, Identity) if edits_identity else None
        if identity is not None:
            for key, field in (("display_name", "name"), ("role", "role")):
                if args.get(key):
                    setattr(identity, field, str(args[key]).strip())
            if profile:
                identity.voice_id = updated.kokoro_tts.voice
            if posture:
                identity.voice_tone = "warm, attentive, empathetic" if posture == "attentive" else "direct, concise, pragmatic"
            identity = Identity.model_validate(identity.model_dump())
        updated = Config.model_validate(updated.model_dump())
        # Validate before writing; keep identity, credentials, memory and all
        # unrelated settings intact when reconfiguring an existing instance.
        dump_yaml(layout.config_path, updated)
        if identity is not None and any(args.get(key) for key in ("display_name", "role", "voice_profile", "interaction_posture")):
            dump_yaml(layout.identity_path, identity)
        if character_id:
            from jaeger_ai.features.personality.character import bind_character
            bind_character(layout.root, character_id)
    else:
        from jaeger_ai.core.instance.setup_wizard import create_instance
        layout = create_instance(
            character_id=str(args.get("character_id") or "truth"),
            name=(layout.root.name if layout is not None else args.get("name")),
            display_name=args.get("display_name") or "Truth",
            role=args.get("role") or None,
            voice_id=("af_heart" if profile == "female" else "am_michael") if profile else None,
            awake_model=model, awake_provider=provider,
            asleep_model=args.get("asleep_model") or model,
            permission_mode=str(args.get("permission_mode") or "confirm"),
            autonomy=str(args.get("autonomy") or "") or None,
        )
    # Persist optional Human Needs / Heartbeat onboarding preferences & initial goals.
    hn_updates: dict[str, Any] = {}
    for key in ("heartbeat_interval_minutes", "quiet_start_hour", "quiet_end_hour", "disabled_dimensions", "proactive_enabled", "digest_enabled"):
        if args.get(key) is not None:
            hn_updates[key] = args[key]
    initial_goals = args.get("initial_goals")
    if hn_updates or (isinstance(initial_goals, list) and initial_goals):
        from jaeger_ai.features.human_needs.store import HumanNeedsStore
        hn_store = HumanNeedsStore()
        if hn_updates:
            hn_store.update_preferences(hn_updates)
        if isinstance(initial_goals, list):
            for g in initial_goals:
                if isinstance(g, dict) and str(g.get("title") or "").strip():
                    hn_store.add_goal(
                        title=str(g["title"]).strip(),
                        dimension=str(g.get("dimension") or "self_actualization"),
                        priority=int(g.get("priority", 3)),
                        notes=str(g.get("notes") or ""),
                        success_metric=str(g.get("success_metric") or ""),
                    )
    # Capture optional device/vision/privacy onboarding metadata before first_boot reset.
    extra_prefs = {
        k: args[k] for k in (
            "audio_input", "audio_output", "camera_device", "vision_enabled",
            "local_fallback_model", "privacy_local_only", "computer_access",
        ) if args.get(k) is not None
    }
    from jaeger_ai.core.models.onboarding_credentials import persist_pending
    from jaeger_ai.core.instance.first_boot import (
        begin,
        commit_to_instance,
        record_bench,
        record_character,
        record_model_selection,
        record_setup_preferences,
        reset,
        snapshot,
    )
    prev_snapshot = snapshot(layout)
    prev_install_mode = prev_snapshot.get("install_mode")
    prev_onboarding_prefs = dict(prev_snapshot.get("onboarding_preferences") or {})
    persist_pending(layout)
    if not args.get("resume_onboarding"):
        reset(layout)
    begin(layout)
    record_model_selection(layout, provider, model)
    record_setup_preferences(layout, voice_profile=profile, interaction_posture=posture)
    # The unified wizard already completed these choices. Do not ask for them
    # a second time when OS initialization takes over.
    if character_id:
        record_bench(layout)
        record_character(
            layout,
            "custom" if character_id == "assistant" else "preset",
            character_id=character_id,
        )
    facts = {key: str(args[source]).strip() for source, key in
             (("user_name", "name"), ("custom_prime_directive", "custom_prime_directive")) if args.get(source)}
    if facts:
        from jaeger_agent.memory.sqlite_store import seed_facts
        seed_facts(layout, facts)
    commit_to_instance(layout)
    if extra_prefs or prev_install_mode or prev_onboarding_prefs:
        import yaml
        from jaeger_ai.core.instance.first_boot import _read, _write
        doc = _read(layout)
        if prev_install_mode:
            doc.setdefault("install_mode", prev_install_mode)
        merged_prefs = {**prev_onboarding_prefs, **extra_prefs}
        if merged_prefs:
            doc["onboarding_preferences"] = merged_prefs
        _write(layout, doc)
    return layout
