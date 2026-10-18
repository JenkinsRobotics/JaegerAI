"""Truthful projection for the bridge's explicitly text-only goal contract."""

from jaeger_ai.core.redaction import redact_text


def project_goal(goal_id, thread, receipt=None):
    receipt = receipt or {}
    raw_status = receipt.get("status", "not_admitted")
    result = receipt.get("result") or {}
    # Model-supplied task/receipt/verification fields are not execution evidence.
    output = result.get("output", result.get("text", receipt.get("output", "")))
    return {
        "id": goal_id,
        "thread": thread,
        "execution_mode": "text_only",
        "execution_verified": False,
        "status": "text_only_completed" if raw_status == "completed" else raw_status,
        "request_status": raw_status,
        "result": {"output": redact_text(output) if isinstance(output, str) else ""},
    }
