"""Standalone State & Memory engine implementing StateMemoryPort.

Synthesizes:
- agno (`offload/store.py`) + gemini-cli (`toolMaskingProcessor.ts`):
  disk-offloading oversized tool outputs into deterministic ``res_<hash12>``
  artifacts with compact preview envelopes and ReDoS-safe regex search.
- ag2 (`history.py`, `assembly.py`, `compact.py`):
  immutable history closing dangling tool calls + orphan-preserving boundaries
  + tiered compaction (prune/offload first, summarize only if needed).
- langgraph (`checkpoint/sqlite`):
  two-table WAL ``checkpoints`` + ``writes`` delta store + semantic key-value
  facts strictly under an external state directory (zero in-repo state!).
- cline (`checkpoint-hooks.ts`): fast isolated GIT_INDEX_FILE workspace snapshots.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .history import choose_boundary, close_dangling_tool_calls

# Heuristic for patterns prone to catastrophic regex backtracking (nested quantifiers).
_SUSPICIOUS_REGEX_RE = re.compile(r"\([^)]*[+*?][^)]*\)[+*{]")


def estimate_tokens(messages: Sequence[Mapping[str, Any]]) -> int:
    """Fast deterministic token estimator (~4 chars/token)."""
    total_chars = sum(len(json.dumps(m, default=str)) for m in messages)
    return max(1, total_chars // 4)


def deterministic_resource_id(tool_name: str, text: str) -> str:
    """Deterministic ``res_<sha256[:12]>`` identifier for an offloaded payload."""
    h = hashlib.sha256(f"{tool_name}\x00{text}".encode("utf-8", errors="replace")).hexdigest()[:12]
    return f"res_{h}"


class RegexTimeoutError(TimeoutError):
    """Raised when a user/model regex exceeds the ReDoS safety timeout."""


class ToolOutputOffloader:
    """Offloads oversized tool outputs to disk with compact preview + ReDoS-safe regex scan."""

    def __init__(
        self,
        state_dir: Path,
        *,
        max_inline_chars: int = 2000,
        preview_chars: int = 400,
        extra_dirs: Sequence[Path] = (),
        grep_timeout_s: float = 2.0,
    ) -> None:
        self._dir = state_dir.expanduser().resolve() / "offload"
        self._dir.mkdir(parents=True, exist_ok=True)
        allowed: list[Path] = [self._dir]
        for extra in extra_dirs:
            resolved_extra = Path(extra).expanduser().resolve()
            if resolved_extra not in allowed:
                allowed.append(resolved_extra)
        self._allowed_dirs = tuple(allowed)
        self._max_inline = max(128, int(max_inline_chars))
        self._preview = max(64, int(preview_chars))
        self._grep_timeout_s = max(0.2, float(grep_timeout_s))

    def maybe_offload(self, tool_name: str, text: str) -> tuple[str, str | None]:
        if len(text) <= self._max_inline:
            return text, None
        res_id = deterministic_resource_id(tool_name, text)
        path = self._dir / f"{tool_name}_{res_id}.txt"
        if not path.exists():
            path.write_text(text, encoding="utf-8")
        head = text[: self._preview]
        tail = text[-min(200, self._preview // 2) :]
        envelope = (
            f"[OFFLOADED {len(text)} chars id={res_id} -> {path}]\n"
            f"--- HEAD ---\n{head}\n--- TAIL ---\n{tail}\n"
            f"(Use search_offloaded_output on {path.name} to inspect specific lines.)"
        )
        return envelope, str(path)

    def _resolve_artifact(self, filename_or_path: str) -> Path | None:
        raw = str(filename_or_path or "").strip()
        if not raw:
            return None
        p = Path(raw).expanduser()
        if p.is_absolute():
            resolved = p.resolve()
            if any(d in resolved.parents for d in self._allowed_dirs) and resolved.is_file():
                return resolved
            return None
        for base in self._allowed_dirs:
            cand = (base / p.name).resolve()
            if base in cand.parents and cand.is_file():
                return cand
        # Also allow lookup by deterministic res_<hash12> id
        if raw.startswith("res_"):
            for base in self._allowed_dirs:
                for cand in base.glob(f"*{raw}*"):
                    resolved = cand.resolve()
                    if base in resolved.parents and resolved.is_file():
                        return resolved
        return None

    def _grep_subprocess(self, resolved: Path, pattern: str, max_matches: int, timeout_s: float) -> list[str]:
        """Execute potentially dangerous regex inside an isolated ``python -I`` subprocess with hard timeout."""
        worker = (
            "import json, pathlib, re, sys\n"
            "p = pathlib.Path(sys.argv[1])\n"
            "pat = sys.argv[2]\n"
            "lim = int(sys.argv[3])\n"
            "rx = re.compile(pat, re.IGNORECASE)\n"
            "out = []\n"
            "for idx, line in enumerate(p.read_text(encoding='utf-8', errors='replace').splitlines(), 1):\n"
            "    if len(line) > 1200:\n"
            "        for m in rx.finditer(line):\n"
            "            s = max(0, m.start() - 120); e = min(len(line), m.end() + 240)\n"
            "            pre = '...' if s > 0 else ''; suf = '...' if e < len(line) else ''\n"
            "            out.append(f'L{idx}@{m.start()}: {pre}{line[s:e]}{suf}')\n"
            "            if len(out) >= lim: break\n"
            "    elif rx.search(line):\n"
            "        out.append(f'L{idx}: {line}')\n"
            "    if len(out) >= lim: break\n"
            "sys.stdout.write(json.dumps(out))\n"
        )
        try:
            proc = subprocess.run(
                [sys.executable, "-I", "-B", "-c", worker, str(resolved), pattern, str(max_matches)],
                capture_output=True,
                text=True,
                timeout=timeout_s,
            )
        except subprocess.TimeoutExpired as exc:
            raise RegexTimeoutError(
                f"Regex search timed out after {timeout_s:.1f}s (possible ReDoS pattern: {pattern!r})"
            ) from exc
        if proc.returncode != 0:
            raise re.error(proc.stderr.strip() or "regex evaluation failed")
        return list(json.loads(proc.stdout or "[]"))

    def grep(
        self,
        filename_or_path: str,
        pattern: str,
        *,
        max_matches: int = 25,
        timeout_s: float | None = None,
    ) -> list[str]:
        resolved = self._resolve_artifact(filename_or_path)
        if resolved is None:
            raise FileNotFoundError(f"Offload artifact not found: {filename_or_path}")
        # Validate syntax early
        rx = re.compile(pattern, re.IGNORECASE)
        limit = max(1, int(max_matches))
        # Guard suspicious backtracking patterns or explicit tight timeout via isolated subprocess
        if _SUSPICIOUS_REGEX_RE.search(pattern) or timeout_s is not None:
            return self._grep_subprocess(
                resolved,
                pattern,
                limit,
                timeout_s if timeout_s is not None else self._grep_timeout_s,
            )

        matches: list[str] = []
        for idx, line in enumerate(
            resolved.read_text(encoding="utf-8", errors="replace").splitlines(),
            start=1,
        ):
            if len(line) > 1200:
                for m in rx.finditer(line):
                    start = max(0, m.start() - 120)
                    end = min(len(line), m.end() + 240)
                    prefix = "..." if start > 0 else ""
                    suffix = "..." if end < len(line) else ""
                    matches.append(f"L{idx}@{m.start()}: {prefix}{line[start:end]}{suffix}")
                    if len(matches) >= limit:
                        return matches
            elif rx.search(line):
                matches.append(f"L{idx}: {line}")
                if len(matches) >= limit:
                    break
        return matches


class SqliteStateMemory:
    """Unified StateMemoryPort: LangGraph two-table WAL checkpoints+writes, facts, offloading & compaction."""

    def __init__(
        self,
        state_dir: Path,
        *,
        summarizer: Callable[[Sequence[Mapping[str, Any]]], str] | None = None,
        max_inline_tool_chars: int = 2000,
    ) -> None:
        self._state_dir = state_dir.expanduser().resolve()
        self._state_dir.mkdir(parents=True, exist_ok=True)
        self._db_path = self._state_dir / "jaeger_memory.sqlite3"
        self._summarizer = summarizer
        self.offloader = ToolOutputOffloader(self._state_dir, max_inline_chars=max_inline_tool_chars)
        self._init_db()

    @property
    def name(self) -> str:
        return "jaeger_memory_sqlite"

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path))
        conn.execute("PRAGMA journal_mode=WAL;")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS checkpoints (
                    checkpoint_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    state_json TEXT NOT NULL,
                    created_at REAL NOT NULL
                )"""
            )
            conn.execute(
                """CREATE TABLE IF NOT EXISTS writes (
                    checkpoint_id TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    idx INTEGER NOT NULL,
                    channel TEXT NOT NULL,
                    value_json TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    PRIMARY KEY (checkpoint_id, task_id, idx)
                )"""
            )
            conn.execute(
                """CREATE TABLE IF NOT EXISTS facts (
                    subject TEXT NOT NULL,
                    key TEXT NOT NULL,
                    value TEXT NOT NULL,
                    category TEXT,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY (subject, key)
                )"""
            )

    def save_checkpoint(self, session_id: str, state: Mapping[str, Any]) -> str:
        cp_id = f"cp_{uuid.uuid4().hex[:12]}"
        payload = json.dumps(dict(state), default=str)
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO checkpoints(checkpoint_id, session_id, state_json, created_at) VALUES (?, ?, ?, ?)",
                (cp_id, session_id, payload, time.time()),
            )
        return cp_id

    def put_writes(
        self,
        checkpoint_id: str,
        task_id: str,
        writes: Sequence[tuple[str, Any]],
    ) -> None:
        """Append incremental delta writes for a checkpoint (LangGraph two-table WAL pattern)."""
        now = time.time()
        with self._connect() as conn:
            for idx, (channel, value) in enumerate(writes):
                conn.execute(
                    """INSERT OR REPLACE INTO writes(
                        checkpoint_id, task_id, idx, channel, value_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?)""",
                    (checkpoint_id, task_id, idx, str(channel), json.dumps(value, default=str), now),
                )

    def get_writes(self, checkpoint_id: str) -> list[dict[str, Any]]:
        """Read all recorded delta writes for ``checkpoint_id`` in deterministic order."""
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT task_id, idx, channel, value_json, created_at
                   FROM writes
                   WHERE checkpoint_id = ?
                   ORDER BY created_at ASC, task_id ASC, idx ASC""",
                (checkpoint_id,),
            ).fetchall()
        return [
            {
                "task_id": r[0],
                "idx": r[1],
                "channel": r[2],
                "value": json.loads(r[3]),
                "created_at": r[4],
            }
            for r in rows
        ]

    def load_checkpoint(self, checkpoint_id: str) -> Mapping[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT state_json FROM checkpoints WHERE checkpoint_id = ?",
                (checkpoint_id,),
            ).fetchone()
        return json.loads(row[0]) if row else None

    def load_checkpoint_with_writes(self, checkpoint_id: str) -> dict[str, Any] | None:
        """Load checkpoint state merged with any incremental delta writes."""
        base = self.load_checkpoint(checkpoint_id)
        if base is None:
            return None
        merged = dict(base)
        for w in self.get_writes(checkpoint_id):
            merged[w["channel"]] = w["value"]
        return merged

    def latest_checkpoint(self, session_id: str) -> Mapping[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT state_json FROM checkpoints WHERE session_id = ? ORDER BY created_at DESC LIMIT 1",
                (session_id,),
            ).fetchone()
        return json.loads(row[0]) if row else None

    def remember(self, key: str, value: str, *, subject: str = "user", category: str | None = None) -> None:
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO facts(subject, key, value, category, updated_at)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(subject, key) DO UPDATE SET
                     value=excluded.value, category=excluded.category, updated_at=excluded.updated_at""",
                (subject, key, value, category, time.time()),
            )

    def recall(self, key: str, *, subject: str = "user") -> str | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT value FROM facts WHERE subject = ? AND key = ?",
                (subject, key),
            ).fetchone()
        return row[0] if row else None

    def compact(self, messages: Sequence[Mapping[str, Any]], *, max_tokens: int) -> list[dict[str, Any]]:
        """Tiered compaction: (1) close dangling calls, (2) offload large tool results,
        (3) summarize middle turns on an orphan-preserving boundary."""
        msgs = close_dangling_tool_calls(messages)
        if estimate_tokens(msgs) <= max_tokens:
            return msgs

        # Tier 1: Offload verbose tool outputs (preserves prompt prefix & zero info loss)
        pruned: list[dict[str, Any]] = []
        for idx, m in enumerate(msgs):
            item = dict(m)
            if item.get("role") == "tool" and idx < len(msgs) - 2:
                content = str(item.get("content") or "")
                if len(content) > 256:
                    envelope, _ = self.offloader.maybe_offload(str(item.get("name") or "tool"), content)
                    item["content"] = envelope
            pruned.append(item)
        if estimate_tokens(pruned) <= max_tokens:
            return pruned

        # Tier 2: Preserve system prefix + orphan-safe recent tail, summarize middle turns
        system_msgs = [m for m in pruned if m.get("role") == "system"]
        non_system = [m for m in pruned if m.get("role") != "system"]
        middle, tail = choose_boundary(non_system, keep_recent=min(4, len(non_system)))
        if not middle:
            return pruned

        if self._summarizer is not None:
            summary_text = self._summarizer(middle)
        else:
            snippets = [f"{m.get('role')}: {str(m.get('content') or '')[:80]}" for m in middle[:6]]
            summary_text = f"[Compacted {len(middle)} earlier messages] " + " | ".join(snippets)

        return close_dangling_tool_calls([
            *system_msgs,
            {"role": "system", "content": summary_text, "compacted_count": len(middle)},
            *tail,
        ])


