"""The canonical event envelope ("trace") every Gateway event carries.

One function, :func:`annotate`, runs on the single durable write path
(``GatewaySessionStore._insert_event``), so every event a client sees, live or
replayed, carries the same correlation block under ``data["trace"]``::

    {
      "v": 1,
      "run_id":  "<request_id>",            # one user turn = one run
      "turn_id": "<turn_id>",
      "span_id": "tool:<call_id>",          # the node this event is about
      "parent_span_id": "step:<step_id>",   # draws the tree / flow diagram
      "kind":   "run|model|tool|approval|input|subagent|message|hook|info|presence",
      "name":   "list_dir",                 # node label
      "state":  "running|waiting|succeeded|failed|cancelled|denied|unknown" | null,
      "seq":    17,                         # per-run, gap-detectable (process-local)
      "ts":     1762921234.123,             # wall clock, seconds
      "duration_ms": 88 | null,             # on terminal transitions
      "agui":   "TOOL_CALL_START",          # nearest AG-UI event type
      "trace_id": "<32 hex>"               # W3C / OpenTelemetry trace id of the run
    }

The SSE ``id:`` is still the durable, global ``event_id`` (monotonic, the
resume cursor). ``seq`` is per run so a client can notice a hole inside one run.
Spans follow OpenTelemetry GenAI naming (invoke_agent > chat > execute_tool),
event names stay Jaeger's for compatibility, and ``agui`` maps each to the
AG-UI protocol so an AG-UI client can be fed by a thin adapter.
"""
from __future__ import annotations

import threading
import time
from collections import OrderedDict
from typing import Any

VERSION = 1
TERMINAL_STATES = frozenset({"succeeded", "failed", "cancelled", "denied", "unknown"})
ACTIVE_STATES = frozenset({"running", "waiting"})
#: Framework-responsibility events (execution loop, state, permissions,
#: orchestration, reliability): annotate their run, never become nodes.
RESPONSIBILITY_EVENTS = frozenset({
    "loop.iteration", "loop.stop", "loop.continuation", "state.memory", "state.saved", "policy.decision",
    "route.selected", "reliability.retry", "reliability.fallback", "reliability.exhausted",
    "reliability.timeout", "guardrail.tripped",
})

_lock = threading.Lock()
_seq: "OrderedDict[str, int]" = OrderedDict()
_starts: "OrderedDict[str, float]" = OrderedDict()
_CAP = 4096


def _bump(run_id: str) -> int:
    with _lock:
        n = _seq.pop(run_id, 0) + 1
        _seq[run_id] = n
        while len(_seq) > _CAP:
            _seq.popitem(last=False)
        return n


def _mark(span_id: str, state: str | None, ts: float) -> int | None:
    with _lock:
        if state in ("running", "waiting"):
            _starts.setdefault(span_id, ts)
            while len(_starts) > _CAP:
                _starts.popitem(last=False)
            return None
        if state in TERMINAL_STATES:
            start = _starts.pop(span_id, None)
            return None if start is None else max(0, int((ts - start) * 1000))
    return None


def _s(v: Any) -> str:
    return "" if v is None else str(v)


def _w3c_trace_id(rid: str) -> str | None:
    """W3C/OpenTelemetry trace id of a run (see :mod:`jaeger_ai.contract.otel`)."""
    if not rid:
        return None
    from jaeger_ai.contract.otel import trace_id
    return trace_id(rid)


def _run_span(rid: str) -> str:
    return f"run:{rid}"


def _activity(call: str, rid: str) -> str:
    """Gateway activity id for a model tool-call id (gateway.server._live_activity_id)."""
    if not call or not rid or call.startswith(("tool_", "sub_")):
        return call
    import re
    safe = re.sub(r"[^A-Za-z0-9_.-]", "", call)[:80]
    return f"tool_{rid.replace('-', '')[:12]}_{safe}" if safe else call


