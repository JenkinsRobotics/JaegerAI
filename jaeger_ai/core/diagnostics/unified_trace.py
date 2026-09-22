"""Unified Observability and Provenance Tracing (Workstream 16).

Connects the full causal path:
human request
→ attention
→ executive decision
→ context compilation
→ provider/model invocation
→ proposed action
→ authority
→ effect
→ environment consequence
→ verification
→ learning

Guarantees:
1. Structured trace IDs correlating the entire execution path.
2. Useful diagnostics: model, provider, latency, tool calls, effects, verification, retries, approvals.
3. Strict redaction: credentials and API keys are never logged.
4. Operator inspection tooling: `render_inspection_tree()` and structured trace diagnosis.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
import logging
from pathlib import Path
import sqlite3
import time
from typing import Any
import uuid

from jaeger_ai.core.redaction import redact_value

logger = logging.getLogger("jaeger.core.diagnostics.trace")


@dataclass
class TraceSpan:
    """A granular phase in the end-to-end execution trace."""
    span_id: str = field(default_factory=lambda: f"sp_{uuid.uuid4().hex[:10]}")
    phase: str = "request"  # request, attention, executive, context_compiler, cognition, proposal, authority, effect, verification, learning
    started_at: float = field(default_factory=time.time)
    ended_at: float | None = None
    duration_ms: float = 0.0
    data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    def finish(self, error: str | None = None, extra_data: dict[str, Any] | None = None) -> None:
        self.ended_at = time.time()
        self.duration_ms = max(0.0, (self.ended_at - self.started_at) * 1000.0)
        if error:
            self.error = error
        if extra_data:
            self.data.update(extra_data)


@dataclass
class ExecutionTrace:
    """Canonical end-to-end trace uniting an entire turn's causal progression."""
    trace_id: str = field(default_factory=lambda: f"tr_{uuid.uuid4().hex[:12]}")
    request_id: str = ""
    session_id: str = "dispatcher"
    actor: str = "human:operator"
    goal: str = ""
    started_at: float = field(default_factory=time.time)
    completed_at: float | None = None
    total_latency_ms: float = 0.0
    model: str | None = None
    provider: str | None = None
    strategy: str | None = None
    spans: list[TraceSpan] = field(default_factory=list)
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    effects: list[dict[str, Any]] = field(default_factory=list)
    verification: dict[str, Any] | None = None
    status: str = "running"  # running, success, failed, rejected
    error: str | None = None

    def start_span(self, phase: str, initial_data: dict[str, Any] | None = None) -> TraceSpan:
        span = TraceSpan(
            phase=phase,
            started_at=time.time(),
            data=dict(initial_data or {}),
        )
        self.spans.append(span)
        return span

    def finish(self, status: str = "success", error: str | None = None) -> None:
        self.completed_at = time.time()
        self.total_latency_ms = max(0.0, (self.completed_at - self.started_at) * 1000.0)
        self.status = status
        self.error = error

    def to_dict(self) -> dict[str, Any]:
        raw = {
            "trace_id": self.trace_id,
            "request_id": self.request_id,
            "session_id": self.session_id,
            "actor": self.actor,
            "goal": self.goal,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "total_latency_ms": self.total_latency_ms,
            "model": self.model,
            "provider": self.provider,
            "strategy": self.strategy,
            "spans": [asdict(s) for s in self.spans],
            "tool_calls": self.tool_calls,
            "effects": self.effects,
            "verification": self.verification,
            "status": self.status,
            "error": self.error,
        }
        # Invariant: Never log or persist credentials/secrets
        return redact_value(raw)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ExecutionTrace:
        spans = [
            TraceSpan(
                span_id=s["span_id"],
                phase=s["phase"],
                started_at=s["started_at"],
                ended_at=s.get("ended_at"),
                duration_ms=s.get("duration_ms", 0.0),
                data=dict(s.get("data") or {}),
                error=s.get("error"),
            )
            for s in (data.get("spans") or [])
        ]
        return cls(
            trace_id=data["trace_id"],
            request_id=data.get("request_id", ""),
            session_id=data.get("session_id", "dispatcher"),
            actor=data.get("actor", "human:operator"),
            goal=data.get("goal", ""),
            started_at=data.get("started_at", time.time()),
            completed_at=data.get("completed_at"),
            total_latency_ms=data.get("total_latency_ms", 0.0),
            model=data.get("model"),
            provider=data.get("provider"),
            strategy=data.get("strategy"),
            spans=spans,
            tool_calls=list(data.get("tool_calls") or []),
            effects=list(data.get("effects") or []),
            verification=data.get("verification"),
            status=data.get("status", "running"),
            error=data.get("error"),
        )

    def render_inspection_tree(self) -> str:
        """Render a formatted human-readable inspection tree for operator diagnosis."""
        lines = [
            f"Execution Trace [{self.trace_id}] (Status: {self.status.upper()}, Latency: {self.total_latency_ms:.1f}ms)",
            f"├─ Request ID: {self.request_id} | Session: {self.session_id} | Actor: {self.actor}",
            f"├─ Model: {self.model or 'n/a'} (Provider: {self.provider or 'n/a'}, Strategy: {self.strategy or 'n/a'})",
            f"├─ Goal: {self.goal[:80] if self.goal else 'n/a'}",
            "├─ Causal Spans:",
        ]
        for i, s in enumerate(self.spans):
            prefix = "│  └─" if i == len(self.spans) - 1 else "│  ├─"
            err_str = f" [ERROR: {s.error}]" if s.error else ""
            lines.append(f"{prefix} [{s.phase.upper()}] {s.duration_ms:.1f}ms{err_str}")

        lines.append(f"├─ Tool Calls: {len(self.tool_calls)} | Effects Recorded: {len(self.effects)}")
        if self.verification:
            v_status = self.verification.get("status", "unverified")
            lines.append(f"└─ Verification: {v_status.upper()} (Verifier: {self.verification.get('verifier')})")
        else:
            lines.append("└─ Verification: None")

        if self.error:
            lines.append(f"   [DIAGNOSTIC FAILURE]: {self.error}")

        return "\n".join(lines)


