"""Explicit consumer parity for the bridge's first-party surfaces.

Adding an operation to the bridge requires adding it here in the same change.
``bridge_only`` is an honest supported state: the protocol implements the
operation, but the native app does not claim a dedicated consumer yet.
"""

from __future__ import annotations

SWIFT_QUERY_SUPPORT = {
    "contract": "bridge_only", "identity": "dedicated", "characters": "dedicated",
    "character": "dedicated", "character_card": "bridge_only", "config": "generic",
    "serving_model": "bridge_only", "settings_catalog": "generic",
    "permissions": "dedicated", "instance_exists": "bridge_only",
    "setup_defaults": "dedicated", "model_catalog": "bridge_only",
    "model_picker": "dedicated", "session_contract": "bridge_only",
    "list_sessions": "dedicated", "load_session": "dedicated",
    "search_sessions": "bridge_only", "check_update": "dedicated",
    "list_skills": "bridge_only", "get_skill": "bridge_only",
    "list_mcp_servers": "bridge_only", "list_tools": "bridge_only",
    "list_credentials": "bridge_only", "skill_usage": "bridge_only",
    "board": "dedicated", "heartbeat": "bridge_only", "cron": "bridge_only",
    "list_schedules": "bridge_only",
}

SWIFT_COMMAND_SUPPORT = {
    "select_character": "dedicated", "make_default": "dedicated",
    "save_profile": "dedicated", "save_traits": "dedicated",
    "save_config": "generic", "save_identity": "dedicated",
    "revoke_permission": "dedicated", "speak": "dedicated",
    "settings_set": "generic", "run_update": "dedicated",
    "new_session": "dedicated", "create_instance": "dedicated",
    "configure_model": "dedicated",
}

for _name in (
    "clone_skill", "install_skill", "enable_skill", "disable_skill", "remove_skill",
    "configure_mcp_server", "enable_mcp_server", "disable_mcp_server",
    "remove_mcp_server", "reload_tools", "set_credential", "delete_credential",
    "configure_fallback_chain", "create_session", "clear_session", "delete_session",
    "reconcile_session_transcript", "create_schedule", "cancel_schedule",
    "pause_schedule", "resume_schedule",
):
    SWIFT_COMMAND_SUPPORT[_name] = "bridge_only"

__all__ = ["SWIFT_COMMAND_SUPPORT", "SWIFT_QUERY_SUPPORT"]
