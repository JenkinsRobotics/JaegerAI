"""System medium transducer for code execution, git, and file modifications.

Dangerous actions (``run_test_suite``, code-mod paths) require
``allow_dangerous_actions=True`` on the transducer / ARESConfig (default False).
``clean_scratch_caches`` is limited to ``~/.jaeger/scratch`` only.
"""

from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path

from ..intent import CognitiveIntent, MediumType
from .base import TransductionResult

logger = logging.getLogger(__name__)

DANGEROUS_ACTIONS = frozenset({
    "run_test_suite",
    "modify_code",
    "code_mod",
    "apply_patch",
    "git_commit",
    "git_write",
})


class SystemTransducer:
    """Transforms intent into gated system actions (fail-closed by default)."""

    def __init__(
        self,
        workspace_root: Path | str | None = None,
        *,
        allow_dangerous_actions: bool = False,
    ) -> None:
        self.workspace_root = Path(workspace_root or os.getcwd()).resolve()
        self.allow_dangerous_actions = bool(allow_dangerous_actions)

    async def transduce(self, intent: CognitiveIntent) -> TransductionResult:
        payload = intent.payload or {}
        action = str(payload.get("action") or "")

        if action == "clean_scratch_caches":
            cleaned = self._clean_scratch_caches()
            return TransductionResult(
                success=True,
                medium=MediumType.SYSTEM,
                output=f"System transducer cleaned {cleaned} temporary files under ~/.jaeger/scratch.",
                metadata={"cleaned_count": cleaned, "gated": False},
            )

        if action in DANGEROUS_ACTIONS or action.startswith("code_"):
            if not self.allow_dangerous_actions:
                logger.info("Blocked gated system action %s (allow_dangerous_actions=False)", action)
                return TransductionResult(
                    success=False,
                    medium=MediumType.SYSTEM,
                    output=(
                        f"Blocked gated system action '{action}': "
                        "requires ARESConfig.allow_dangerous_system_actions=True"
                    ),
                    metadata={"action": action, "gated": True, "blocked": True},
                )
            if action == "run_test_suite":
                test_path = payload.get("test_path", "dev/tests")
                return self._run_tests(str(test_path))

        # Default: record intent without mutating the workspace
        return TransductionResult(
            success=True,
            medium=MediumType.SYSTEM,
            output=f"Recorded system intent (no mutation): {intent.goal}",
            metadata={"goal": intent.goal, "reasoning": intent.reasoning, "gated": False},
        )

    def _clean_scratch_caches(self) -> int:
        count = 0
        scratch_dir = Path(os.path.expanduser("~/.jaeger/scratch")).resolve()
        if not scratch_dir.exists():
            return 0
        # Only delete files directly under scratch (no recursion outside)
        for p in scratch_dir.iterdir():
            try:
                resolved = p.resolve()
                if resolved.parent != scratch_dir:
                    continue
                if resolved.is_file():
                    resolved.unlink()
                    count += 1
            except OSError:
                pass
        return count

    def _run_tests(self, test_path: str) -> TransductionResult:
        # Extra fail-closed: refuse paths that escape workspace
        target = (self.workspace_root / test_path).resolve()
        if self.workspace_root not in target.parents and target != self.workspace_root:
            return TransductionResult(
                success=False,
                medium=MediumType.SYSTEM,
                output=f"Refused test path outside workspace: {test_path}",
                metadata={"blocked": True},
            )
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
                output=(proc.stdout[-500:] if proc.stdout else proc.stderr[-500:]),
                metadata={"exit_code": proc.returncode, "gated": False},
            )
        except Exception as exc:
            return TransductionResult(
                success=False,
                medium=MediumType.SYSTEM,
                output=f"Test run failed to execute: {type(exc).__name__}",
            )
