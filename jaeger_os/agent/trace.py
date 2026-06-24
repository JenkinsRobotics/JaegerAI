"""trace.py — pipeline tracing for the agent turn.

Emits one ``TraceStep`` on the bus per step of a turn (``input`` ->
``tool``... -> ``think`` -> ``answer``) as the turn runs, so a Studio
panel can follow the flow live; a recorder persists every step to
``logs/trace.jsonl`` for the historic baseline. Flow + timings only —
no model reasoning text.

Zero hot-path cost: an emit is a bus ``put_nowait`` (the InProcBus
delivery thread fans out), and the recorder's file append runs on that
delivery thread — never the turn thread. Emits are best-effort and never
raise into a turn.

ponytail: one global Tracer holds the current turn's id / seq / clock.
Turns are serialized by the ``llm_lock``, so only one turn is ever live.
Upgrade to a per-turn handle if concurrent multi-session turns land.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

_MAX_DETAIL = 200  # cap the input/output preview kept per step


def _clip(s: Any, n: int = _MAX_DETAIL) -> str:
    t = "" if s is None else str(s)
    t = " ".join(t.split())  # collapse newlines / runs of whitespace
    return t if len(t) <= n else t[: n - 1] + "…"


# ── emit side: the live Tracer ──────────────────────────────────────
class Tracer:
    """Holds the current turn's id + clock; publishes TraceStep events."""

    def __init__(self) -> None:
        self._turn_id = 0
        self._seq = 0
        self._t0 = 0.0
        self._session = ""

    def begin(self, session: str, user_text: str) -> int:
        self._turn_id += 1
        self._seq = 0
        self._t0 = time.perf_counter()
        self._session = session or ""
        self._emit("input", "", 0.0, 0.0, True, user_text)
        return self._turn_id

    def step(self, kind: str, name: str = "", dur_s: float = 0.0,
             ok: bool = True, detail: Any = "") -> None:
        self._emit(kind, name, self._offset(), float(dur_s or 0.0), ok, detail)

    def end(self, answer: str, total_s: float, ok: bool = True) -> None:
        # The terminal ``answer`` step carries the whole turn's wall time.
        self._emit("answer", "", self._offset(), float(total_s or 0.0), ok, answer)

    def _offset(self) -> float:
        return max(0.0, time.perf_counter() - self._t0) if self._t0 else 0.0

    def _emit(self, kind: str, name: str, t_offset_s: float,
              dur_s: float, ok: bool, detail: Any) -> None:
        self._seq += 1
        try:
            from jaeger_os.nodes import runtime
            from jaeger_os.transport import topics
            runtime.get_bus().publish(topics.TraceStep(
                turn_id=self._turn_id, step_seq=self._seq, kind=kind,
                name=name or "", t_offset_s=round(t_offset_s, 4),
                dur_s=round(dur_s, 4), ok=bool(ok),
                detail=_clip(detail), session=self._session,
            ))
        except Exception:  # noqa: BLE001 — tracing never breaks a turn
            pass


_tracer = Tracer()


def trace_begin(session: str, user_text: str) -> int:
    return _tracer.begin(session, user_text)


def trace_step(kind: str, name: str = "", dur_s: float = 0.0,
               ok: bool = True, detail: Any = "") -> None:
    _tracer.step(kind, name, dur_s, ok, detail)


def trace_end(answer: str, total_s: float, ok: bool = True) -> None:
    _tracer.end(answer, total_s, ok)


