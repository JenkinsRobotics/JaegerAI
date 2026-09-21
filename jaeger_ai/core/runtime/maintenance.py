"""Idle self-maintenance coordinator (PRODUCTION OS SPEC Parts 23–27).

Runs in an isolated git worktree. Never modifies the running resident tree.
Never merges to master.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
from pathlib import Path
import subprocess
import time
from typing import Any

from jaeger_ai.core.entity.events import EventType, JaegerEvent

logger = logging.getLogger("jaeger.runtime.maintenance")

PROTECTED_PATH_MARKERS = (
    "authority",
    "permissions",
    "effect",
    "credential",
    "autostart",
    "verification",
    "release",
    "merge",
)
MAX_REPAIR_ATTEMPTS = 3


@dataclass
class MaintenanceResult:
    item_id: str
    status: str
    worktree: str | None = None
    branch: str | None = None
    commit: str | None = None
    diagnostics: str = ""


class MaintenanceCoordinator:
    def __init__(self, repo_root: Path, event_store: Any | None = None) -> None:
        self.repo_root = Path(repo_root)
        self.event_store = event_store
        self._attempts: dict[str, int] = {}

    def _emit(self, event_type: str, payload: dict[str, Any]) -> None:
        if self.event_store is None:
            return
        try:
            self.event_store.append(
                JaegerEvent(
                    event_id="",
                    event_type=event_type,
                    actor="system:maintenance",
                    source="maintenance",
                    timestamp=time.time(),
                    payload=payload,
                    salience=0.4,
                )
            )
        except Exception:
            logger.debug("maintenance event skipped", exc_info=True)

    def select_item(self, backlog: list[dict[str, Any]]) -> dict[str, Any] | None:
        for item in backlog:
            item_id = str(item.get("id") or item.get("title") or "")
            if self._attempts.get(item_id, 0) >= MAX_REPAIR_ATTEMPTS:
                continue
            path = str(item.get("path") or "")
            if any(m in path.lower() for m in PROTECTED_PATH_MARKERS):
                continue
            return item
        return None

    def open_worktree(self, item_id: str) -> tuple[Path, str]:
        ts = time.strftime("%Y%m%dT%H%M%S")
        slug = "".join(ch if ch.isalnum() else "-" for ch in item_id)[:40].strip("-") or "task"
        branch = f"jaeger-maint/{ts}-{slug}"
        worktree = self.repo_root.parent / f"jaeger-maint-{ts}-{slug}"
        subprocess.run(
            ["git", "worktree", "add", "-b", branch, str(worktree)],
            cwd=self.repo_root,
            check=True,
            capture_output=True,
            text=True,
        )
        return worktree, branch

    def run_cycle(self, item: dict[str, Any], *, dry_run: bool = True) -> MaintenanceResult:
        item_id = str(item.get("id") or item.get("title") or "item")
        self._attempts[item_id] = self._attempts.get(item_id, 0) + 1
        self._emit(EventType.MAINTENANCE_STARTED.value, {"item_id": item_id, "attempt": self._attempts[item_id]})
        if dry_run:
            result = MaintenanceResult(
                item_id=item_id,
                status="BLOCKED" if self._attempts[item_id] >= MAX_REPAIR_ATTEMPTS else "candidate",
                diagnostics="dry_run: isolated worktree not created",
            )
            self._emit(EventType.MAINTENANCE_COMPLETED.value, {"item_id": item_id, "status": result.status})
            return result
        try:
            worktree, branch = self.open_worktree(item_id)
        except Exception as exc:
            status = "BLOCKED" if self._attempts[item_id] >= MAX_REPAIR_ATTEMPTS else "FAILED"
            result = MaintenanceResult(item_id=item_id, status=status, diagnostics=str(exc))
            self._emit(EventType.MAINTENANCE_COMPLETED.value, {"item_id": item_id, "status": status, "error": str(exc)})
            return result
        result = MaintenanceResult(
            item_id=item_id,
            status="candidate",
            worktree=str(worktree),
            branch=branch,
            diagnostics="worktree created; tests not yet executed",
        )
        self._emit(
            EventType.MAINTENANCE_COMPLETED.value,
            {"item_id": item_id, "status": result.status, "branch": branch, "worktree": str(worktree)},
        )
        return result
