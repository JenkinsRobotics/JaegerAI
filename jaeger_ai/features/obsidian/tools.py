"""Optional agent tools for the read-only Obsidian vault adapter."""

from __future__ import annotations

import os

from jaeger_os.core.tools.tool_registry import register_tool_from_function

from .adapter import VaultError, list_notes, read_note, search_notes, vault_root


def register_if_enabled() -> None:
    if not os.environ.get("JAEGER_OBSIDIAN_VAULT"):
        return
    try:
        vault_root()
    except VaultError:
        return

    @register_tool_from_function(name="obsidian_list_notes", side_effect="read")
    def obsidian_list_notes(limit: int = 50) -> dict:
        """List Markdown note paths in the configured Obsidian vault."""
        try:
            return {"ok": True, **list_notes(limit)}
        except (VaultError, OSError, ValueError) as exc:
            return {"ok": False, "error": str(exc)}

    @register_tool_from_function(name="obsidian_read_note", side_effect="read")
    def obsidian_read_note(path: str) -> dict:
        """Read a Markdown note, splitting YAML front matter from its body."""
        try:
            return {"ok": True, "note": read_note(path)}
        except (VaultError, OSError, ValueError) as exc:
            return {"ok": False, "error": str(exc)}

    @register_tool_from_function(name="obsidian_search_notes", side_effect="read")
    def obsidian_search_notes(query: str, limit: int = 20) -> dict:
        """Search plain text across Markdown notes in the configured vault."""
        try:
            return {"ok": True, **search_notes(query, limit)}
        except (VaultError, OSError, ValueError) as exc:
            return {"ok": False, "error": str(exc)}
