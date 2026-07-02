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
