"""Agent-mode safety: isolate file/code work and make every turn undoable.

Industry-standard default (as in Codex and Claude Code):

* **Git workspace → session worktree.** An Agent-mode turn whose workspace is
  inside a git repository runs in a per-session git worktree
  (``<state>/worktrees/<repo>-<sid8>`` on branch ``jaeger/<sid8>``) that starts
  from the checkout's HEAD plus the owner's uncommitted changes. The owner's
  checkout is untouched until they press **Apply**, which lands the agent's
  changes there as ordinary uncommitted edits. **Discard** moves the worktree
  aside and keeps the branch, so nothing is lost.
* **Any workspace → per-turn checkpoint.** Before an Agent turn the effective
  directory is snapshotted into a shadow git store (never the owner's repo);
  after the turn a second snapshot records what changed. **Undo** puts the
  files back to the pre-turn snapshot. Files the turn created are moved to
  ``<state>/agent-undo-trash/`` rather than deleted, and the current state is
  snapshotted first so the undo itself can be reverted.

After **Apply**, a worktree turn's Undo is retargeted to the owner's checkout:
it reverts that turn's diff there (and in the worktree), offered only while
every file in the checkout still matches what the turn produced.

Undo is offered only while the files are exactly as the turn left them: an
older turn whose files were changed again later is not silently rolled back.
Very large or unsafe roots (``/``, the home folder) are never snapshotted.

Mode: ``JAEGER_AGENT_ISOLATION`` = ``worktree`` (default) | ``checkpoint`` |
``off``. Plan and Chat turns are read-only and are not touched.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_MAX_FILES = 60_000           # refuse to snapshot trees bigger than this
_MAX_CARRY_BYTES = 200 * 1024 * 1024
_GIT_TIMEOUT = 120


def isolation_mode() -> str:
    raw = (os.environ.get("JAEGER_AGENT_ISOLATION") or "").strip().lower()
    return raw if raw in {"worktree", "checkpoint", "off"} else "worktree"


def _git(args: list[str], cwd: Path | str, *, check: bool = False, input: str | None = None,
         timeout: int = _GIT_TIMEOUT) -> subprocess.CompletedProcess:
    """Run git in the owner's repo, never signing or prompting."""
    env = dict(os.environ)
    env["GIT_TERMINAL_PROMPT"] = "0"
    for k in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"):
        env.pop(k, None)
    res = subprocess.run(["git", "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null", *args],
                         cwd=str(cwd), env=env, capture_output=True, text=True, input=input,
                         encoding="utf-8", errors="replace", timeout=timeout)
    if check and res.returncode != 0:
        raise RuntimeError(f"git {' '.join(args[:2])} failed: {res.stderr.strip()[:300]}")
    return res


def _repo_root(path: Path) -> Path | None:
    res = _git(["rev-parse", "--show-toplevel"], path)
    return Path(res.stdout.strip()) if res.returncode == 0 and res.stdout.strip() else None


def _unsafe_root(path: Path) -> bool:
    home = Path.home().resolve()
    p = path.resolve()
    return p == Path("/") or p == home or p in home.parents or len(p.parts) <= 2


