"""System medium transducer for code execution, git, and file modifications."""

from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path

from ..intent import CognitiveIntent, MediumType
from .base import TransductionResult

logger = logging.getLogger(__name__)


class SystemTransducer:
    """Transforms intent into code modifications, automated test execution, or cache cleanups."""

    def __init__(self, workspace_root: Path | str | None = None) -> None:
        self.workspace_root = Path(workspace_root or os.getcwd()).resolve()

    async def transduce(self, intent: CognitiveIntent) -> TransductionResult:
        payload = intent.payload

        # Clean scratch caches
        if payload.get("action") == "clean_scratch_caches":
            cleaned = self._clean_scratch_caches()
            return TransductionResult(
                success=True,
                medium=MediumType.SYSTEM,
                output=f"System transducer cleaned {cleaned} temporary files.",
                metadata={"cleaned_count": cleaned},
            )

        # Run automated tests if requested
        if payload.get("action") == "run_test_suite":
            test_path = payload.get("test_path", "dev/tests")
            return self._run_tests(test_path)

        # Default system action: log maintenance intent
        return TransductionResult(
            success=True,
            medium=MediumType.SYSTEM,
            output=f"Executed system action for goal: {intent.goal}",
            metadata={"goal": intent.goal, "reasoning": intent.reasoning},
        )

    def _clean_scratch_caches(self) -> int:
        count = 0
        scratch_dir = Path(os.path.expanduser("~/.jaeger/scratch"))
        if scratch_dir.exists():
            for p in scratch_dir.glob("*"):
                try:
                    if p.is_file():
                        p.unlink()
                        count += 1
                except Exception:
                    pass
        return count

    def _run_tests(self, test_path: str) -> TransductionResult:
        try:
            proc = subprocess.run(
                ["pytest", test_path, "-q"],
                cwd=str(self.workspace_root),
                capture_output=True,
                text=True,
                timeout=30,
            )
            success = proc.returncode == 0
            return TransductionResult(
                success=success,
                medium=MediumType.SYSTEM,
                output=proc.stdout[-500:] if proc.stdout else proc.stderr[-500:],
                metadata={"exit_code": proc.returncode},
            )
        except Exception as exc:
            return TransductionResult(
                success=False,
                medium=MediumType.SYSTEM,
                output=f"Test run failed to execute: {exc}",
            )
