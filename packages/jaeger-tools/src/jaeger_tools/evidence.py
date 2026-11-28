"""Retained Evidence paging store for large tool outputs (REA MIT pattern).

Instead of truncating huge tool dumps or blowing up prompt context windows,
``RetainedEvidenceStore`` stores oversized outputs under a content-addressed
``ev_<hash>`` handle and returns a compact summary alongside paginated
``inspect(evidence_id, offset, limit)`` access. Pure stdlib.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import threading
import time
from typing import Any


@dataclass(frozen=True)
class RetainedSummary:
    evidence_id: str
    source_tool: str
    total_chars: int
    total_lines: int
    preview: str
    truncated: bool
    created_at: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class RetainedEvidenceStore:
    """Stores oversized tool outputs on disk/memory under ``ev_<id>`` for paginated reads."""

    def __init__(
        self,
        root_dir: Path | None = None,
        *,
        inline_threshold_chars: int = 8_000,
        preview_chars: int = 1_200,
        max_items: int = 120,
    ) -> None:
        self._root = Path(root_dir).expanduser().resolve() if root_dir is not None else None
        self._threshold = max(500, int(inline_threshold_chars))
        self._preview_chars = max(200, min(int(preview_chars), self._threshold))
        self._max_items = max(10, int(max_items))
        self._lock = threading.RLock()
        self._mem: dict[str, dict[str, Any]] = {}
        self._order: list[str] = []

    @property
    def threshold_chars(self) -> int:
        return self._threshold

    def retain(self, content: str, *, source_tool: str = "tool", metadata: dict[str, Any] | None = None) -> RetainedSummary:
        raw = str(content or "")
        digest = hashlib.sha256(f"{source_tool}\x00{raw}".encode("utf-8", errors="replace")).hexdigest()[:12]
        ev_id = f"ev_{digest}"
        now = time.time()
        lines = raw.splitlines()
        record = {
            "evidence_id": ev_id,
            "source_tool": source_tool,
            "content": raw,
            "total_chars": len(raw),
            "total_lines": len(lines),
            "metadata": dict(metadata or {}),
            "created_at": now,
        }
        with self._lock:
            self._mem[ev_id] = record
            if ev_id in self._order:
                self._order.remove(ev_id)
            self._order.append(ev_id)
            while len(self._order) > self._max_items:
                old = self._order.pop(0)
                self._mem.pop(old, None)
            if self._root is not None:
                self._root.mkdir(parents=True, exist_ok=True)
                (self._root / f"{ev_id}.json").write_text(
                    json.dumps(record, ensure_ascii=False),
                    encoding="utf-8",
                )
        return RetainedSummary(
            evidence_id=ev_id,
            source_tool=source_tool,
            total_chars=len(raw),
            total_lines=len(lines),
            preview=raw[: self._preview_chars],
            truncated=len(raw) > self._preview_chars,
            created_at=now,
        )

    def maybe_retain(self, content: str, *, source_tool: str = "tool") -> tuple[str, RetainedSummary | None]:
        """Return ``(content, None)`` if small, or ``(compact_notice, summary)`` if oversized."""
        raw = str(content or "")
        if len(raw) <= self._threshold:
            return raw, None
        summary = self.retain(raw, source_tool=source_tool)
        notice = (
            f"{summary.preview}\n\n"
            f"[Retained oversized output as {summary.evidence_id}: {summary.total_chars:,} chars / "
            f"{summary.total_lines:,} lines. Call `inspect_evidence(evidence_id='{summary.evidence_id}', "
            f"offset=..., limit=...)` to page through the full record.]"
        )
        return notice, summary

    def _load_record(self, evidence_id: str) -> dict[str, Any] | None:
        ev_id = (evidence_id or "").strip()
        if not ev_id.startswith("ev_") or len(ev_id) > 32:
            return None
        with self._lock:
            if ev_id in self._mem:
                return self._mem[ev_id]
        if self._root is not None:
            cand = (self._root / f"{ev_id}.json").resolve()
            if cand.parent == self._root and cand.is_file():
                try:
                    data = json.loads(cand.read_text(encoding="utf-8"))
                    if isinstance(data, dict):
                        with self._lock:
                            self._mem[ev_id] = data
                        return data
                except (OSError, json.JSONDecodeError):
                    return None
        return None

    def inspect(
        self,
        evidence_id: str,
        *,
        offset: int = 0,
        limit: int = 4000,
        search: str = "",
    ) -> dict[str, Any]:
        """Page through a retained evidence record by character offset or keyword filter."""
        rec = self._load_record(evidence_id)
        if rec is None:
            return {"ok": False, "error": f"retained evidence not found: {evidence_id}"}
        content = str(rec.get("content") or "")
        total = len(content)
        clean_search = (search or "").strip()
        if clean_search:
            matches: list[dict[str, Any]] = []
            low_q = clean_search.lower()
            for lineno, line in enumerate(content.splitlines(), start=1):
                if low_q in line.lower():
                    matches.append({"line": lineno, "text": line[:300]})
                    if len(matches) >= 50:
                        break
            return {
                "ok": True,
                "evidence_id": rec["evidence_id"],
                "source_tool": rec.get("source_tool", ""),
                "search": clean_search,
                "match_count": len(matches),
                "matches": matches,
            }

        start = max(0, min(int(offset or 0), total))
        cap = max(200, min(int(limit or 4000), 16_000))
        end = min(total, start + cap)
        return {
            "ok": True,
            "evidence_id": rec["evidence_id"],
            "source_tool": rec.get("source_tool", ""),
            "offset": start,
            "limit": cap,
            "end": end,
            "total_chars": total,
            "exhausted": end >= total,
            "text": content[start:end],
        }

    def list_recent(self, *, limit: int = 20) -> list[dict[str, Any]]:
        with self._lock:
            ids = list(reversed(self._order))[: max(1, int(limit))]
            return [
                {
                    "evidence_id": self._mem[i]["evidence_id"],
                    "source_tool": self._mem[i]["source_tool"],
                    "total_chars": self._mem[i]["total_chars"],
                    "total_lines": self._mem[i]["total_lines"],
                    "created_at": self._mem[i]["created_at"],
                }
                for i in ids
                if i in self._mem
            ]


__all__ = ["RetainedEvidenceStore", "RetainedSummary"]
