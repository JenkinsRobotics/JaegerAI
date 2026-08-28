"""SWE-style coding benchmark runner for JaegerAI."""

from __future__ import annotations

import argparse
import contextlib
import json
import logging
import os
import subprocess
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

TurnFn = Callable[[str], str | dict[str, Any]]


def run_swe_benchmark_task(
    repo_path: Path,
    issue_description: str,
    test_command: str,
    max_turns: int = 15,
    *,
    turn_fn: TurnFn | None = None,
    test_timeout_s: int = 120,
) -> dict[str, Any]:
    """Ask Jaeger to fix one repository, then run its verification command."""
    started = time.perf_counter()
    task_result: dict[str, Any] = {
        "status": "failed",
        "duration_s": 0.0,
        "turns": 0,
        "test_output": "",
        "error": None,
    }

    repo_path = repo_path.expanduser().resolve()
    if not repo_path.is_dir():
        task_result["error"] = f"Repository path {repo_path} is not a directory"
        return task_result
    if not test_command.strip():
        task_result["error"] = "Verification command is empty"
        return task_result

    prompt = (
        f"Fix the following software engineering issue in {repo_path}:\n"
        f"{issue_description}\n\n"
        f"Use at most {max_turns} autonomous steps. Verify the result with: "
        f"{test_command}"
    )

    boot = None
    prior_project_root = None
    try:
        if turn_fn is None:
            from jaeger_agent.workspace import get_project_root, set_project_root
            from jaeger_ai.main import _run_turn, boot_for_tui

            boot = boot_for_tui(instance_name=None, with_memory=True, warmup=False)
            prior_project_root = get_project_root()
            set_project_root(repo_path)

            def _product_turn(text: str) -> dict[str, Any]:
                return _run_turn(
                    boot.client,
                    text,
                    session_key=f"swe-eval-{uuid.uuid4().hex[:10]}",
                )

            turn_fn = _product_turn

        turn_output = turn_fn(prompt)
        if isinstance(turn_output, dict):
            task_result["turns"] = int(turn_output.get("steps") or 1)
            agent_error = turn_output.get("error")
            if agent_error:
                raise RuntimeError(str(agent_error))
        else:
            task_result["turns"] = 1

        # The command is deliberately supplied by the benchmark operator and
        # often contains shell syntax. Keep the shell boundary explicit.
        proc = subprocess.run(
            ["/bin/sh", "-lc", test_command],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=max(1, test_timeout_s),
            check=False,
        )
        task_result["test_output"] = proc.stdout + proc.stderr
        task_result["status"] = "passed" if proc.returncode == 0 else "failed"
        if proc.returncode != 0:
            logger.warning("SWE task verification exited %d", proc.returncode)
    except Exception as exc:  # noqa: BLE001 -- benchmark records failures
        task_result["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        if prior_project_root is not None or boot is not None:
            with contextlib.suppress(Exception):
                from jaeger_agent.workspace import set_project_root

                set_project_root(prior_project_root)
        if boot is not None:
            with contextlib.suppress(Exception):
                boot.cleanup()
        task_result["duration_s"] = round(time.perf_counter() - started, 3)

    return task_result


def main() -> None:
    parser = argparse.ArgumentParser(description="JaegerAI SWE benchmark runner")
    parser.add_argument("--repo", type=Path, required=True, help="Repository under test")
    parser.add_argument(
        "--issue", required=True,
        help="Issue description text or path to a UTF-8 text file",
    )
    parser.add_argument("--test-cmd", required=True, help="Command that verifies the fix")
    parser.add_argument("--max-turns", type=int, default=15)
    parser.add_argument("--test-timeout", type=int, default=120)
    args = parser.parse_args()

    issue = args.issue
    issue_path = Path(os.path.expanduser(issue))
    if issue_path.is_file():
        issue = issue_path.read_text(encoding="utf-8")

    result = run_swe_benchmark_task(
        args.repo,
        issue,
        args.test_cmd,
        max_turns=max(1, args.max_turns),
        test_timeout_s=max(1, args.test_timeout),
    )
    print(json.dumps(result, indent=2))
    if result["status"] != "passed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