def _approval_state(d: dict[str, Any]) -> str:
    status = _s(d.get("status") or d.get("decision")).lower()
    if d.get("approved") is True or status in {"approved", "allow", "allowed", "once", "always", "session"}:
        return "succeeded"
    if d.get("approved") is False or status in {"denied", "deny", "rejected", "declined"}:
        return "denied"
    if status in {"expired", "cancelled", "timeout"}:
        return "cancelled"
    return "succeeded"


def classify(event: str, d: dict[str, Any]) -> dict[str, Any] | None:
    """(kind, span_id, parent_span_id, name, state, agui) for one event, or None."""
    rid = _s(d.get("request_id") or d.get("run_id"))
    run = _run_span(rid) if rid else None
    step = f"step:{d['step_id']}" if d.get("step_id") else None
    call = _s(d.get("call_id") or d.get("activity_id"))
    parent_run = f"run:{d['parent_run_id']}" if d.get("parent_run_id") else None

    def node(kind, span, parent, name, state, agui):
        return {"kind": kind, "span_id": span, "parent_span_id": parent, "name": name,
                "state": state, "agui": agui}

    if event == "turn.start":
        return node("run", run, parent_run, "turn", "running", "RUN_STARTED")
    if event in {"turn.finish", "turn.reconciled"}:
        return node("run", run, parent_run, "turn", "succeeded", "RUN_FINISHED")
    if event == "turn.failed":
        return node("run", run, parent_run, "turn", "failed", "RUN_ERROR")
    if event == "turn.cancelled":
        return node("run", run, parent_run, "turn", "cancelled", "RUN_FINISHED")
    if event == "turn.unknown":
        return node("run", run, parent_run, "turn", "unknown", "RUN_ERROR")
    if event == "model.started":
        return node("model", step, run, _s(d.get("model")) or f"model #{d.get('index', '')}".strip(),
                    "running", "STEP_STARTED")
    if event == "model.finished":
        return node("model", step, run, _s(d.get("model")) or f"model #{d.get('index', '')}".strip(),
                    "failed" if d.get("ok") is False else "succeeded", "STEP_FINISHED")
    if event in {"turn.reasoning", "turn.reasoning.done"}:
        return node("message", step or run, run if step else None, "reasoning", None,
                    "REASONING_MESSAGE_CONTENT" if event == "turn.reasoning" else "REASONING_MESSAGE_END")
    if event == "turn.delta":
        return node("message", step or run, run if step else None, "text", None, "TEXT_MESSAGE_CONTENT")
    if event in {"tool.started", "tool.completed", "tool.failed", "tool.done", "tool.error"} and call:
        state = {"tool.started": "running", "tool.completed": "succeeded", "tool.done": "succeeded"}.get(event, "failed")
        if event == "tool.failed" and _s(d.get("outcome")) in {"blocked", "denied", "blocked_by_hook"}:
            state = "denied"
        return node("tool", f"tool:{call}", step or run, _s(d.get("tool")) or "tool", state,
                    "TOOL_CALL_START" if state == "running" else "TOOL_CALL_RESULT")
    if event == "tool.progress" and call:
        # Progress annotates the open tool span; it never changes its state.
        return node("tool", f"tool:{call}", step or run, _s(d.get("tool")) or "tool", None, "CUSTOM")
    if event == "approval.request" and d.get("approval_id"):
        parent = f"tool:{d['call_id']}" if d.get("call_id") else run
        return node("approval", f"approval:{d['approval_id']}", parent,
                    _s(d.get("kind")) or "approval", "waiting", "CUSTOM")
    if event == "approval.resolved" and d.get("approval_id"):
        parent = f"tool:{d['call_id']}" if d.get("call_id") else run
        return node("approval", f"approval:{d['approval_id']}", parent,
                    _s(d.get("kind")) or "approval", _approval_state(d), "CUSTOM")
    if event == "clarify.request" and d.get("clarify_id"):
        return node("input", f"clarify:{d['clarify_id']}", run, "question", "waiting", "CUSTOM")
    if event == "clarify.resolved" and d.get("clarify_id"):
        st = {"cancelled": "cancelled", "expired": "cancelled"}.get(_s(d.get("status")), "succeeded")
        return node("input", f"clarify:{d['clarify_id']}", run, "question", st, "CUSTOM")
    if event in {"subagent.tool.started", "subagent.tool.finished"} and call and d.get("subagent_id"):
        done = event.endswith("finished")
        state = ("succeeded" if d.get("ok") is not False else "failed") if done else "running"
        return node("tool", f"tool:{call}", f"agent:{d['subagent_id']}", _s(d.get("tool")) or "tool", state,
                    "TOOL_CALL_RESULT" if done else "TOOL_CALL_START")
    if event in {"room.started", "room.finished"} and run:
        if event == "room.started":
            return node("run", run, None, "room", "running", "RUN_STARTED")
        st = "failed" if _s(d.get("status")) == "failed" else "succeeded"
        return node("run", run, None, "room", st, "RUN_FINISHED" if st == "succeeded" else "RUN_ERROR")
    if event == "room.turn" and d.get("turn_id"):
        # One member's turn in a room: an agent lane, nested under the member
        # turn that @-handed it the room (else under the room run).
        status = _s(d.get("status"))
        st = {"running": "running", "failed": "failed", "passed": "succeeded"}.get(status, "succeeded")
        parent = f"agent:{d['parent_turn_id']}" if d.get("parent_turn_id") else run
        return node("subagent", f"agent:{d['turn_id']}", parent, _s(d.get("agent_name") or d.get("agent_id")) or "agent",
                    st, "STEP_STARTED" if st == "running" else "STEP_FINISHED")
    if event == "agent.message":
        span = f"agent:{d['turn_id']}" if d.get("turn_id") else (f"agent:{d['handoff_id']}" if d.get("handoff_id") else None)
        if span:
            return node("message", span, None, _s(d.get("agent_name") or d.get("agent_id")) or "agent", None,
                        "TEXT_MESSAGE_CONTENT")
    if event in {"delegate.started", "delegate.finished", "delegate.failed"} and d.get("handoff_id"):
        # An inner helper (one-mind collaboration): a node under the lead's tool call.
        hid = _s(d["handoff_id"])
        call = _activity(call, rid)
        st = {"delegate.started": "running", "delegate.finished": "succeeded"}.get(event)
        if st is None:
            st = {"cancelled": "cancelled", "denied": "denied", "execution_unknown": "unknown"}.get(
                _s(d.get("status")), "failed")
        return node("subagent", f"agent:{hid}", f"tool:{call}" if call else run,
                    _s(d.get("agent_name") or d.get("profile") or d.get("agent_id")) or "helper", st,
                    "STEP_STARTED" if st == "running" else "STEP_FINISHED")
    if event in {"agent.handoff", "agent.handoff.finished", "subagent.started", "subagent.finished"}:
        h = d.get("handoff") if isinstance(d.get("handoff"), dict) else d
        hid = _s(h.get("id") or h.get("handoff_id") or d.get("subagent_id"))
        if not hid:
            return None
        hmeta = h.get("metadata") if isinstance(h.get("metadata"), dict) else {}
        # A handoff carries the asking tool call in its metadata (call_agent).
        # Older records hold the model's raw id; the tool span uses the
        # Gateway's per-request activity id, so map it or the node is orphaned.
        call = call or _activity(_s(hmeta.get("call_id")), rid)
        name = _s((h.get("metadata") or {}).get("target_display") if isinstance(h.get("metadata"), dict) else "") \
            or _s(h.get("to_agent_id") or d.get("agent_id") or d.get("name")) or "agent"
        done = event in {"agent.handoff.finished", "subagent.finished"}
        hstatus = _s(h.get("status"))
        if done:
            st = {"failed": "failed", "error": "failed", "cancelled": "cancelled", "denied": "denied",
                  "execution_unknown": "unknown"}.get(hstatus, "succeeded")
        else:
            st = "waiting" if hstatus == "pending_approval" else "running"
        return node("subagent", f"agent:{hid}", f"tool:{call}" if call else run, name, st,
                    "STEP_FINISHED" if done else "STEP_STARTED")
    if event == "hook.decision":
        action = _s(d.get("action")) or "allow"
        return node("hook", f"hook:{_s(d.get('hook'))}:{action}:{call}", f"tool:{call}" if call else run,
                    f"{_s(d.get('hook')) or 'hook'} · {action}", "denied" if action == "deny" else "succeeded",
                    "CUSTOM")
    if event in RESPONSIBILITY_EVENTS and run:
        return node("info", step or run, run if step else None, event, None, "CUSTOM")
    if event in {"turn.progress", "tools.selected", "turn.context", "turn.plan", "turn.model",
                 "sources", "files.changed", "search.count", "follow_ups", "turn.steer", "turn.cancel"} and run:
        return node("info", step or run, run if step else None, event, None,
                    "STATE_DELTA" if event == "turn.plan" else "CUSTOM")
    # Presence frames are published only by the Gateway bus (see
    # contract.presence); here they are recognised by shape, not re-declared.
    if event.endswith(".state") and _s(d.get("state")) in _presence_states():
        return node("presence", f"presence:{_s(d.get('session_id'))}", run, _s(d.get("state")),
                    None, "STATE_SNAPSHOT")
    return None


