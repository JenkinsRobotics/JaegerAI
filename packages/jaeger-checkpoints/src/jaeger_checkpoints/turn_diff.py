"""In-memory per-turn unified diff tracker (Codex turn_diff_tracker pattern).

Computes live unified diffs directly from committed file edits during a turn
with zero workspace re-reads, tracking baseline vs. current state and renames.
"""
from __future__ import annotations

import difflib
import threading
from dataclasses import dataclass


@dataclass
class _FileState:
    origin_path: str
    baseline: str | None  # None when newly created during this turn
    current: str | None   # None when deleted during this turn
    revision: int = 0


class TurnDiffTracker:
    """Tracks net per-turn file deltas in memory for instant UI diff streaming."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._files: dict[str, _FileState] = {}
        self._cache: dict[tuple[str, int], str] = {}

    def record_edit(
        self,
        path: str,
        *,
        before: str | None,
        after: str | None,
        renamed_from: str | None = None,
    ) -> None:
        """Record one committed file edit/create/delete/rename."""
        with self._lock:
            origin = path
            baseline = before
            if renamed_from and renamed_from in self._files:
                prev = self._files.pop(renamed_from)
                origin = prev.origin_path
                baseline = prev.baseline
            existing = self._files.get(path)
            if existing is None:
                self._files[path] = _FileState(origin_path=origin, baseline=baseline, current=after, revision=1)
            else:
                existing.current = after
                existing.revision += 1
            self._cache = {k: v for k, v in self._cache.items() if k[0] != path}

    def changed_files(self) -> list[str]:
        with self._lock:
            return sorted(
                path for path, st in self._files.items()
                if st.baseline != st.current or st.origin_path != path
            )

    def file_diff(self, path: str) -> str:
        with self._lock:
            st = self._files.get(path)
            if st is None or (st.baseline == st.current and st.origin_path == path):
                return ""
            key = (path, st.revision)
            cached = self._cache.get(key)
            if cached is not None:
                return cached
            from_lines = (st.baseline or "").splitlines(keepends=True)
            to_lines = (st.current or "").splitlines(keepends=True)
            fromfile = "/dev/null" if st.baseline is None else f"a/{st.origin_path}"
            tofile = "/dev/null" if st.current is None else f"b/{path}"
            rendered = "".join(difflib.unified_diff(from_lines, to_lines, fromfile=fromfile, tofile=tofile))
            self._cache[key] = rendered
            return rendered

    def unified_diff(self) -> str:
        with self._lock:
            parts = [d for path in self.changed_files() if (d := self.file_diff(path))]
            return "\n".join(parts)

    def reset(self) -> None:
        with self._lock:
            self._files.clear()
            self._cache.clear()


__all__ = ["TurnDiffTracker"]
