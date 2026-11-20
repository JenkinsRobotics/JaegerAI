"""Structured result models for ``jaeger selftest`` (§6)."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
import json
from typing import Any


class CheckStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    SKIPPED = "SKIPPED"
    BLOCKED = "BLOCKED"


@dataclass
class CheckResult:
    id: str
    name: str
    status: CheckStatus
    required: bool = True
    elapsed_s: float = 0.0
    metrics: dict[str, Any] = field(default_factory=dict)
    evidence: dict[str, Any] = field(default_factory=dict)
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value
        return d


@dataclass
class SelftestReport:
    commit: str
    started_at: str
    finished_at: str
    checks: list[CheckResult] = field(default_factory=list)
    artifacts_dir: str = ""
    artifacts_cleaned: bool = True
    retention_policy: str = "isolated_temp_auto_cleanup_unless_keep_artifacts"

    @property
    def counts(self) -> dict[str, int]:
        out = {s.value: 0 for s in CheckStatus}
        for c in self.checks:
            out[c.status.value] = out.get(c.status.value, 0) + 1
        return out

    @property
    def required_failures(self) -> list[CheckResult]:
        return [c for c in self.checks if c.required and c.status == CheckStatus.FAIL]

    @property
    def overall_status(self) -> str:
        if self.required_failures:
            return CheckStatus.FAIL.value
        if any(c.status == CheckStatus.BLOCKED for c in self.checks if c.required):
            return CheckStatus.BLOCKED.value
        return CheckStatus.PASS.value

    @property
    def exit_code(self) -> int:
        return 1 if self.required_failures else 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "jaeger.selftest.v1",
            "commit": self.commit,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "overall_status": self.overall_status,
            "exit_code": self.exit_code,
            "counts": self.counts,
            "artifacts_dir": self.artifacts_dir,
            "artifacts_cleaned": self.artifacts_cleaned,
            "retention_policy": self.retention_policy,
            "checks": [c.to_dict() for c in self.checks],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, default=str)

    def to_human_report(self) -> str:
        lines = [
            f"JaegerAI Automated Acceptance Report ({self.overall_status})",
            f"Commit: {self.commit} | Started: {self.started_at} | Finished: {self.finished_at}",
            f"Summary: PASS={self.counts['PASS']} FAIL={self.counts['FAIL']} BLOCKED={self.counts['BLOCKED']} SKIPPED={self.counts['SKIPPED']}",
            "",
        ]
        for c in self.checks:
            detail = f" — {c.reason}" if c.reason else ""
            lines.append(f"[{c.status.value:7s}] {c.id}: {c.name} ({c.elapsed_s:.2f}s){detail}")
        return "\n".join(lines)
