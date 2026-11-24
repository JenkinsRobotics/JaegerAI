"""Canonical tool identity and actor trust classification (zero jaeger_ai imports)."""

from __future__ import annotations

from typing import Any, Mapping

TOOL_ALIASES: Mapping[str, str] = {
    # local shell
    "shell": "shell",
    "terminal": "shell",
    "run_shell": "shell",
    "exec": "shell",
    "exec_command": "shell",
    "bash": "shell",
    "sh": "shell",
    "zsh": "shell",
    "run_command": "shell",
    "shell_exec": "shell",
    "execute_command": "shell",
    "run_terminal_command": "shell",
    # remote shell
    "remote_terminal": "remote_shell",
    "remote_shell": "remote_shell",
    "ssh": "remote_shell",
    # arbitrary code execution
    "execute_code": "code_exec",
    "run_python": "code_exec",
    "run_in_venv": "code_exec",
    # git / files
    "git_push": "git_push",
    "push": "git_push",
    "write_file": "write_file",
    "edit_file": "write_file",
    "append_file": "write_file",
    "patch": "write_file",
    "apply_patch": "write_file",
    "delete_file": "delete_file",
    "read_file": "read_file",
    "view_file": "read_file",
    "list_dir": "read_file",
    "grep_search": "read_file",
    "find_by_name": "read_file",
    # desktop UI / screen control
    "computer_do": "computer_control",
    "computer_use": "computer_control",
    "computer_click": "computer_control",
    "computer_type_text": "computer_control",
    "computer_press_key": "computer_control",
    "computer_menu_select": "computer_control",
}

SHELL_TOOL_IDS = frozenset({"shell", "remote_shell"})
PRIVILEGED_TOOL_IDS = frozenset({
    "shell", "remote_shell", "code_exec", "deploy", "git_push", "computer_control",
})
IDENTITY_TOOL_IDS = frozenset({"set_name", "update_soul", "adjust_trait"})
OWNER_MANAGEMENT_TOOL_IDS = frozenset({"settings_set", "session_manage", "session_organize"})
MEMORY_WRITE_TOOL_IDS = frozenset({
    "remember", "forget", "memory", "remember_person",
    "knowledge_record_claim", "knowledge_verify_claim",
    "human_needs_add_goal", "human_needs_propose_opportunity", "human_needs_record_outcome",
})
OWNER_ACTOR_PREFIXES = ("owner", "human")
UNTRUSTED_ACTOR_PREFIXES = ("guest", "untrusted", "external_agent", "helper", "mcp", "a2a")
KNOWN_TIERS = frozenset({"read_only", "write_local", "external_effect", "hardware", "privileged"})
KNOWN_ACTION_TYPES = frozenset({"tool_call"})


def canonical_tool_id(name: Any) -> str:
    """Normalize tool aliases and namespaced names (mcp__x__terminal -> shell)."""
    raw = str(name or "").strip().lower().replace("-", "_")
    if not raw:
        return ""
    if raw in TOOL_ALIASES:
        return TOOL_ALIASES[raw]
    for sep in ("__", ".", ":", "/"):
        if sep in raw:
            tail = raw.rsplit(sep, 1)[-1]
            if tail in TOOL_ALIASES:
                return TOOL_ALIASES[tail]
    return raw


def is_owner_actor(actor: str) -> bool:
    a = (actor or "").strip().lower()
    return any(a == p or a.startswith(p + ":") for p in OWNER_ACTOR_PREFIXES)


def is_untrusted_actor(actor: str) -> bool:
    a = (actor or "").strip().lower()
    return any(a == p or a.startswith(p + ":") for p in UNTRUSTED_ACTOR_PREFIXES)
