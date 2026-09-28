"""Tier 3 sensory perception: lightweight workspace/host observation.

The bus never opens repository state and never runs the model on the event
loop.  It produces debounced, classified sensor actions for the already
lease-gated :class:`BackgroundProducers` owner.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
from collections import deque
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jaeger_ai.core.instance.hardware_bench import DISK_LOW_GB

from .salience import SalienceClassifier, SalienceLevel

DEFAULT_SENSOR_DEBOUNCE_S = 8.0
DEFAULT_SENSOR_INTERVAL_S = 5.0
BATTERY_LOW_PERCENT = 20.0
_SKIPPED_DIRS = {
    ".git", ".hg", ".svn", "__pycache__", ".mypy_cache", ".ruff_cache",
    ".venv", "node_modules", ".DS_Store",
}
_FAILED_LOG_RE = re.compile(r"(?i)\b(failed|error)\b")


@dataclass(frozen=True, slots=True)
class SensorEvent:
    """A normalized observation. ``details`` is small and redacts nothing."""

    source: str
    kind: str
    summary: str
    details: dict[str, Any]
    timestamp: float

    @property
    def identity(self) -> str:
        """Stable identity for deduplication and request replay."""
        payload = {
            "source": self.source,
            "kind": self.kind,
            "summary": self.summary,
            "details": self.details,
        }
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


ModelClassifier = Callable[[SensorEvent], SalienceLevel]
JournalSink = Callable[[SensorEvent], None]


def event_identity(event: SensorEvent) -> str:
    return event.identity


def sensor_prompt(event: SensorEvent) -> str:
    """The one proactive prompt shape. Never expose raw long logs."""
    compact = json.dumps(event.details, sort_keys=True, default=str)[:1200]
    return (
        "A Jaeger Tier 3 sensor produced a high-salience observation.\n\n"
        f"Source: {event.source}\nKind: {event.kind}\nSummary: {event.summary}\n"
        f"Details: {compact}\n\n"
        "Investigate the relevant context and answer with one concise, "
        "operator-facing result. Do not take destructive action."
    )


def _should_skip(path: Path) -> bool:
    return any(part in _SKIPPED_DIRS for part in path.parts)


class _NoWorkspaceObserver:
    """Disable workspace observation when no workspace is configured."""

    root = Path("")

    def poll(self, _now: float) -> list[SensorEvent]:
        return []


class WorkspaceObserver:
    """Poll a bounded workspace and debounce material changes."""

    def __init__(self, root: str | os.PathLike[str], *, debounce_s: float) -> None:
        self.root = Path(root).expanduser()
        self.debounce_s = max(0.05, float(debounce_s))
        self._snapshots: dict[Path, tuple[float, int]] = {}
        self._last_emit: dict[str, float] = {}
        self._head_ref: str | None = None
        self._failed_fingerprint: str | None = None
        self._failed_logs: dict[str, str] = {}
        self._seeded = False

    def poll(self, now: float) -> list[SensorEvent]:
        if not self.root.exists():
            return []
        current: dict[Path, tuple[float, int]] = {}
        failures: dict[str, Any] = {}
        failed_logs: list[Path] = []
        for path in self._files():
            try:
                stat = path.stat()
            except OSError:
                continue
            current[path] = (stat.st_mtime_ns, stat.st_size)
            name = path.name
            if (name == "lastfailed" and path.parent.name == "cache"
                    and path.parent.parent.name == "v"
                    and path.parent.parent.parent.name == ".pytest_cache"):
                try:
                    payload = json.loads(path.read_text(encoding="utf-8") or "{}")
                    if isinstance(payload, dict) and payload:
                        failures = payload
                except Exception:  # noqa: BLE001
                    failures = {"parse_error": True}
            elif path.suffix == ".log" and "test" in path.name.lower():
                try:
                    if _FAILED_LOG_RE.search(path.read_text(encoding="utf-8", errors="ignore")[:20000]):
                        failed_logs.append(path)
                except OSError:
                    pass

        events: list[SensorEvent] = []
        for path in failed_logs:
            try:
                fingerprint = hashlib.sha256(
                    path.read_bytes()[:20000],
                ).hexdigest()
            except OSError:
                continue
            previous = self._failed_logs.get(str(path))
            self._failed_logs[str(path)] = fingerprint
            if self._seeded and previous != fingerprint:
                event = SensorEvent(
                    source="workspace", kind="test_failed",
                    summary=f"Test log reports failure: {path.relative_to(self.root)}",
                    details={"path": str(path.relative_to(self.root))},
                    timestamp=now,
                )
                if self._debounce(event.identity, now):
                    events.append(event)
        fingerprint = json.dumps(failures or {}, sort_keys=True, default=str)
        if self._seeded and failures and fingerprint != self._failed_fingerprint:
            event = SensorEvent(
                source="workspace", kind="test_failed",
                summary=f"{len(failures)} pytest test(s) failed",
                details={"tests": list(failures)[:20], "fingerprint": fingerprint},
                timestamp=now,
            )
            if self._debounce(event.identity, now):
                events.append(event)
            self._failed_fingerprint = fingerprint
        elif failures:
            self._failed_fingerprint = fingerprint
        elif self._seeded and self._failed_fingerprint not in (None, "{}"):
            events.append(SensorEvent(
                source="workspace", kind="test_passed",
                summary="Previously failed pytest tests now pass",
                details={"fingerprint": "{}"}, timestamp=now,
            ))
            self._failed_fingerprint = "{}"
        else:
            self._failed_fingerprint = "{}"

        if self._seeded:
            for path, old in sorted(self._snapshots.items()):
                new = current.get(path)
                if new == old:
                    continue
                relative = str(path.relative_to(self.root))
                kind = "file_removed" if new is None else "file_changed"
                event = SensorEvent(
                    source="workspace", kind=kind,
                    summary=f"Workspace {kind.replace('_', ' ')}: {relative}",
                    details={"path": relative, **({"size": new[1]} if new else {})},
                    timestamp=now,
                )
                if self._debounce(event.identity, now):
                    events.append(event)
            for path, value in current.items():
                if path in self._snapshots:
                    continue
                relative = str(path.relative_to(self.root))
                event = SensorEvent(
                    source="workspace", kind="file_added",
                    summary=f"Workspace file added: {relative}",
                    details={"path": relative, "size": value[1]},
                    timestamp=now,
                )
                if self._debounce(event.identity, now):
                    events.append(event)
        self._snapshots = current
        self._seeded = True

        head = self._read_head()
        if self._seeded and bool(head) and self._head_ref and head != self._head_ref:
            event = SensorEvent(
                source="workspace", kind="branch_changed",
                summary=f"Git branch changed to {head}",
                details={"from": self._head_ref, "to": head},
                timestamp=now,
            )
            if self._debounce(event.identity, now):
                events.append(event)
        self._head_ref = head
        return events[:16]

    def _files(self) -> Iterable[Path]:
        for directory, dirs, files in os.walk(self.root, topdown=True):
            depth = len(Path(directory).relative_to(self.root).parts)
            if depth >= 3:
                dirs[:] = []
            dirs[:] = sorted(d for d in dirs if d not in _SKIPPED_DIRS)[:64]
            for name in sorted(files)[:256]:
                path = Path(directory) / name
                if not _should_skip(path.relative_to(self.root)):
                    yield path

    def _debounce(self, identity: str, now: float) -> bool:
        last = self._last_emit.get(identity, float("-inf"))
        if now - last < self.debounce_s:
            return False
        self._last_emit[identity] = now
        if len(self._last_emit) > 256:
            cutoff = now - self.debounce_s * 10
            self._last_emit = {
                key: stamp for key, stamp in self._last_emit.items() if stamp >= cutoff
            }
        return True

    def _read_head(self) -> str:
        git_head = self.root / ".git" / "HEAD"
        try:
            line = git_head.read_text(encoding="utf-8").strip()
        except OSError:
            return ""
        if line.startswith("ref: refs/heads/"):
            return line.removeprefix("ref: refs/heads/")
        return line[:12]


class HostTelemetryObserver:
    """Safe macOS host vitals, with transition-only alerting."""

    def __init__(
        self,
        *,
        telemetry: Callable[[], dict[str, Any]] | None = None,
    ) -> None:
        self.telemetry = telemetry or self._hardware_bench_vitals
        self._active: dict[str, str] = {}

    def poll(self, now: float) -> list[SensorEvent]:
        try:
            reading = dict(self.telemetry() or {})
        except Exception:  # noqa: BLE001
            return []
        disk_free = _number(reading.get("disk_free_gb"), 1000.0)
        pressure = int(_number(reading.get("memory_pressure_level"), 0))
        battery = _number(reading.get("battery_level"), None)
        events: list[SensorEvent] = []

        if disk_free < DISK_LOW_GB:
            event = self._transition(
                "disk_low", f"Disk free space is {disk_free:.1f} GB",
                {"disk_free_gb": disk_free, "threshold_gb": DISK_LOW_GB}, now,
            )
            if event is not None:
                events.append(event)
        else:
            self._clear("disk_low")

        if pressure >= 3:
            event = self._transition(
                "memory_pressure",
                f"Unified memory pressure is critical (level {pressure})",
                {"memory_pressure_level": pressure}, now,
            )
            if event is not None:
                events.append(event)
        else:
            self._clear("memory_pressure")

        if battery is not None and battery <= BATTERY_LOW_PERCENT:
            event = self._transition(
                "battery_low",
                f"Battery level is {battery:.0f}%",
                {"battery_level": battery}, now,
            )
            if event is not None:
                events.append(event)
        else:
            self._clear("battery_low")
        return events

    def _transition(
        self, key: str, summary: str, details: dict[str, Any], now: float,
    ) -> SensorEvent | None:
        if key in self._active:
            return None
        self._active[key] = summary
        return SensorEvent(
            source="host", kind=key, summary=summary,
            details={**details, "timestamp": now}, timestamp=now,
        )

    def _clear(self, key: str) -> None:
        self._active.pop(key, None)

    @staticmethod
    def _hardware_bench_vitals() -> dict[str, Any]:
        from jaeger_ai.core.instance.hardware_bench import snapshot
        return snapshot()


def _number(value: Any, default: float | None) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


@dataclass(slots=True)
class ClassifiedSensorEvent:
    event: SensorEvent
    level: SalienceLevel


class SensorBus:
    """Coordinates observers, classification, journals, and delivery queues."""

    def __init__(
        self,
        workspace_path: str | os.PathLike[str] | None,
        *,
        interval_s: float = DEFAULT_SENSOR_INTERVAL_S,
        debounce_s: float = DEFAULT_SENSOR_DEBOUNCE_S,
        telemetry: Callable[[], dict[str, Any]] | None = None,
        journal_sink: JournalSink | None = None,
        awake_model: str = "gemma4",
        model_evaluator: ModelClassifier | None = None,
    ) -> None:
        self.workspace = (
            WorkspaceObserver(workspace_path, debounce_s=debounce_s)
            if workspace_path and str(workspace_path).strip()
            else _NoWorkspaceObserver()
        )
        self.telemetry = HostTelemetryObserver(telemetry=telemetry)
        self.filter = SalienceClassifier(awake_model=awake_model, model_evaluator=model_evaluator)
        self.interval_s = max(1.0, float(interval_s))
        self._journal_sink = journal_sink
        self._immediate: deque[SensorEvent] = deque(maxlen=64)
        self._digests: deque[SensorEvent] = deque(maxlen=64)
        self._journals: deque[SensorEvent] = deque(maxlen=256)
        self._levels: dict[str, SalienceLevel] = {}
        self._lock = threading.RLock()
        self._poll_lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def started(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.started:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="sensor-bus", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=self.interval_s + 0.25)
        self._thread = None

    def poll_once(self) -> None:
        with self._poll_lock:
            now = time.time()
            events = [*self.workspace.poll(now), *self.telemetry.poll(now)]
            with self._lock:
                for event in events:
                    level = self.filter.classify(event)
                    self._levels[event.identity] = level
                    if len(self._levels) > 512:
                        for key in list(self._levels)[:256]:
                            self._levels.pop(key, None)
                    if level is SalienceLevel.NOISE:
                        continue
                    if level is SalienceLevel.JOURNAL:
                        self._record_journal(event)
                        self._journals.append(event)
                    elif level is SalienceLevel.DIGEST:
                        self._digests.append(event)
                    elif level is SalienceLevel.IMMEDIATE:
                        self._immediate.append(event)

    def next_action(
        self, *, user_active: bool | None = None,
    ) -> ClassifiedSensorEvent | None:
        """Pop one immediate action, or a digest only when operator is active."""
        with self._lock:
            event = self._immediate.popleft() if self._immediate else None
            if event is None and user_active is True and self._digests:
                event = self._digests.popleft()
            if event is None:
                return None
            return ClassifiedSensorEvent(event, self._levels.get(event.identity, SalienceLevel.JOURNAL))

    def pending_digests(self) -> list[SensorEvent]:
        with self._lock:
            return list(self._digests)

    def journals(self) -> list[SensorEvent]:
        with self._lock:
            return list(self._journals)

    def _run(self) -> None:
        while not self._stop.wait(self.interval_s):
            try:
                self.poll_once()
            except Exception:  # noqa: BLE001
                continue

    def _record_journal(self, event: SensorEvent) -> None:
        sink = self._journal_sink
        if sink is None:
            try:
                from jaeger_ai.core.entity.runtime import EntityRuntime
                EntityRuntime.get_singleton().submit_observation(
                    event.source, event.details, salience=0.2,
                )
            except Exception:  # noqa: BLE001
                return
        else:
            try:
                sink(event)
            except Exception:  # noqa: BLE001
                return


__all__ = [
    "DEFAULT_SENSOR_DEBOUNCE_S", "DEFAULT_SENSOR_INTERVAL_S",
    "DISK_LOW_GB", "HostTelemetryObserver", "SalienceClassifier",
    "SalienceLevel",
    "SensorBus", "SensorEvent", "WorkspaceObserver", "sensor_prompt",
]
