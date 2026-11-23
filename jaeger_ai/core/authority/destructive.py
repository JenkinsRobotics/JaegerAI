"""Canonical detection of destructive or irreversible actions.

Delegates directly to standalone ``jaeger-authority`` (Module 05), preserving
JaegerAI's two product-specific framework handoff gates (``framework_delegate``
and ``framework_apply_diff``).
"""

from __future__ import annotations

from typing import Any, Mapping

from jaeger_authority import destructive_reason as _v2_destructive_reason
from jaeger_authority import shell_command_reason as shell_command_reason


def destructive_reason(tool_name: Any, arguments: Mapping[str, Any] | None) -> str | None:
    """Why this tool call is destructive/irreversible (needs fresh owner approval), or None."""
    args = dict(arguments or {})
    raw = str(tool_name or "").strip().lower()
    if raw == "framework_delegate":
        return f"handing a task to another agent framework ({args.get('framework') or '?'})"
    if raw == "framework_apply_diff":
        return f"applying another framework's patch to {args.get('workspace') or '?'}"
    return _v2_destructive_reason(tool_name, args)


__all__ = ["destructive_reason", "shell_command_reason"]
