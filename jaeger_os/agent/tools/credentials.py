"""Credential skills (jaeger-specific safety feature).

  • get_credential(name)    — read a secret by name; rejects if perms > 0600
  • list_credentials()      — list stored credential NAMES (never values)

The agent must use this tool to access credentials — direct file reads
under <instance>/credentials/ are rejected by `file_read`. Once a
credential value is fetched, it should flow to other tool calls but
NEVER be echoed back to the user.
"""

from __future__ import annotations

from typing import Any

from jaeger_os.agent.schemas.tool_registry import register_tool_from_function
from jaeger_os.core import credentials as creds
from jaeger_os.core.context import _require_layout


def get_credential(name: str) -> dict[str, Any]:
    """Fetch a credential by name. NEVER read credential files directly —
    this is the only sanctioned access path. Use the returned value in a
    tool call (e.g. an API request) but do NOT echo it back to the user."""
    return creds.get_credential_tool_result(_require_layout(), name=name)


def list_credentials() -> dict[str, Any]:
    """List the names of every credential currently stored. Values are
    never returned — use get_credential(name) for the actual value."""
    return {"credentials": creds.list_credentials(_require_layout())}


# ---------------------------------------------------------------------------
# Agent-facing tool wrappers (migrated from main._register_builtins).
# ---------------------------------------------------------------------------
@register_tool_from_function(name="get_credential")
def _t_get_credential(name: str) -> dict:
    """Look up a secret (API key, token) by name from the instance's
    credentials/ store. NEVER read credential files directly — this is
    the only sanctioned access path. The returned value is for tool
    use only; do NOT echo it back to the user in your reply.
    """
    return creds.get_credential_tool_result(_require_layout(), name=name)


@register_tool_from_function(name="list_credentials", side_effect="read")
def _t_list_credentials() -> dict:
    """List the names of every credential currently stored. Values
    are never returned by this tool — use get_credential(name) for
    the actual value, and never echo the value in your reply."""
    return {"credentials": creds.list_credentials(_require_layout())}


@register_tool_from_function(name="set_credential", side_effect="write")
def _t_set_credential(name: str, value: str) -> dict:
    """Save a secret (API key, token, chat ID) the user gave you into
    the instance's credentials/ store, by name. Use this to PERSIST a
    credential the user just provided — do NOT tell them to run a CLI
    or set an env var; store it here. The value is written 0600 and is
    NEVER echoed back (the result returns only the name). Pick a clear
    UPPER_SNAKE name matching what the plugin / setup_plugin expects
    (e.g. TELEGRAM_BOT_TOKEN). Returns {saved, name} or {saved:false,
    error} — never raises."""
    try:
        creds.set_credential(_require_layout(), name, value)
    except Exception as exc:  # noqa: BLE001 — surface as a tool error, never raise
        return {"saved": False, "name": name, "error": str(exc)}
    return {"saved": True, "name": name}