class GitCheckpointManager:
    """Fast isolated GIT_INDEX_FILE workspace snapshots & rollback (cline/opencode)."""

    def __init__(self, workspace: Path, state_dir: Path) -> None:
        self._ws = workspace.expanduser().resolve()
        self._git_dir = state_dir.expanduser().resolve() / "shadow_git"
        self._git_dir.mkdir(parents=True, exist_ok=True)
        self._env = {
            **os.environ,
            "GIT_DIR": str(self._git_dir),
            "GIT_WORK_TREE": str(self._ws),
            "GIT_INDEX_FILE": str(self._git_dir / "index"),
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_SYSTEM": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
        }
        if not (self._git_dir / "HEAD").exists():
            init_env = {
                k: v
                for k, v in self._env.items()
                if k not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE")
            }
            subprocess.run(
                ["git", "init", "--bare", str(self._git_dir)],
                env=init_env,
                check=True,
                capture_output=True,
            )

    def snapshot(self) -> str:
        """Capture current workspace tree into an immutable Git tree SHA."""
        subprocess.run(["git", "add", "-A"], env=self._env, cwd=str(self._ws), check=True, capture_output=True)
        proc = subprocess.run(
            ["git", "write-tree"], env=self._env, cwd=str(self._ws), check=True, capture_output=True, text=True
        )
        return proc.stdout.strip()

    def restore(self, tree_sha: str) -> None:
        """Restore workspace cleanly to a captured tree SHA."""
        subprocess.run(
            ["git", "read-tree", "--reset", "-u", tree_sha],
            env=self._env,
            cwd=str(self._ws),
            check=True,
            capture_output=True,
        )


__all__ = [
    "GitCheckpointManager",
    "RegexTimeoutError",
    "SqliteStateMemory",
    "ToolOutputOffloader",
    "close_dangling_tool_calls",
    "deterministic_resource_id",
    "estimate_tokens",
]