class SqliteTraceStore:
    """Persistent storage for execution traces in <state_root>/execution_traces.sqlite3."""

    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        return conn

    def _init_db(self) -> None:
        with self._get_conn() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS execution_traces (
                    trace_id TEXT PRIMARY KEY,
                    request_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    trace_json TEXT NOT NULL,
                    created_at REAL NOT NULL
                );
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_traces_req ON execution_traces(request_id);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_traces_sess ON execution_traces(session_id);")

    def save_trace(self, trace: ExecutionTrace) -> None:
        payload = json.dumps(trace.to_dict())
        with self._get_conn() as conn:
            conn.execute(
                """
                INSERT INTO execution_traces (trace_id, request_id, session_id, status, trace_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(trace_id) DO UPDATE SET
                    status=excluded.status,
                    trace_json=excluded.trace_json
                """,
                (
                    trace.trace_id,
                    trace.request_id,
                    trace.session_id,
                    trace.status,
                    payload,
                    trace.started_at,
                ),
            )

    def get_trace(self, trace_id: str) -> ExecutionTrace | None:
        with self._get_conn() as conn:
            row = conn.execute("SELECT trace_json FROM execution_traces WHERE trace_id = ?", (trace_id,)).fetchone()
            if not row:
                return None
            return ExecutionTrace.from_dict(json.loads(row["trace_json"]))

    def get_by_request_id(self, request_id: str) -> ExecutionTrace | None:
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT trace_json FROM execution_traces WHERE request_id = ? ORDER BY created_at DESC LIMIT 1",
                (request_id,),
            ).fetchone()
            if not row:
                return None
            return ExecutionTrace.from_dict(json.loads(row["trace_json"]))

    def list_traces(self, limit: int = 20) -> list[ExecutionTrace]:
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT trace_json FROM execution_traces ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [ExecutionTrace.from_dict(json.loads(r["trace_json"])) for r in rows]