# ── record side: persist the bus stream to logs/trace.jsonl ──────────
class TraceRecorder:
    """Subscribes to ``SENSE_TRACE_STEP`` and appends each step to
    ``trace.jsonl``. Runs on the bus delivery thread — off the turn."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def on_step(self, msg: Any) -> None:
        row = {
            "turn_id": getattr(msg, "turn_id", 0),
            "seq": getattr(msg, "step_seq", 0),
            "kind": getattr(msg, "kind", ""),
            "name": getattr(msg, "name", ""),
            "t_offset_s": getattr(msg, "t_offset_s", 0.0),
            "dur_s": getattr(msg, "dur_s", 0.0),
            "ok": getattr(msg, "ok", True),
            "detail": getattr(msg, "detail", ""),
            "session": getattr(msg, "session", ""),
            "ts_ns": getattr(msg, "t_emit_ns", 0),
        }
        line = json.dumps(row, ensure_ascii=False, default=str)
        try:
            with self._lock, self.path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except Exception:  # noqa: BLE001
            pass


_recorder_started = False
_recorder_lock = threading.Lock()


def start_trace_recorder(layout: Any) -> "TraceRecorder | None":
    """Wire a TraceRecorder onto the brain bus (idempotent). Call once at
    boot where the InstanceLayout is available."""
    global _recorder_started
    with _recorder_lock:
        if _recorder_started:
            return None
        try:
            from jaeger_os.nodes import runtime
            from jaeger_os.transport import topics
            rec = TraceRecorder(layout.logs_dir / "trace.jsonl")
            runtime.get_bus().subscribe(topics.SENSE_TRACE_STEP, rec.on_step)
            _recorder_started = True
            return rec
        except Exception:  # noqa: BLE001
            return None


# ── read side: timeline + baseline over trace.jsonl ─────────────────
def read_steps(path: Path) -> list[dict]:
    p = Path(path)
    if not p.exists():
        return []
    out: list[dict] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def turns(steps: list[dict]) -> dict[int, list[dict]]:
    by: dict[int, list[dict]] = {}
    for s in steps:
        by.setdefault(int(s.get("turn_id", 0)), []).append(s)
    for v in by.values():
        v.sort(key=lambda s: int(s.get("seq", 0)))
    return by


def _avg(xs: list[float]) -> float:
    return round(sum(xs) / len(xs), 4) if xs else 0.0


def _pct(xs: list[float], q: float) -> float:
    if not xs:
        return 0.0
    s = sorted(xs)
    return round(s[min(len(s) - 1, int(round(q * (len(s) - 1))))], 4)


def baseline(path: Path) -> dict:
    """Aggregate trace.jsonl into a performance baseline."""
    by = turns(read_steps(path))
    totals: list[float] = []
    think_times: list[float] = []
    tool_calls = 0
    per_tool: dict[str, list[float]] = {}
    for ss in by.values():
        ans = [s for s in ss if s.get("kind") == "answer"]
        if ans:
            totals.append(float(ans[-1].get("dur_s", 0.0)))
        think_times.append(
            sum(float(s.get("dur_s", 0.0)) for s in ss if s.get("kind") == "think"))
        for s in ss:
            if s.get("kind") == "tool":
                tool_calls += 1
                per_tool.setdefault(s.get("name") or "?", []).append(
                    float(s.get("dur_s", 0.0)))
    return {
        "turns": len(by),
        "total_s": {"avg": _avg(totals), "p50": _pct(totals, 0.5),
                    "p95": _pct(totals, 0.95)},
        "think_s": {"avg": _avg(think_times)},
        "tool_calls": tool_calls,
        "tools": {n: {"calls": len(v), "avg_s": _avg(v), "total_s": round(sum(v), 4)}
                  for n, v in sorted(per_tool.items(), key=lambda kv: -sum(kv[1]))},
    }


def format_timeline(ss: list[dict]) -> str:
    rows = []
    for s in ss:
        bad = "" if s.get("ok", True) else " !"
        nm = (" " + s["name"]) if s.get("name") else ""
        det = ("  " + s["detail"]) if s.get("detail") else ""
        rows.append(
            f"  +{float(s.get('t_offset_s', 0)):5.1f}s  "
            f"{str(s.get('kind', '')):<7}{nm:<14}"
            f"{float(s.get('dur_s', 0)):6.2f}s{bad}{det}")
    return "\n".join(rows)


def _default_trace_path() -> Path:
    from jaeger_os.core.instance.instance import (
        InstanceLayout, default_instance_name, resolve_instance_dir)
    layout = InstanceLayout(root=resolve_instance_dir(default_instance_name()))
    return layout.logs_dir / "trace.jsonl"


def _main(argv: list[str]) -> int:
    flags = [a for a in argv if a.startswith("-")]
    rest = [a for a in argv if not a.startswith("-")]
    path = Path(rest[0]) if rest else _default_trace_path()
    by = turns(read_steps(path))
    if not by:
        print(f"no trace data at {path}")
        return 0
    if "--last" in flags:
        tid = max(by)
        n_tools = len([s for s in by[tid] if s.get("kind") == "tool"])
        print(f"turn #{tid}  ({n_tools} tool call{'s' * (n_tools != 1)})")
        print(format_timeline(by[tid]))
        return 0
    print(json.dumps(baseline(path), indent=2))
    return 0


if __name__ == "__main__":
    import sys
    raise SystemExit(_main(sys.argv[1:]))
