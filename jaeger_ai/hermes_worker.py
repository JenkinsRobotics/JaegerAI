"""Optional Hermes subprocess worker controlled by Jaeger's delegation tool."""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from typing import Any


def enabled() -> bool:
    """Return true only when the operator selected Hermes as delegate worker."""
    return os.environ.get("JAEGER_DELEGATE_WORKER", "").strip().lower() == "hermes"


def run(subtask: str, depth: int) -> dict[str, Any]:
    """Run a task over one-shot stdio, never a Hermes WebUI or gateway port."""
    command = os.environ.get("JAEGER_HERMES_COMMAND", "hermes").strip() or "hermes"
    executable = shutil.which(command)
    if executable is None:
        return {
            "delegated": False,
            "worker": "hermes",
            "error": f"Hermes worker executable not found: {command}",
        }
    try:
        timeout = max(1, int(os.environ.get("JAEGER_HERMES_TIMEOUT_SECONDS", "900")))
    except ValueError:
        timeout = 900

    started = time.perf_counter()
    try:
        completed = subprocess.run(
            [executable, "--oneshot", subtask],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {
            "delegated": False,
            "worker": "hermes",
            "error": f"Hermes worker timed out after {timeout}s",
        }
    except OSError as exc:
        return {
            "delegated": False,
            "worker": "hermes",
            "error": f"Could not start Hermes worker: {exc}",
        }

    answer = completed.stdout.strip()
    if completed.returncode != 0:
        detail = completed.stderr.strip() or answer or f"exit code {completed.returncode}"
        return {
            "delegated": False,
            "worker": "hermes",
            "error": detail[-2000:],
        }
    return {
        "delegated": True,
        "worker": "hermes",
        "transport": "oneshot_stdio",
        "subtask": subtask,
        "answer": answer,
        "depth": depth + 1,
        "elapsed_s": round(time.perf_counter() - started, 3),
    }
