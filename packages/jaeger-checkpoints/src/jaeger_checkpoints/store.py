"""Shadow-Git per-step workspace checkpoints (cline GIT_INDEX_FILE pattern).

Maintains an isolated bare Git directory per workspace under ``storage_dir`` so
snapshots, diffs, and rollbacks NEVER touch or pollute the user's own ``.git``,
current branch, staging index, or commit history.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Checkpoint:
    checkpoint_id: str
    workspace: str
    label: str
    timestamp: str


class ShadowCheckpointStore:
    def __init__(self, storage_dir: str | Path) -> None:
        self.storage_dir = Path(storage_dir).expanduser().resolve()
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    def _repo_dir(self, workspace: str | Path) -> tuple[Path, Path]:
        ws = Path(workspace).expanduser().resolve()
        key = hashlib.sha256(str(ws).encode("utf-8")).hexdigest()[:16]
        git_dir = self.storage_dir / f"ws-{key}.git"
        return ws, git_dir

    def _git(self, ws: Path, git_dir: Path, args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
        env = {
            **os.environ,
            "GIT_DIR": str(git_dir),
            "GIT_WORK_TREE": str(ws),
            "GIT_INDEX_FILE": str(git_dir / "index"),
            "GIT_AUTHOR_NAME": "Jaeger Checkpoint",
            "GIT_AUTHOR_EMAIL": "checkpoint@jaeger.local",
            "GIT_COMMITTER_NAME": "Jaeger Checkpoint",
            "GIT_COMMITTER_EMAIL": "checkpoint@jaeger.local",
        }
        return subprocess.run(
            ["git", *args],
            cwd=str(ws),
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
            check=check,
        )

    def _ensure_init(self, ws: Path, git_dir: Path) -> None:
        if (git_dir / "HEAD").exists():
            return
        git_dir.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "init", "--bare", str(git_dir)], capture_output=True, text=True, check=True)
        excl = git_dir / "info" / "exclude"
        excl.parent.mkdir(parents=True, exist_ok=True)
        excl.write_text(
            ".git/\nnode_modules/\n__pycache__/\n.venv/\nvenv/\n.pytest_cache/\ndist/\nbuild/\n",
            encoding="utf-8",
        )

    def snapshot(self, workspace: str | Path, label: str = "checkpoint") -> Checkpoint:
        ws, git_dir = self._repo_dir(workspace)
        if not ws.is_dir():
            raise ValueError(f"workspace directory does not exist: {ws}")
        self._ensure_init(ws, git_dir)
        self._git(ws, git_dir, ["add", "-A"])
        tree = self._git(ws, git_dir, ["write-tree"]).stdout.strip()
        head_proc = self._git(ws, git_dir, ["rev-parse", "--verify", "HEAD"], check=False)
        parent_args = ["-p", head_proc.stdout.strip()] if head_proc.returncode == 0 else []
        commit = self._git(
            ws, git_dir, ["commit-tree", tree, *parent_args, "-m", label or "checkpoint"],
        ).stdout.strip()
        self._git(ws, git_dir, ["update-ref", "HEAD", commit])
        ts = self._git(ws, git_dir, ["show", "-s", "--format=%cI", commit]).stdout.strip()
        return Checkpoint(checkpoint_id=commit[:12], workspace=str(ws), label=label, timestamp=ts)

    def list_checkpoints(self, workspace: str | Path, *, limit: int = 20) -> list[Checkpoint]:
        ws, git_dir = self._repo_dir(workspace)
        if not (git_dir / "HEAD").exists():
            return []
        proc = self._git(ws, git_dir, ["log", f"-n{max(1, limit)}", "--format=%H\t%cI\t%s"], check=False)
        if proc.returncode != 0:
            return []
        out: list[Checkpoint] = []
        for line in proc.stdout.splitlines():
            parts = line.split("\t", 2)
            if len(parts) == 3:
                out.append(Checkpoint(parts[0][:12], str(ws), parts[2], parts[1]))
        return out

    def diff(self, workspace: str | Path, checkpoint_id: str) -> str:
        ws, git_dir = self._repo_dir(workspace)
        if not (git_dir / "HEAD").exists():
            return ""
        self._git(ws, git_dir, ["add", "-A"])
        return self._git(ws, git_dir, ["diff", "--cached", checkpoint_id], check=False).stdout

    def restore(self, workspace: str | Path, checkpoint_id: str) -> dict[str, Any]:
        ws, git_dir = self._repo_dir(workspace)
        if not (git_dir / "HEAD").exists():
            raise ValueError("no checkpoints exist for this workspace")
        # Record a safety snapshot before restoring so rollback is itself undoable.
        pre = self.snapshot(ws, label=f"pre-restore-{checkpoint_id}")
        self._git(ws, git_dir, ["read-tree", "--reset", "-u", checkpoint_id])
        return {"ok": True, "restored_to": checkpoint_id, "undo_checkpoint_id": pre.checkpoint_id}
