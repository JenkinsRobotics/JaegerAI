"""Trajectory accumulation and JSONL export for Atropos.

Every conversation generates training data; wire it on day one so we
have months of history when we want to fine-tune.

This module ships the minimum viable shape: an in-memory
:class:`Trajectory` that callers append events to during a session, and
a JSONL writer that lands the events under ``data/trajectories/`` at
session end. The on-disk format is one JSON object per line, each
self-describing (``kind``, ``timestamp``, ``actor``, ``payload``), so
the format is forward-compatible — Atropos's own schema can be reached
by adapting the per-line objects without breaking older trajectories.

Subagent contributions are tagged via the ``actor`` field. When a
research subagent runs a tool, the trajectory carries that fact through
to the export — useful when the eventual fine-tuning pass wants to
weigh main-agent vs. subagent reasoning differently.

# PORTABILITY: Layer 1. The export sink is a directory path; the caller
# (the runtime launcher) decides where that path lives. On a desktop
# it lands under the working directory; inside JROS it can land on the
# robot's persistent volume.
"""

from __future__ import annotations

import datetime as _dt
import json
import pathlib
import re
import threading
import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any, Literal


EventKind = Literal[
    "user_message",
    "assistant_message",
    "tool_invocation",
    "system",
    "marker",
]
"""Allowed values of :attr:`TrajectoryEvent.kind`. Adding a new kind is
a forward-compatible change; consumers must handle unknown kinds
gracefully."""


VALID_KINDS: tuple[EventKind, ...] = (
    "user_message",
    "assistant_message",
    "tool_invocation",
    "system",
    "marker",
)


# --- Helpers ---------------------------------------------------------------


def _utc_now() -> str:
    return _dt.datetime.now(tz=_dt.timezone.utc).isoformat()


def _new_session_id() -> str:
    """Short, sortable id used in filenames and event records."""
    return uuid.uuid4().hex[:12]


_FILENAME_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


def _filename_safe(text: str) -> str:
    """Slugify a string for safe inclusion in a filename."""
    return _FILENAME_SAFE.sub("_", text).strip("_") or "session"


# --- Event ----------------------------------------------------------------


@dataclass(frozen=True)
class TrajectoryEvent:
    """One event in the conversation trajectory.

    Attributes:
        kind: ``user_message`` / ``assistant_message`` / ``tool_invocation``
            / ``system`` / ``marker``. Other consumers should treat
            unknown kinds as opaque.
        timestamp: ISO-8601 UTC timestamp at append time.
        actor: ``"main"`` for the top-level agent, ``"subagent:<name>"``
            for a Hermes subagent.
        payload: Free-form, kind-specific. JSON-serializable.
    """

    kind: EventKind
    timestamp: str
    actor: str
    payload: dict[str, Any]

    def to_jsonl(self) -> str:
        """Serialize to a single JSON line (no trailing newline)."""
        return json.dumps(
            {
                "kind": self.kind,
                "timestamp": self.timestamp,
                "actor": self.actor,
                "payload": self.payload,
            },
            ensure_ascii=False,
            sort_keys=True,
        )


# --- Trajectory -----------------------------------------------------------