class _Shadow:
    """Snapshots of a directory in a private bare repo (never the owner's .git)."""

    def __init__(self, store: Path):
        self.store = store

    def _cp(self):
        from jaeger_checkpoints import shadow_manager as cp
        return cp

    def _ready(self, wd: Path) -> bool:
        return self._cp()._init_store(self.store, wd)

    def _g(self, args: list[str], wd: Path, index: Path | None = None):
        return self._cp()._git(args, self.store, wd, index, timeout=_GIT_TIMEOUT)

    def _index(self, wd: Path) -> Path:
        cp = self._cp()
        path = cp._index_path(self.store, cp._project_hash(wd))
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def _ref(self, wd: Path) -> str:
        cp = self._cp()
        return cp._ref(cp._project_hash(wd))

    def tree_now(self, wd: Path) -> str | None:
        """Tree hash of the directory as it is now, without recording anything."""
        if not self._ready(wd):
            return None
        index = self._index(wd)
        tmp = index.with_name(index.name + f".peek-{uuid.uuid4().hex[:8]}")
        try:
            if index.exists():
                shutil.copy2(index, tmp)
            if self._g(["add", "-A", "--", str(wd)], wd, tmp).returncode != 0:
                return None
            res = self._g(["write-tree"], wd, tmp)
            return res.stdout.strip() if res.returncode == 0 else None
        finally:
            with __import__("contextlib").suppress(OSError):
                tmp.unlink()

    def snapshot(self, wd: Path, reason: str) -> str | None:
        """Commit the directory's current state; returns the commit (new or unchanged tip)."""
        if not self._ready(wd):
            return None
        index, ref = self._index(wd), self._ref(wd)
        tip = self._g(["rev-parse", "--verify", "--quiet", ref], wd)
        parent = tip.stdout.strip() if tip.returncode == 0 else ""
        self._g(["read-tree", parent] if parent else ["read-tree", "--empty"], wd, index)
        if self._g(["add", "-A", "--", str(wd)], wd, index).returncode != 0:
            return None
        tree = self._g(["write-tree"], wd, index).stdout.strip()
        if not tree:
            return None
        if parent and self._g(["rev-parse", f"{parent}^{{tree}}"], wd).stdout.strip() == tree:
            return parent
        made = self._g(["commit-tree", tree, "-m", f"agent-safety: {reason}", *(["-p", parent] if parent else [])], wd)
        commit = made.stdout.strip()
        if made.returncode != 0 or not commit:
            return None
        self._g(["update-ref", ref, commit], wd)
        return commit

    def changes(self, wd: Path, before: str, after: str) -> list[dict[str, str]]:
        res = self._g(["diff", "--name-status", "--no-renames", before, after], wd)
        out = []
        for line in res.stdout.splitlines():
            status, _, path = line.partition("\t")
            if path:
                out.append({"path": path, "status": {"A": "added", "D": "deleted"}.get(status[:1], "modified")})
        return out

    def tree_of(self, wd: Path, commit: str) -> str:
        return self._g(["rev-parse", f"{commit}^{{tree}}"], wd).stdout.strip()

    def blob(self, wd: Path, commit: str, path: str) -> bytes | None:
        """File bytes as recorded in a snapshot, or None when absent there."""
        cp = self._cp()
        res = subprocess.run(["git", "cat-file", "blob", f"{commit}:{path}"], env=cp._git_env(self.store, wd, None),
                             capture_output=True, timeout=_GIT_TIMEOUT)
        return res.stdout if res.returncode == 0 else None

    def restore_paths(self, wd: Path, commit: str, paths: list[str]) -> None:
        for i in range(0, len(paths), 200):
            chunk = paths[i:i + 200]
            res = self._g(["checkout", commit, "--", *chunk], wd, self._index(wd))
            if res.returncode != 0:
                raise RuntimeError(f"restore failed: {res.stderr.strip()[:300]}")


def _count_files(root: Path, limit: int) -> int:
    n = 0
    skip = {".git", "node_modules", "__pycache__", ".venv", "venv", ".worktrees"}
    for _dir, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in skip]
        n += len(files)
        if n > limit:
            break
    return n


