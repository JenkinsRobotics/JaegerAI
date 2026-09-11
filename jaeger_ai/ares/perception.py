"""Continuous environment perception for ARES."""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class RepoStatus:
    is_git: bool = False
    branch: str = ""
    dirty_files_count: int = 0
    untracked_files_count: int = 0
    recent_commit: str = ""


@dataclass(frozen=True)
class SystemTelemetry:
    disk_free_gb: float = 0.0
    disk_total_gb: float = 0.0
    load_average: tuple[float, float, float] = (0.0, 0.0, 0.0)


@dataclass(frozen=True)
class OperatorState:
    idle_seconds: float = 0.0
    last_turn_ts: float = 0.0
    current_focus: str = ""


@dataclass(frozen=True)
class FinanceState:
    configured: bool = False
    unreviewed_count: int = 0
    anomalies_detected: bool = False
    net_worth_cached: float | None = None


@dataclass(frozen=True)
class PerceptionSnapshot:
    timestamp: float = field(default_factory=time.time)
    repo: RepoStatus = field(default_factory=RepoStatus)
    system: SystemTelemetry = field(default_factory=SystemTelemetry)
    operator: OperatorState = field(default_factory=OperatorState)
    finance: FinanceState = field(default_factory=FinanceState)
    active_alerts: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "repo": {
                "is_git": self.repo.is_git,
                "branch": self.repo.branch,
                "dirty_files": self.repo.dirty_files_count,
                "untracked_files": self.repo.untracked_files_count,
                "recent_commit": self.repo.recent_commit,
            },
            "system": {
                "disk_free_gb": self.system.disk_free_gb,
                "load_avg": list(self.system.load_average),
            },
            "operator": {
                "idle_seconds": round(self.operator.idle_seconds, 1),
                "current_focus": self.operator.current_focus,
            },
            "finance": {
                "configured": self.finance.configured,
                "unreviewed_count": self.finance.unreviewed_count,
                "anomalies_detected": self.finance.anomalies_detected,
            },
            "alerts": list(self.active_alerts),
        }


class SensorStream:
    """Collects environmental sensor signals asynchronously without blocking."""

    def __init__(self, workspace_root: Path | str | None = None) -> None:
        self.workspace_root = Path(workspace_root or os.getcwd()).resolve()
        self._last_user_activity_ts = time.time()

    def record_operator_activity(self, focus: str = "") -> None:
        """Called by bridge/chat when the operator interacts."""
        self._last_user_activity_ts = time.time()

    async def perceive(self) -> PerceptionSnapshot:
        """Gather passive telemetry across repo, system, operator, and finance."""
        repo = self._perceive_repo()
        system = self._perceive_system()
        operator = self._perceive_operator()
        finance = await self._perceive_finance()

        alerts: list[str] = []
        if repo.dirty_files_count > 15:
            alerts.append(f"High working-tree drift ({repo.dirty_files_count} dirty files)")
        if system.disk_free_gb < 5.0 and system.disk_total_gb > 0:
            alerts.append(f"Low disk space ({system.disk_free_gb:.1f} GB remaining)")
        if finance.anomalies_detected:
            alerts.append("Unreviewed financial transactions or pacing alerts detected")

        return PerceptionSnapshot(
            repo=repo,
            system=system,
            operator=operator,
            finance=finance,
            active_alerts=tuple(alerts),
        )

    def _perceive_repo(self) -> RepoStatus:
        git_dir = self.workspace_root / ".git"
        if not git_dir.exists():
            return RepoStatus(is_git=False)

        try:
            # Branch
            branch_proc = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=str(self.workspace_root),
                capture_output=True,
                text=True,
                timeout=2,
            )
            branch = branch_proc.stdout.strip() if branch_proc.returncode == 0 else "unknown"

            # Status short
            status_proc = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=str(self.workspace_root),
                capture_output=True,
                text=True,
                timeout=2,
            )
            dirty = 0
            untracked = 0
            if status_proc.returncode == 0:
                for line in status_proc.stdout.splitlines():
                    if line.startswith("??"):
                        untracked += 1
                    elif line.strip():
                        dirty += 1

            # Commit
            commit_proc = subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                cwd=str(self.workspace_root),
                capture_output=True,
                text=True,
                timeout=2,
            )
            commit = commit_proc.stdout.strip() if commit_proc.returncode == 0 else ""

            return RepoStatus(
                is_git=True,
                branch=branch,
                dirty_files_count=dirty,
                untracked_files_count=untracked,
                recent_commit=commit,
            )
        except Exception:
            return RepoStatus(is_git=True, branch="error")

    def _perceive_system(self) -> SystemTelemetry:
        try:
            usage = shutil.disk_usage(str(self.workspace_root))
            free_gb = round(usage.free / (1024**3), 2)
            total_gb = round(usage.total / (1024**3), 2)
        except Exception:
            free_gb, total_gb = 0.0, 0.0

        try:
            load_avg = os.getloadavg()
        except Exception:
            load_avg = (0.0, 0.0, 0.0)

        return SystemTelemetry(
            disk_free_gb=free_gb,
            disk_total_gb=total_gb,
            load_average=load_avg,
        )

    def _perceive_operator(self) -> OperatorState:
        idle = max(0.0, time.time() - self._last_user_activity_ts)
        return OperatorState(
            idle_seconds=idle,
            last_turn_ts=self._last_user_activity_ts,
            current_focus=str(self.workspace_root.name),
        )

    async def _perceive_finance(self) -> FinanceState:
        try:
            from jaeger_ai.features.finance.monarch_service import MonarchMoneyService
            svc = MonarchMoneyService()
            if not svc.is_configured():
                return FinanceState(configured=False)

            cached_report = Path(os.path.expanduser("~/.jaeger/reports/finance/latest.json"))
            if cached_report.exists():
                import json
                data = json.loads(cached_report.read_text(encoding="utf-8"))
                return FinanceState(
                    configured=True,
                    unreviewed_count=data.get("unreviewed_count", 0),
                    anomalies_detected=data.get("anomalies_count", 0) > 0,
                    net_worth_cached=data.get("net_worth"),
                )
            return FinanceState(configured=True)
        except Exception:
            return FinanceState(configured=False)