def _presence_states() -> frozenset[str]:
    from jaeger_ai.contract.presence import ACTIVITY_STATES
    return frozenset(str(x) for x in ACTIVITY_STATES)


def annotate(session_id: str, event: str, data: dict[str, Any], ts: float | None = None) -> dict[str, Any]:
    """Return ``data`` with ``data["trace"]`` set. Pure aside from per-run counters."""
    if not isinstance(data, dict) or isinstance(data.get("trace"), dict):
        return data
    try:
        info = classify(event, data)
    except Exception:  # noqa: BLE001 — annotation never blocks an event
        info = None
    if info is None or not info.get("span_id"):
        return data
    now = ts or time.time()
    rid = _s(data.get("request_id") or data.get("run_id"))
    duration = _mark(info["span_id"], info["state"], now)
    if duration is None and info["state"] in TERMINAL_STATES:
        if isinstance(data.get("duration_ms"), (int, float)):
            duration = int(data["duration_ms"])
        elif isinstance(data.get("elapsed_s"), (int, float)):
            duration = int(float(data["elapsed_s"]) * 1000)
    trace = {"v": VERSION, "run_id": rid or None, "turn_id": _s(data.get("turn_id")) or None,
             **info, "seq": _bump(rid) if rid else None, "ts": now, "duration_ms": duration,
             "trace_id": _w3c_trace_id(rid)}
    return {**data, "trace": trace}


