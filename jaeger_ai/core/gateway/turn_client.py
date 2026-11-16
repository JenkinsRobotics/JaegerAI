"""One-call Gateway turn for surfaces that used to run turns in-process.

CLI REPL, TUI fallback, bridge local mode, voice runtime, webhooks and
diagnostics call :func:`run_gateway_turn`; it uses the shared
:class:`~jaeger_ai.core.gateway.client.GatewayTurnClient` (the same client the
bridge uses when Gateway-backed) and returns the legacy turn-dict shape, so
callers did not change. A lost reply is never resent: the request id is
polled until it settles.
"""

from __future__ import annotations

import time
import uuid
from typing import Any


def session_id_for(session_key: str | None, source: str) -> str:
    key = (session_key or "").strip() or "default"
    if ":" in key or len(key) >= 32:
        return key  # already a Gateway session id
    return f"{source}:{key}"


def run_gateway_turn(text: str, *, session_key: str | None = None, source: str = "cli",
                     caller: str = "bridge", tier: str | None = None,
                     timeout_s: float = 900.0) -> dict[str, Any]:
    """Returns ``{text, error, status, elapsed_s, halt_reason, request_id, session_id}``."""
    from jaeger_ai.core.gateway.client import GatewayTurnClient

    started = time.time()
    sid = session_id_for(session_key, source)
    rid = f"{source}-{uuid.uuid4().hex[:16]}"
    client = GatewayTurnClient(caller=caller)

    def shaped(status: str, text_out: str = "", error: str | None = None, halt: str | None = None) -> dict[str, Any]:
        return {"text": text_out, "error": error, "status": status,
                "elapsed_s": round(time.time() - started, 2),
                "halt_reason": halt or ("complete" if status == "completed" else status),
                "request_id": rid, "session_id": sid}

    try:
        try:
            client.get_session(sid)
        except Exception:  # noqa: BLE001 — missing: create it (409 = raced, fine)
            try:
                client.ensure_session(sid, title=f"{source.title()} chat", source=source)
            except Exception:  # noqa: BLE001
                pass
        choices: dict[str, Any] = {"source": source}
        if tier:
            choices["interaction_tier"] = tier
        deadline = time.monotonic() + timeout_s
        while True:
            try:
                client.submit(sid, text, request_id=rid, **choices)
                break
            except Exception as exc:  # noqa: BLE001
                busy = "409" in str(exc) and "belongs" not in str(exc)
                if busy and time.monotonic() < deadline:
                    time.sleep(3)  # session busy: wait our turn, same request id
                    continue
                raise
    except Exception as exc:  # noqa: BLE001
        return shaped("failed", error=f"Gateway did not accept the turn: {exc}", halt="gateway_unavailable")
    result = client.wait(sid, rid, timeout_s=max(5.0, deadline - time.monotonic()), poll_s=1.0,
                         submitted_at=started)
    if result.status == "timeout":
        return shaped("execution_unknown", error="Still running in the Gateway; the reply will appear in that chat.",
                      halt="timeout")
    return shaped(result.status, result.text.strip(),
                  None if result.status == "completed" else str(result.error or result.status))
