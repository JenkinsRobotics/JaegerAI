"""Commit setup to the selected identity; reruns never recreate its directory."""
from __future__ import annotations

from typing import Any

from jaeger_ai.core.instance.schemas import Config, Identity, dump_yaml, load_yaml
from jaeger_ai.core.models.configuration import selected_model_config


def onboarding_identity(layout: Any) -> dict[str, str]:
    if layout is None or not layout.exists():
        return {}
    from jaeger_ai.personality.character import active_character_id
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
        if args.get("permission_mode"):
            updated.permissions.mode = str(args["permission_mode"])
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
            from jaeger_ai.personality.character import bind_character
            bind_character(layout.root, character_id)
    else:
        from jaeger_ai.core.instance.setup_wizard import create_instance
        layout = create_instance(
            character_id=str(args.get("character_id") or "assistant"),
            name=(layout.root.name if layout is not None else args.get("name")),
            display_name=args.get("display_name") or None,
            role=args.get("role") or None,
            voice_id=("af_heart" if profile == "female" else "am_michael") if profile else None,
            awake_model=model, awake_provider=provider,
            asleep_model=args.get("asleep_model") or model,
            permission_mode=str(args.get("permission_mode") or "confirm"),
        )
    from jaeger_ai.core.models.onboarding_credentials import persist_pending
    from jaeger_ai.core.instance.first_boot import (
        begin,
        commit_to_instance,
        record_bench,
        record_character,
        record_model_selection,
        record_setup_preferences,
        reset,
    )
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
    return layout