def history_trace(event: str, data: dict[str, Any], ts: float,
                  starts: dict[str, float]) -> dict[str, Any] | None:
    """Trace for a durable history row (pure: no global counters).

    ``starts`` is the caller's span-start map for the page being rebuilt, so
    replaying older turns yields the same spans and durations as live.
    """
    try:
        info = classify(event, data)
    except Exception:  # noqa: BLE001
        return None
    if not info or not info.get("span_id"):
        return None
    span, state = info["span_id"], info["state"]
    duration = None
    if state in ACTIVE_STATES:
        starts.setdefault(span, ts)
    elif state in TERMINAL_STATES:
        if span in starts:
            duration = int((ts - starts.pop(span)) * 1000)
        elif isinstance(data.get("duration_ms"), (int, float)):
            duration = int(data["duration_ms"])
        elif isinstance(data.get("elapsed_s"), (int, float)):
            duration = int(float(data["elapsed_s"]) * 1000)
    rid = _s(data.get("request_id") or data.get("run_id"))
    return {"v": VERSION, "run_id": rid or None, "turn_id": _s(data.get("turn_id")) or None,
            **info, "seq": None, "ts": ts, "duration_ms": duration, "trace_id": _w3c_trace_id(rid)}


def split_record(record: dict[str, Any]) -> dict[str, Any]:
    """Move a stored ``data["trace"]`` to the record's top-level ``trace``."""
    data = record.get("data")
    if isinstance(data, dict) and isinstance(data.get("trace"), dict):
        data = dict(data)
        record = {**record, "data": data, "trace": data.pop("trace")}
    return record
