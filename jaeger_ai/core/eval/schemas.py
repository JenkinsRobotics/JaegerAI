"""Schemas and contracts for External Agent Evaluation Suite (Workstream 17)."""
from __future__ import annotations

from enum import Enum
import time
from typing import Any
from pydantic import BaseModel, Field


class FailureCategory(str, Enum):
    """Categorization of external evaluation failures."""
    NONE = "none"
    MODEL_LIMITATION = "model_limitation"
    RUNTIME_LIMITATION = "runtime_limitation"
    TOOL_LIMITATION = "tool_limitation"
    CONTEXT_LIMITATION = "context_limitation"
    INTEGRATION_FAILURE = "integration_failure"


class EvaluationTask(BaseModel):
    """Canonical representation of an external evaluation benchmark task."""
    task_id: str
    suite: str  # BFCL, SWE-bench-Verified, Terminal-Bench, AgentDojo
    description: str = ""
    prompt: str
    setup_files: dict[str, str] = Field(default_factory=dict)
    expected_artifacts: dict[str, str] = Field(default_factory=dict)
    verifier: str = "default_independent_probe"
    metadata: dict[str, Any] = Field(default_factory=dict)


class EvaluationVerdict(BaseModel):
    """Independent grading verdict for an evaluated task."""
    task_id: str
    suite: str
    passed: bool
    failure_category: FailureCategory = FailureCategory.NONE
    evidence: str = ""
    grader_details: dict[str, Any] = Field(default_factory=dict)
    elapsed_s: float = 0.0


class EvaluationReport(BaseModel):
    """Comprehensive, reproducible external evaluation report."""
    report_id: str = Field(default_factory=lambda: f"eval_{int(time.time())}")
    architecture: str = "pinocchio"
    provider: str = "ollama"
    model: str = "kimi-k2.7-code:cloud"
    tool_configuration: dict[str, Any] = Field(default_factory=dict)
    context_configuration: dict[str, Any] = Field(default_factory=dict)
    total_tasks: int = 0
    passed_tasks: int = 0
    pass_rate: float = 0.0
    failure_breakdown: dict[str, int] = Field(default_factory=dict)
    verdicts: list[EvaluationVerdict] = Field(default_factory=list)
    timestamp: float = Field(default_factory=time.time)

    def to_markdown(self) -> str:
        lines = [
            f"# External Agent Evaluation Report: {self.report_id}",
            "",
            f"- **Architecture:** `{self.architecture}`",
            f"- **Provider / Model:** `{self.provider}` / `{self.model}`",
            f"- **Pass Rate:** **{self.pass_rate * 100:.1f}%** ({self.passed_tasks}/{self.total_tasks})",
            "",
            "## Failure Breakdown",
            "",
            "| Category | Count |",
            "| :--- | :--- |",
        ]
        for cat, cnt in sorted(self.failure_breakdown.items()):
            lines.append(f"| `{cat}` | {cnt} |")

        lines.extend([
            "",
            "## Detailed Task Verdicts",
            "",
            "| Task ID | Suite | Result | Failure Category | Evidence |",
            "| :--- | :--- | :--- | :--- | :--- |",
        ])
        for v in self.verdicts:
            res_str = "PASS" if v.passed else "FAIL"
            lines.append(
                f"| `{v.task_id}` | {v.suite} | **{res_str}** | `{v.failure_category.value}` | {v.evidence[:80]} |"
            )

        return "\n".join(lines)