class AgentSafety:
    def __init__(self, state_root: Path, store_root: Path):
        self.state_root = state_root          # e.g. ~/.jaeger
        self.root = store_root                # gateway dir / agent-safety
        self.shadow = _Shadow(store_root / "store")
        self.lock = threading.RLock()

    # ── records ─────────────────────────────────────────────────────
    def _dir(self, session: str) -> Path:
        return self.root / "sessions" / hashlib.sha256(session.encode()).hexdigest()[:24]

    def _read(self, path: Path) -> dict[str, Any]:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _write(self, path: Path, data: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        tmp = path.with_suffix(f".{uuid.uuid4().hex}.tmp")
        tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
        os.replace(tmp, path)

    def _turn_path(self, session: str, request: str) -> Path:
        return self._dir(session) / f"turn-{hashlib.sha256(request.encode()).hexdigest()[:24]}.json"

    def _wt_path(self, session: str) -> Path:
        return self._dir(session) / "worktree.json"

    # ── worktree ────────────────────────────────────────────────────
    def worktree(self, session: str) -> dict[str, Any]:
        rec = self._read(self._wt_path(session))
        if rec and not Path(rec.get("path", "")).is_dir():
            return {}
        return rec

    def _ensure_worktree(self, session: str, repo: Path) -> dict[str, Any]:
        rec = self.worktree(session)
        if rec and Path(rec["repo"]) == repo:
            return rec
        sid8 = re.sub(r"[^a-zA-Z0-9]", "", session)[:8] or uuid.uuid4().hex[:8]
        name = re.sub(r"[^A-Za-z0-9._-]", "-", repo.name)[:40]
        base_dir = self.state_root / "worktrees"
        base_dir.mkdir(parents=True, exist_ok=True)
        path, branch, n = base_dir / f"{name}-{sid8}", f"jaeger/{sid8}", 1
        while path.exists() or _git(["rev-parse", "--verify", "--quiet", f"refs/heads/{branch}"], repo).returncode == 0:
            n += 1
            path, branch = base_dir / f"{name}-{sid8}-{n}", f"jaeger/{sid8}-{n}"
        head = _git(["rev-parse", "HEAD"], repo, check=True).stdout.strip()
        _git(["worktree", "add", "-b", branch, str(path), head], repo, check=True)
        carried = self._carry_uncommitted(repo, path)
        if carried:
            _git(["add", "-A"], path, check=True)
            _git(["-c", "user.name=Jaeger", "-c", "user.email=jaeger@localhost", "commit", "-q", "--no-verify",
                  "-m", "Jaeger: starting point (your uncommitted changes)"], path, check=True)
        base = _git(["rev-parse", "HEAD"], path, check=True).stdout.strip()
        rec = {"repo": str(repo), "path": str(path), "branch": branch, "base": base, "head": head,
               "created_at": time.time(), "carried": carried}
        self._write(self._wt_path(session), rec)
        return rec

    @staticmethod
    def _carry_uncommitted(repo: Path, wt: Path) -> int:
        """Bring the owner's uncommitted tracked edits and untracked files along."""
        n = 0
        diff = subprocess.run(["git", "diff", "--binary", "HEAD"], cwd=str(repo), capture_output=True, timeout=_GIT_TIMEOUT)
        if diff.returncode == 0 and diff.stdout.strip():
            applied = subprocess.run(["git", "apply", "--binary", "--whitespace=nowarn"], cwd=str(wt), input=diff.stdout,
                                     capture_output=True, timeout=_GIT_TIMEOUT)
            if applied.returncode == 0:
                n += 1
            else:
                logger.warning("agent worktree: uncommitted edits not carried: %s", applied.stderr[:200])
        others = _git(["ls-files", "--others", "--exclude-standard", "-z"], repo).stdout.split("\0")
        total = 0
        for rel in [o for o in others if o][:2000]:
            src = repo / rel
            try:
                size = src.stat().st_size
            except OSError:
                continue
            total += size
            if total > _MAX_CARRY_BYTES:
                logger.warning("agent worktree: untracked files over %d MB not carried", _MAX_CARRY_BYTES >> 20)
                break
            dst = wt / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            n += 1
        return n

    def worktree_status(self, session: str) -> dict[str, Any]:
        rec = self.worktree(session)
        if not rec:
            return {"active": False, "mode": isolation_mode()}
        wt = Path(rec["path"])
        _git(["add", "-A", "-N"], wt)  # show new files in the diff without staging content
        res = _git(["diff", "--name-status", "--no-renames", rec["base"]], wt)
        files = []
        for line in res.stdout.splitlines():
            status, _, path = line.partition("\t")
            if path:
                files.append({"path": path, "status": {"A": "added", "D": "deleted"}.get(status[:1], "modified")})
        stat = _git(["diff", "--shortstat", rec["base"]], wt).stdout.strip()
        return {"active": True, "mode": "worktree", "repo": rec["repo"], "repoName": Path(rec["repo"]).name,
                "path": rec["path"], "branch": rec["branch"], "files": files, "stat": stat}

    def apply(self, session: str) -> dict[str, Any]:
        """Land the agent's worktree changes in the owner's checkout as uncommitted edits."""
        with self.lock:
            rec = self.worktree(session)
            if not rec:
                raise ValueError("This chat has no agent worktree")
            wt, repo = Path(rec["path"]), Path(rec["repo"])
            _git(["add", "-A"], wt, check=True)
            if _git(["diff", "--cached", "--quiet"], wt).returncode != 0:
                _git(["-c", "user.name=Jaeger", "-c", "user.email=jaeger@localhost", "commit", "-q", "--no-verify",
                      "-m", "Jaeger: agent changes"], wt, check=True)
            head = _git(["rev-parse", "HEAD"], wt, check=True).stdout.strip()
            patch = subprocess.run(["git", "diff", "--binary", rec["base"], head], cwd=str(wt),
                                   capture_output=True, timeout=_GIT_TIMEOUT).stdout
            if not patch.strip():
                return {**self.worktree_status(session), "applied": 0}
            files = _git(["diff", "--name-only", rec["base"], head], wt).stdout.split()
            check = subprocess.run(["git", "apply", "--check", "--binary"], cwd=str(repo), input=patch,
                                   capture_output=True, timeout=_GIT_TIMEOUT)
            if check.returncode != 0:
                raise ValueError(f"Your checkout changed in the same places. Nothing was applied; merge branch "
                                 f"{rec['branch']} yourself, or discard. ({check.stderr.decode(errors='replace').strip()[:160]})")
            done = subprocess.run(["git", "apply", "--binary"], cwd=str(repo), input=patch,
                                  capture_output=True, timeout=_GIT_TIMEOUT)
            if done.returncode != 0:
                raise ValueError(f"Apply failed: {done.stderr.decode(errors='replace').strip()[:200]}")
            rec["base"] = head
            rec["applied_at"] = time.time()
            self._write(self._wt_path(session), rec)
            self._mark_applied(session, rec)
            return {**self.worktree_status(session), "applied": len(files), "appliedFiles": files[:200]}

    def _turns(self, session: str) -> list[tuple[Path, dict[str, Any]]]:
        folder = self._dir(session)
        return [(p, self._read(p)) for p in sorted(folder.glob("turn-*.json"))] if folder.is_dir() else []

    def _mark_applied(self, session: str, rec: dict[str, Any]) -> None:
        """Retarget Undo of every applied worktree turn to the owner's checkout."""
        wt, repo = Path(rec["path"]).resolve(), Path(rec["repo"])
        for path, turn in self._turns(session):
            if turn.get("mode") != "worktree" or turn.get("undone") or turn.get("applied") or not turn.get("files"):
                continue
            if (turn.get("worktree") or {}).get("path") != rec["path"]:
                continue
            try:
                rel = Path(turn["dir"]).resolve().relative_to(wt)
            except ValueError:
                continue
            turn["applied"] = {"dir": str(repo / rel), "at": time.time()}
            self._write(path, turn)

    def _checkout_matches(self, turn: dict[str, Any]) -> tuple[bool, str]:
        """True while every file in the checkout is exactly what the turn produced."""
        wd, target = Path(turn["dir"]), Path(turn["applied"]["dir"])
        for f in turn.get("files") or []:
            want = self.shadow.blob(wd, turn["after"], f["path"])
            dest = target / f["path"]
            have = dest.read_bytes() if dest.is_file() else None
            if have != want:
                return False, f"{f['path']} changed in {target.name} after Apply; undo it by hand or with git"
        return True, ""

    def _undo_applied(self, turn: dict[str, Any], trash: Path) -> list[str]:
        """Revert the turn's diff in the checkout, then in the worktree, and move the base on."""
        wd, target = Path(turn["dir"]), Path(turn["applied"]["dir"])
        moved: list[str] = []
        for f in turn.get("files") or []:
            dest = target / f["path"]
            before = self.shadow.blob(wd, turn["before"], f["path"])
            if before is None:
                if dest.exists():
                    (trash / f["path"]).parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(dest), str(trash / f["path"]))
                    moved.append(f["path"])
            else:
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(before)
        # Keep the worktree in step so a later Apply does not bring the change back.
        if wd.is_dir() and self.shadow.tree_now(wd) == self.shadow.tree_of(wd, turn["after"]):
            others = [f["path"] for f in turn["files"] if self.shadow.blob(wd, turn["before"], f["path"]) is not None]
            for f in turn["files"]:
                if f["path"] not in others and (wd / f["path"]).exists():
                    (trash / "worktree" / f["path"]).parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(wd / f["path"]), str(trash / "worktree" / f["path"]))
            if others:
                self.shadow.restore_paths(wd, turn["before"], others)
            rec = self.worktree(turn["session"])
            if rec:
                wt = Path(rec["path"])
                _git(["add", "-A"], wt)
                if _git(["diff", "--cached", "--quiet"], wt).returncode != 0:
                    _git(["-c", "user.name=Jaeger", "-c", "user.email=jaeger@localhost", "commit", "-q", "--no-verify",
                          "-m", "Jaeger: undo applied turn"], wt)
                rec["base"] = _git(["rev-parse", "HEAD"], wt).stdout.strip() or rec["base"]
                self._write(self._wt_path(turn["session"]), rec)
        return moved

    def discard(self, session: str) -> dict[str, Any]:
        """Move the worktree aside (kept on branch + folder); the next Agent turn starts fresh."""
        with self.lock:
            rec = self.worktree(session)
            if not rec:
                raise ValueError("This chat has no agent worktree")
            wt, repo = Path(rec["path"]), Path(rec["repo"])
            _git(["add", "-A"], wt)
            if _git(["diff", "--cached", "--quiet"], wt).returncode != 0:
                _git(["-c", "user.name=Jaeger", "-c", "user.email=jaeger@localhost", "commit", "-q", "--no-verify",
                      "-m", "Jaeger: discarded agent changes"], wt)
            aside = self.state_root / "worktrees" / ".discarded" / f"{wt.name}-{time.strftime('%Y%m%d-%H%M%S')}"
            aside.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(wt), str(aside))
            _git(["worktree", "prune"], repo)
            self._wt_path(session).replace(self._dir(session) / f"worktree-discarded-{int(time.time())}.json")
            return {"active": False, "mode": isolation_mode(), "discarded": True, "branch": rec["branch"],
                    "movedTo": str(aside)}

    # ── turns ───────────────────────────────────────────────────────
    def prepare(self, session: str, request: str, workspace: str | None) -> dict[str, Any]:
        """Before an Agent turn: pick the directory it works in and snapshot it."""
        mode = isolation_mode()
        if mode == "off" or not workspace:
            return {}
        ws = Path(workspace).expanduser()
        if not ws.is_dir() or _unsafe_root(ws):
            return {}
        with self.lock:
            existing = self._read(self._turn_path(session, request))
            if existing.get("dir") and Path(existing["dir"]).is_dir():
                # A continuation pass of the same request keeps its directory and checkpoint.
                return {"root": existing["dir"], "mode": existing.get("mode"), "worktree": existing.get("worktree")}
            root, rec = ws, None
            repo = _repo_root(ws) if mode == "worktree" else None
            if repo is not None and not _unsafe_root(repo):
                try:
                    rec = self._ensure_worktree(session, repo)
                    root = Path(rec["path"]) / ws.resolve().relative_to(repo.resolve())
                except Exception as exc:  # noqa: BLE001 — fall back to checkpoint only
                    logger.warning("agent worktree unavailable for %s: %s", repo, exc)
                    rec, root = None, ws
            if rec is None and _count_files(root, _MAX_FILES) > _MAX_FILES:
                logger.info("agent checkpoint skipped: %s has over %d files", root, _MAX_FILES)
                return {"root": str(root)} if root != ws else {}
            before = self.shadow.snapshot(root, f"before turn {request[:12]}")
            turn = {"session": session, "request": request, "dir": str(root), "workspace": str(ws),
                    "mode": "worktree" if rec else "checkpoint", "before": before, "after": None,
                    "files": [], "undone": False, "started_at": time.time()}
            if rec:
                turn["worktree"] = {k: rec[k] for k in ("repo", "path", "branch")}
            self._write(self._turn_path(session, request), turn)
            return {"root": str(root), "mode": turn["mode"], "worktree": turn.get("worktree")}

    def settle(self, session: str, request: str) -> dict[str, Any]:
        with self.lock:
            path = self._turn_path(session, request)
            turn = self._read(path)
            if not turn or not turn.get("before") or turn.get("undone"):
                return turn
            wd = Path(turn["dir"])
            after = self.shadow.snapshot(wd, f"after turn {request[:12]}")
            turn["after"] = after
            turn["files"] = self.shadow.changes(wd, turn["before"], after) if after and after != turn["before"] else []
            turn["settled_at"] = time.time()
            self._write(path, turn)
            return turn

    def has_turn(self, session: str, request: str) -> bool:
        return self._turn_path(session, request).exists()

    def describe(self, session: str, request: str) -> dict[str, Any]:
        turn = self._read(self._turn_path(session, request))
        if not turn:
            return {}
        if turn.get("mode") == "worktree" and not turn.get("applied") and not turn.get("undone"):
            rec = self.worktree(session) or {}
            if rec.get("applied_at", 0) > turn.get("settled_at", float("inf")):
                self._mark_applied(session, rec)   # applied before this record knew about Apply
                turn = self._read(self._turn_path(session, request))
        files = [{"path": f["path"], "status": f["status"]} for f in turn.get("files") or []]
        can, reason = False, ""
        applied = turn.get("applied")
        if files and not turn.get("undone") and turn.get("after") and applied:
            can, reason = self._checkout_matches(turn)
        elif files and not turn.get("undone") and turn.get("after"):
            wd = Path(turn["dir"])
            if not wd.is_dir():
                reason = "The folder this turn worked in is gone"
            elif self.shadow.tree_now(wd) != self.shadow.tree_of(wd, turn["after"]):
                reason = "Files changed after this turn; undo the later turn first"
            else:
                can = True
        return {"requestId": request, "safety": turn.get("mode"), "dir": turn.get("dir"),
                "worktree": turn.get("worktree"), "files": files, "undone": bool(turn.get("undone")),
                "canUndo": can, "undoBlocked": reason or None, "checkpoint": (turn.get("before") or "")[:12],
                "appliedTo": applied["dir"] if applied else None}

    def undo(self, session: str, request: str) -> dict[str, Any]:
        with self.lock:
            path = self._turn_path(session, request)
            turn = self._read(path)
            state = self.describe(session, request)
            if not state.get("canUndo"):
                raise ValueError(state.get("undoBlocked") or "Nothing to undo for this turn")
            wd = Path(turn["dir"])
            trash = self.state_root / "agent-undo-trash" / f"{time.strftime('%Y%m%d-%H%M%S')}-{request[:12]}"
            if turn.get("applied"):
                moved = self._undo_applied(turn, trash)
                turn.update(undone=True, undone_at=time.time(), undo_trash=str(trash) if moved else None)
                self._write(path, turn)
                return {**self.describe(session, request), "movedToTrash": str(trash) if moved else None}
            safety = self.shadow.snapshot(wd, f"before undo of {request[:12]}")
            added = [f["path"] for f in turn["files"] if f["status"] == "added"]
            others = [f["path"] for f in turn["files"] if f["status"] != "added"]
            for rel in added:
                src = wd / rel
                if src.exists() or src.is_symlink():
                    dst = trash / rel
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(src), str(dst))
            if others:
                self.shadow.restore_paths(wd, turn["before"], others)
            turn.update(undone=True, undone_at=time.time(), undo_safety=safety,
                        undo_trash=str(trash) if added else None)
            self._write(path, turn)
            return {**self.describe(session, request), "movedToTrash": str(trash) if added else None}
