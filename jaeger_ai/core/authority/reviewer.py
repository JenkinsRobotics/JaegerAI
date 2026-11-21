"""Reviewer-model path for autonomy 'scoped' (Approve for me).

Actions already inside saved scope are not sent here. Out-of-scope actions
are described (secrets redacted) to a tool-less reviewer model. The reviewer
returns approve, deny, or unsure plus a short reason. Approve means the
action may run; deny or unsure falls back to asking the owner. Hardline
blocks never reach this module.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

VERDICTS = ("approve", "deny", "unsure")
MAX_REVIEW_CHARS = 64_000

REVIEW_SYSTEM = """You are a permission reviewer for Jaeger, a personal assistant.
The owner has chosen "Approve for me": actions inside a saved approval scope
run automatically; you review actions outside that scope.

Decide whether this proposed tool call should run now, given the owner's
request, the action, and the rules. You cannot run tools. You do not grant
standing permission.

Rules:
- Approve only when the action is a reasonable, limited next step of the
  owner's current request, and is not a surprising expansion of scope
  (new destinations, credentials, payments, destructive or irreversible
  work, messaging third parties, or changing permissions).
- Deny when the action is off-request, destructive without a clear ask,
  or would leave the owner's machine or accounts in a worse state.
- Return unsure when you cannot tell, the arguments are incomplete, or a
  person should decide.

Reply with a single JSON object and nothing else:
{"verdict": "approve"|"deny"|"unsure", "reason": "one short sentence"}
"""

_JSON_BLOCK = re.compile(r"\{[^{}]*\"verdict\"[^{}]*\}", re.I | re.S)


def _redact(value: Any) -> Any:
    try:
        from jaeger_ai.core.redaction import redact_value
        return redact_value(value)
    except Exception:  # noqa: BLE001 — never send unredacted args if this fails
        try:
            from jaeger_os.core.safety.redact import redact_obj
            return redact_obj(value)
        except Exception:
            return "<redacted>"


def reviewer_prompt(*, user_request: str, tool: str, arguments: Any, rules: str = "") -> str:
    args = json.dumps(_redact(arguments), default=str, ensure_ascii=False)
    request = (user_request or "").strip() or "(no current request text)"
    extra = (rules or "").strip()
    prompt = (
        f"Owner's request:\n{request}\n\n"
        f"Proposed action: {tool or '(unknown tool)'}\n"
        f"Arguments (secrets redacted):\n{args}\n"
        + (f"\nAdditional rules:\n{extra}\n" if extra else "")
        + "\nYour decision:"
    )
    if len(prompt) > MAX_REVIEW_CHARS:
        raise ValueError("The complete action and request exceed the reviewer context limit.")
    return prompt


def parse_review(text: str) -> tuple[str, str]:
    """Return (verdict, reason). Unparseable output is unsure."""
    raw = (text or "").strip()
    blob = raw
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.S)
    if fenced:
        blob = fenced.group(1)
    else:
        found = _JSON_BLOCK.search(raw)
        if found:
            blob = found.group(0)
    try:
        data = json.loads(blob)
    except Exception:
        data = {}
    if not isinstance(data, dict):
        data = {}
    verdict = str(data.get("verdict") or "").strip().lower()
    if verdict not in VERDICTS:
        # Plain-word fallback
        lowered = raw.lower()
        if re.search(r"\bapprove\b", lowered) and not re.search(r"\bdeny\b|\bunsure\b", lowered):
            verdict = "approve"
        elif re.search(r"\bdeny\b", lowered):
            verdict = "deny"
        else:
            verdict = "unsure"
    reason = str(data.get("reason") or "").strip()
    if not reason:
        reason = raw[:240].strip() or "The reviewer did not give a reason."
    return verdict, reason[:400]


def review_action(
    gateway: Any,
    *,
    user_request: str,
    tool: str,
    arguments: Any,
    model: str | None = None,
    provider: str | None = None,
    timeout_s: float = 45.0,
) -> tuple[str, str]:
    """Run a tool-less reviewer completion. On failure, return unsure."""
    try:
        prompt = reviewer_prompt(
            user_request=user_request, tool=tool, arguments=arguments,
        )
    except ValueError:
        return "unsure", "The complete action and request exceed the reviewer context limit; owner review is required."
    loop = getattr(gateway, "_loop", None)
    if loop is None or not loop.is_running():
        return "unsure", "The reviewer is unavailable right now."
    import asyncio
    import threading
    cancel = threading.Event()
    fut = None
    try:
        fut = asyncio.run_coroutine_threadsafe(
            gateway._model_chat(
                prompt,
                model=model,
                provider=provider,
                system_prompt=REVIEW_SYSTEM,
                history=(),
                controls={"reasoning_effort": "low", "max_tokens": 1024},
                interrupt_event=cancel,
            ),
            loop,
        )
        text = fut.result(timeout=max(5.0, float(timeout_s)))
    except Exception as exc:  # noqa: BLE001 — a reviewer failure asks the owner
        cancel.set()
        if fut is not None and not fut.done():
            fut.cancel()
        logger.info("approval reviewer failed: %s", type(exc).__name__)
        return "unsure", "The reviewer could not complete a decision."
    return parse_review(str(text or ""))
