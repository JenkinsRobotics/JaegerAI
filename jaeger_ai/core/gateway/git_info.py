"""Quiet, cached git commit lookup for the Gateway health payload."""
from __future__ import annotations

import functools
import subprocess
from pathlib import Path


@functools.lru_cache(maxsize=8)
def git_commit(path: str) -> str:
    """Return HEAD for the repo containing ``path``, or "unknown".

    Deploy snapshots are not git checkouts; git's "fatal: not a git
    repository" must not reach gateway.log on every health poll, so stderr is
    discarded and the answer is cached per path.
    """
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(Path(path)),
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except Exception:
        return "unknown"
    return out.stdout.strip() if out.returncode == 0 and out.stdout.strip() else "unknown"
