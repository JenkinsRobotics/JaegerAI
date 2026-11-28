"""Shared-store shadow-git filesystem checkpoints with rollback.

Ported from hermes-agent ``tools/checkpoint_manager.py`` (MIT licensed) and
promoted into the standalone ``jaeger-checkpoints`` package with zero upward
dependencies on ``jaeger_agent`` or ``jaeger_ai``.

Storage layout::

    <state_root>/checkpoints/
        store/                     — one shared bare repo
            refs/jaeger/<hash16>   — per-project branch tip
            indexes/<hash16>       — per-project git index
            projects/<hash16>.json — {workdir, created_at, last_touch}

Config isolation (``GIT_CONFIG_GLOBAL``/``GIT_CONFIG_SYSTEM`` -> ``os.devnull``,
``GIT_CONFIG_NOSYSTEM=1``) prevents an operator's ``commit.gpgsign = true`` from
hanging background snapshots on interactive pinentry prompts.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

_GIT_TIMEOUT = 60
_DEFAULT_MAX_SNAPSHOTS = 20
_REF_PREFIX = "refs/jaeger"

_store_root_provider: Callable[[], Path] | None = None
_enabled_provider: Callable[[], bool] | None = None


@dataclass(frozen=True)
class SnapshotRecord:
    """One snapshot in the shared bare store."""

    commit: str
    created_at: float
    reason: str

    @property
    def age_seconds(self) -> float:
        return max(0.0, time.time() - self.created_at)


# Module-local alias matching the original manager API
Checkpoint = SnapshotRecord


def configure_checkpoints(
    *,
    store_root_provider: Callable[[], Path] | None = None,
    enabled_provider: Callable[[], bool] | None = None,
) -> None:
    """Register host-specific root and enabled providers (dependency inversion)."""
    global _store_root_provider, _enabled_provider
    if store_root_provider is not None:
        _store_root_provider = store_root_provider
    if enabled_provider is not None:
        _enabled_provider = enabled_provider


def _normalize(path: Any) -> Path:
    return Path(os.path.abspath(os.path.expanduser(str(path))))


def _project_hash(working_dir: Any) -> str:
    return hashlib.sha256(
        str(_normalize(working_dir)).encode("utf-8")
    ).hexdigest()[:16]


def _root() -> Path:
    if _store_root_provider is not None:
        return Path(_store_root_provider())
    env_root = os.environ.get("JAEGER_STATE_DIR", "").strip()
    base = Path(env_root).expanduser() if env_root else (Path.home() / ".jaeger")
    return base / "checkpoints"


def store_path(root: Path | None = None) -> Path:
    return (Path(root) if root is not None else _root()) / "store"


def _index_path(store: Path, dir_hash: str) -> Path:
    return store / "indexes" / dir_hash


def _meta_path(store: Path, dir_hash: str) -> Path:
    return store / "projects" / f"{dir_hash}.json"


def _ref(dir_hash: str) -> str:
    return f"{_REF_PREFIX}/{dir_hash}"


def _git_env(store: Path, working_dir: Any, index_file: Path | None) -> dict[str, str]:
    """Env that redirects git at the shadow store without inheriting operator config."""
    env = dict(os.environ)
    env["GIT_DIR"] = str(store)
    env["GIT_WORK_TREE"] = str(_normalize(working_dir))
    env.pop("GIT_NAMESPACE", None)
    env.pop("GIT_ALTERNATE_OBJECT_DIRECTORIES", None)
    if index_file is not None:
        env["GIT_INDEX_FILE"] = str(index_file)
    else:
        env.pop("GIT_INDEX_FILE", None)
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_CONFIG_SYSTEM"] = os.devnull
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    env.setdefault("GIT_AUTHOR_NAME", "jaeger-checkpoints")
    env.setdefault("GIT_AUTHOR_EMAIL", "checkpoints@jaeger.local")
    env.setdefault("GIT_COMMITTER_NAME", "jaeger-checkpoints")
    env.setdefault("GIT_COMMITTER_EMAIL", "checkpoints@jaeger.local")
    return env


def _git(
    args: list[str],
    store: Path,
    working_dir: Any,
    index_file: Path | None = None,
    timeout: int = _GIT_TIMEOUT,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        env=_git_env(store, working_dir, index_file),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )


def _repair_bare_dirs(store: Path) -> None:
    """Recreate ``refs/``/``branches/`` that ``git gc`` can prune."""
    for sub in ("refs", "refs/heads", "branches"):
        try:
            (store / sub).mkdir(parents=True, exist_ok=True)
        except OSError:
            pass


def _init_store(store: Path, working_dir: Any) -> bool:
    """Create the bare store if absent. True when usable."""
    try:
        if (store / "HEAD").exists():
            _repair_bare_dirs(store)
            return True
        store.mkdir(parents=True, exist_ok=True)
        env = dict(os.environ)
        for k in (
            "GIT_DIR",
            "GIT_WORK_TREE",
            "GIT_INDEX_FILE",
            "GIT_NAMESPACE",
            "GIT_ALTERNATE_OBJECT_DIRECTORIES",
        ):
            env.pop(k, None)
        env["GIT_CONFIG_GLOBAL"] = os.devnull
        env["GIT_CONFIG_SYSTEM"] = os.devnull
        env["GIT_CONFIG_NOSYSTEM"] = "1"
        res = subprocess.run(
            ["git", "init", "--bare", "--quiet", str(store)],
            env=env,
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT,
        )
        if res.returncode != 0:
            logger.warning("checkpoints: store init failed: %s", res.stderr.strip())
            return False
        _repair_bare_dirs(store)
        (store / "indexes").mkdir(parents=True, exist_ok=True)
        (store / "projects").mkdir(parents=True, exist_ok=True)
        (store / "info").mkdir(parents=True, exist_ok=True)
        (store / "info" / "exclude").write_text(
            "\n".join(
                (
                    ".git/",
                    "node_modules/",
                    "__pycache__/",
                    "*.pyc",
                    ".venv/",
                    "venv/",
                    ".worktrees/",
                    ".DS_Store",
                    "",
                )
            ),
            encoding="utf-8",
        )
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("checkpoints: store init error: %s", exc)
        return False


def _register(store: Path, working_dir: Any, dir_hash: str) -> None:
    meta = _meta_path(store, dir_hash)
    try:
        meta.parent.mkdir(parents=True, exist_ok=True)
        now = time.time()
        payload = {
            "workdir": str(_normalize(working_dir)),
            "created_at": now,
            "last_touch": now,
        }
        if meta.is_file():
            try:
                existing = json.loads(meta.read_text(encoding="utf-8"))
                payload["created_at"] = existing.get("created_at", now)
            except Exception:  # noqa: BLE001
                pass
        meta.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except OSError as exc:
        logger.debug("checkpoints: could not register project: %s", exc)


class CheckpointManager:
    """Takes at most one snapshot per turn, per working directory."""

    def __init__(
        self,
        enabled: bool | None = None,
        max_snapshots: int = _DEFAULT_MAX_SNAPSHOTS,
        *,
        store_root: Path | None = None,
        enabled_provider: Callable[[], bool] | None = None,
    ) -> None:
        self._enabled = enabled
        self._store_root = Path(store_root) if store_root is not None else None
        self._enabled_provider = enabled_provider
        self.max_snapshots = max(1, int(max_snapshots))
        self._turn_taken: set[str] = set()

    def _store(self) -> Path:
        return store_path(self._store_root)

    @property
    def enabled(self) -> bool:
        if self._enabled is not None:
            return self._enabled
        val = os.environ.get("JAEGER_CHECKPOINTS", "").strip().lower()
        if val in ("0", "false", "no", "off"):
            return False
        if val in ("1", "true", "yes", "on"):
            return True
        provider = self._enabled_provider or _enabled_provider
        if provider is not None:
            try:
                return bool(provider())
            except Exception:  # noqa: BLE001
                return False
        return False

    def new_turn(self) -> None:
        """Reset the once-per-turn guard. Called at the top of each turn."""
        self._turn_taken.clear()

    def ensure_checkpoint(
        self, working_dir: Any, reason: str = "auto"
    ) -> str | None:
        """Snapshot *working_dir* unless one was already taken this turn."""
        if not self.enabled:
            return None
        key = str(_normalize(working_dir))
        if key in self._turn_taken:
            return None
        self._turn_taken.add(key)
        try:
            return self._take(working_dir, reason)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "checkpoints: snapshot failed for %s: %s", working_dir, exc
            )
            return None

    def _take(self, working_dir: Any, reason: str) -> str | None:
        wd = _normalize(working_dir)
        if not wd.is_dir():
            return None
        store = self._store()
        if not _init_store(store, wd):
            return None
        dir_hash = _project_hash(wd)
        index = _index_path(store, dir_hash)
        index.parent.mkdir(parents=True, exist_ok=True)
        ref = _ref(dir_hash)
        _register(store, wd, dir_hash)

        parent = self._tip(store, wd, ref)
        if parent:
            _git(["read-tree", parent], store, wd, index)
        else:
            _git(["read-tree", "--empty"], store, wd, index)

        add = _git(["add", "-A", "--", str(wd)], store, wd, index)
        if add.returncode != 0:
            logger.debug("checkpoints: add failed: %s", add.stderr.strip())
            return None

        tree = _git(["write-tree"], store, wd, index)
        if tree.returncode != 0:
            return None
        tree_hash = tree.stdout.strip()

        if parent:
            parent_tree = _git(["rev-parse", f"{parent}^{{tree}}"], store, wd, index)
            if (
                parent_tree.returncode == 0
                and parent_tree.stdout.strip() == tree_hash
            ):
                return None

        args = ["commit-tree", tree_hash, "-m", f"checkpoint: {reason}"]
        if parent:
            args += ["-p", parent]
        made = _git(args, store, wd, index)
        if made.returncode != 0:
            logger.debug("checkpoints: commit-tree failed: %s", made.stderr.strip())
            return None
        commit = made.stdout.strip()
        upd = _git(["update-ref", ref, commit], store, wd, index)
        if upd.returncode != 0:
            return None
        self._prune(store, wd, ref, index)
        return commit

    @staticmethod
    def _tip(store: Path, wd: Path, ref: str) -> str | None:
        res = _git(["rev-parse", "--verify", "--quiet", ref], store, wd)
        return res.stdout.strip() if res.returncode == 0 else None

    def list_checkpoints(self, working_dir: Any) -> list[SnapshotRecord]:
        """Snapshots for *working_dir*, newest first."""
        wd = _normalize(working_dir)
        store = self._store()
        if not (store / "HEAD").exists():
            return []
        ref = _ref(_project_hash(wd))
        res = _git(
            [
                "log",
                "--format=%H%x00%ct%x00%s",
                "-n",
                str(self.max_snapshots * 2),
                ref,
            ],
            store,
            wd,
        )
        if res.returncode != 0:
            return []
        out: list[SnapshotRecord] = []
        for line in res.stdout.splitlines():
            parts = line.split("\x00")
            if len(parts) != 3:
                continue
            commit, ts, subject = parts
            try:
                created = float(ts)
            except ValueError:
                continue
            out.append(
                SnapshotRecord(
                    commit=commit,
                    created_at=created,
                    reason=subject.removeprefix("checkpoint: "),
                )
            )
        return out

    def diff(self, working_dir: Any, commit: str) -> str:
        """Diff the working tree against a snapshot."""
        wd = _normalize(working_dir)
        if not _valid_commit(commit):
            return ""
        store = self._store()
        index = _index_path(store, _project_hash(wd))
        res = _git(["diff", commit, "--"], store, wd, index)
        return res.stdout if res.returncode == 0 else ""

    def restore(
        self, working_dir: Any, commit: str, *, take_safety: bool = True
    ) -> tuple[bool, str]:
        """Roll *working_dir* back to *commit* with a pre-restore safety snapshot."""
        if not _valid_commit(commit):
            return False, f"not a valid commit hash: {commit!r}"
        wd = _normalize(working_dir)
        if not wd.is_dir():
            return False, f"not a directory: {wd}"
        store = self._store()
        if not (store / "HEAD").exists():
            return False, "no checkpoint store for this instance"

        index = _index_path(store, _project_hash(wd))
        known = _git(["cat-file", "-e", f"{commit}^{{commit}}"], store, wd, index)
        if known.returncode != 0:
            return False, f"unknown checkpoint {commit[:12]}"

        safety = None
        if take_safety:
            try:
                safety = self._take(wd, "pre-restore safety")
            except Exception as exc:  # noqa: BLE001
                return False, (
                    f"pre-restore safety snapshot failed ({exc}); "
                    "nothing was changed"
                )
            if safety is None and self.list_checkpoints(wd):
                safety = None

        res = _git(["checkout", "-f", commit, "--", "."], store, wd, index)
        if res.returncode != 0:
            return False, f"restore failed: {res.stderr.strip()[:300]}"
        msg = f"restored {wd} to checkpoint {commit[:12]}"
        if safety:
            msg += f" (pre-restore state saved as {safety[:12]})"
        return True, msg

    def _prune(self, store: Path, wd: Path, ref: str, index: Path) -> None:
        """Keep at most ``max_snapshots`` by re-rooting the ref."""
        try:
            res = _git(["rev-list", ref], store, wd, index)
            if res.returncode != 0:
                return
            commits = res.stdout.split()
            if len(commits) <= self.max_snapshots:
                return
            keep = commits[self.max_snapshots - 1]
            _git(["update-ref", ref, keep], store, wd, index)
        except Exception as exc:  # noqa: BLE001
            logger.debug("checkpoints: prune skipped: %s", exc)


def _valid_commit(value: str) -> bool:
    v = (value or "").strip()
    return 7 <= len(v) <= 40 and all(c in "0123456789abcdef" for c in v.lower())


_manager: CheckpointManager | None = None


def manager() -> CheckpointManager:
    global _manager
    if _manager is None:
        _manager = CheckpointManager()
    return _manager


def reset_manager() -> None:
    """Test seam."""
    global _manager
    _manager = None


__all__ = [
    "Checkpoint",
    "CheckpointManager",
    "SnapshotRecord",
    "configure_checkpoints",
    "manager",
    "reset_manager",
    "store_path",
]
