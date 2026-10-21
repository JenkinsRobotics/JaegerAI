"""Public tool result categories. Never include raw arguments or errors in SSE."""
from typing import Any


def tool_outcome(ok: bool, result: Any) -> str:
    if ok:
        return "completed"
    error_type = result.get("error_type") if isinstance(result, dict) else None
    if isinstance(result, dict) and result.get("interrupted") is True and error_type != "effect_indeterminate":
        return "cancelled"
    if not isinstance(error_type, str):
        error_type = ""
    return {
        "permission_denied": "denied", "unknown_tool": "rejected",
        "unsupported_sandbox": "unsupported", "effect_indeterminate": "unknown",
        "cancelled": "cancelled",
    }.get(error_type, "failed")