@dataclass
class Trajectory:
    """Accumulates events for one session and writes them out at the end.

    Thread-safe: the lock around mutation lets subagents append from
    other threads without racing the main agent.

    Attributes:
        session_id: Unique within the destination directory.
        started_at: ISO-8601 UTC timestamp of session start.
        events: Append-only event log. Use ``record_*`` helpers to
            extend; do not mutate directly.
    """

    session_id: str = field(default_factory=_new_session_id)
    started_at: str = field(default_factory=_utc_now)
    events: list[TrajectoryEvent] = field(default_factory=list, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    # ---- Append helpers -------------------------------------------------

    def _record(
        self,
        kind: EventKind,
        payload: dict[str, Any],
        *,
        actor: str = "main",
    ) -> TrajectoryEvent:
        if kind not in VALID_KINDS:
            raise ValueError(f"unknown event kind: {kind!r}")
        event = TrajectoryEvent(
            kind=kind,
            timestamp=_utc_now(),
            actor=actor,
            payload=payload,
        )
        with self._lock:
            self.events.append(event)
        return event

    def record_user_message(self, text: str) -> TrajectoryEvent:
        """Append a user-said message."""
        return self._record("user_message", {"text": text})

    def record_assistant_message(
        self,
        text: str,
        *,
        actor: str = "main",
    ) -> TrajectoryEvent:
        """Append an assistant-said message (main agent or subagent)."""
        return self._record("assistant_message", {"text": text}, actor=actor)

    def record_tool_invocation(
        self,
        *,
        skill: str,
        operation: str,
        args: dict[str, Any] | None = None,
        result: Any = None,
        ok: bool,
        error: str | None = None,
        duration_ms: int | None = None,
        actor: str = "main",
    ) -> TrajectoryEvent:
        """Append a tool call result.

        ``args`` and ``result`` must be JSON-serializable. The export is
        plain-text JSONL on disk, so secrets (API keys, tokens, auth
        headers) are scrubbed here via :mod:`jaeger_os.core.safety.redact`
        before anything is written.
        """
        from jaeger_os.core.safety.redact import redact_obj, redact_text
        payload: dict[str, Any] = {
            "skill": skill,
            "operation": operation,
            "args": redact_obj(args or {}),
            "ok": ok,
        }
        if result is not None:
            payload["result"] = redact_obj(result)
        if error is not None:
            payload["error"] = redact_text(error)
        if duration_ms is not None:
            payload["duration_ms"] = duration_ms
        return self._record("tool_invocation", payload, actor=actor)

    def record_system(self, text: str) -> TrajectoryEvent:
        """Append a system-prompt-style note (e.g. session opening prompt)."""
        return self._record("system", {"text": text})

    def record_marker(self, label: str, **extra: Any) -> TrajectoryEvent:
        """Append a free-form marker. Useful for session breaks, retries, etc."""
        payload: dict[str, Any] = {"label": label}
        payload.update(extra)
        return self._record("marker", payload)

    # ---- Inspection -----------------------------------------------------

    def __len__(self) -> int:
        return len(self.events)

    def __iter__(self) -> Iterable[TrajectoryEvent]:
        return iter(self.events)

    # ---- Export ---------------------------------------------------------

    def export(self, destination_dir: pathlib.Path | str) -> pathlib.Path:
        """Write the trajectory to ``destination_dir`` as JSONL.

        Filename: ``trajectory-<started_at_slug>-<session_id>.jsonl``.
        The directory is created if it doesn't exist. Returns the path
        written. Idempotent if the file already exists *and* has the
        same content; otherwise raises :class:`FileExistsError` to avoid
        silent overwrite (use ``destination_dir`` per-session if that's
        a problem).
        """
        out_dir = pathlib.Path(destination_dir).expanduser()
        out_dir.mkdir(parents=True, exist_ok=True)
        slug = _filename_safe(self.started_at)
        path = out_dir / f"trajectory-{slug}-{self.session_id}.jsonl"

        # Render under the lock so concurrent appends don't slip in
        # between events.
        with self._lock:
            lines = [event.to_jsonl() for event in self.events]
        new_content = "\n".join(lines) + ("\n" if lines else "")

        if path.exists():
            existing = path.read_text(encoding="utf-8")
            if existing == new_content:
                return path
            raise FileExistsError(
                f"refusing to overwrite existing trajectory at {path}"
            )

        path.write_text(new_content, encoding="utf-8")
        return path


# --- Read-back (for tests and downstream tooling) ---------------------------


def load_trajectory_jsonl(path: pathlib.Path) -> list[TrajectoryEvent]:
    """Read a trajectory file back into a list of events.

    The reverse of :meth:`Trajectory.export`. Useful in tests and in any
    downstream tooling that wants to scan trajectory archives. Skips
    blank lines.
    """
    events: list[TrajectoryEvent] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        record = json.loads(line)
        events.append(
            TrajectoryEvent(
                kind=record["kind"],
                timestamp=record["timestamp"],
                actor=record["actor"],
                payload=record["payload"],
            )
        )
    return events


__all__ = [
    "EventKind",
    "Trajectory",
    "TrajectoryEvent",
    "VALID_KINDS",
    "load_trajectory_jsonl",
]
