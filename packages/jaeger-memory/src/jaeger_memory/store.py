"""Standalone State & Memory engine implementing StateMemoryPort.

Synthesizes:
- agno (`offload/store.py`) + gemini-cli (`toolMaskingProcessor.ts`):
  disk-offloading oversized tool outputs into compact preview envelopes with
  grep-able regex scan access before any lossy summarization.
- ag2 (`history.py`, `assembly.py`, `compact.py`):
  immutable history closing dangling tool calls + pure composable AssemblyPolicy
  pipeline + tiered compaction (prune/offload first, summarize only if needed).
- langgraph (`checkpoint/base`) + JaegerAI (`memory/port.py`):
  durable SQLite checkpointing + semantic key-value memory strictly under an
  external state directory (zero in-repo state!).
- cline (`checkpoint-hooks.ts`): fast isolated GIT_INDEX_FILE workspace snapshots.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence


def estimate_tokens(messages: Sequence[Mapping[str, Any]]) -> int:
    """Fast deterministic token estimator (~4 chars/token)."""
    total_chars = sum(len(json.dumps(m, default=str)) for m in messages)
    return max(1, total_chars // 4)


class ToolOutputOffloader:
    """Offloads oversized tool outputs to disk with compact preview + regex scan (agno)."""

    def __init__(self, state_dir: Path, *, max_inline_chars: int = 2000, preview_chars: int = 400) -> None:
        self._dir = state_dir.expanduser().resolve() / "offload"
        self._dir.mkdir(parents=True, exist_ok=True)
        self._max_inline = max(128, int(max_inline_chars))
        self._preview = max(64, int(preview_chars))

    def maybe_offload(self, tool_name: str, text: str) -> tuple[str, str | None]:
        if len(text) <= self._max_inline:
            return text, None
        digest = hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:12]
        path = self._dir / f"{tool_name}_{digest}.txt"
        path.write_text(text, encoding="utf-8")
        head = text[: self._preview]
        tail = text[-min(200, self._preview // 2) :]
        envelope = (
            f"[OFFLOADED {len(text)} chars -> {path}]\n"
            f"--- HEAD ---\n{head}\n--- TAIL ---\n{tail}\n"
            f"(Use search_offloaded_output on {path.name} to inspect specific lines.)"
        )
        return envelope, str(path)

    def grep(self, filename_or_path: str, pattern: str, *, max_matches: int = 25) -> list[str]:
        p = Path(filename_or_path)
        if not p.is_absolute():
            p = self._dir / p.name
        resolved = p.resolve()
        if self._dir not in resolved.parents or not resolved.is_file():
            raise FileNotFoundError(f"Offload artifact not found: {filename_or_path}")
        rx = re.compile(pattern, re.IGNORECASE)
        matches: list[str] = []
        for idx, line in enumerate(resolved.read_text(encoding="utf-8").splitlines(), start=1):
            if rx.search(line):
                matches.append(f"L{idx}: {line}")
                if len(matches) >= max_matches:
                    break
        return matches


def close_dangling_tool_calls(messages: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Ensure every assistant tool_call has a matching tool result (ag2 History invariant)."""
    out = [dict(m) for m in messages]
    answered = {
        m.get("tool_call_id")
        for m in out
        if m.get("role") == "tool" and m.get("tool_call_id")
    }
    patched: list[dict[str, Any]] = []
    for m in out:
        patched.append(m)
        if m.get("role") == "assistant" and isinstance(m.get("tool_calls"), list):
            for tc in m["tool_calls"]:
                tc_id = tc.get("id") if isinstance(tc, Mapping) else None
                if tc_id and tc_id not in answered:
                    patched.append({
                        "role": "tool",
                        "tool_call_id": tc_id,
                        "content": "[interrupted: tool call did not complete before checkpoint]",
                    })
                    answered.add(tc_id)
    return patched


class SqliteStateMemory:
    """Unified StateMemoryPort combining SQLite checkpoints, facts, offloading & tiered compaction."""

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

    def load_checkpoint(self, checkpoint_id: str) -> Mapping[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT state_json FROM checkpoints WHERE checkpoint_id = ?",
                (checkpoint_id,),
            ).fetchone()
        return json.loads(row[0]) if row else None

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
        (3) summarize middle turns while keeping system prompt & recent tail intact."""
        msgs = close_dangling_tool_calls(messages)
        if estimate_tokens(msgs) <= max_tokens:
            return msgs

        # Tier 1: Offload verbose tool outputs (preserves prompt prefix & zero info loss!)
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

        # Tier 2: Preserve system prefix + recent tail, summarize middle turns
        system_msgs = [m for m in pruned if m.get("role") == "system"]
        non_system = [m for m in pruned if m.get("role") != "system"]
        keep_tail = min(4, len(non_system))
        middle = non_system[: len(non_system) - keep_tail]
        tail = non_system[len(non_system) - keep_tail :]
        if not middle:
            return pruned

        if self._summarizer is not None:
            summary_text = self._summarizer(middle)
        else:
            snippets = [f"{m.get('role')}: {str(m.get('content') or '')[:80]}" for m in middle[:6]]
            summary_text = f"[Compacted {len(middle)} earlier messages] " + " | ".join(snippets)

        return [
            *system_msgs,
            {"role": "system", "content": summary_text, "compacted_count": len(middle)},
            *tail,
        ]


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
        }
        if not (self._git_dir / "HEAD").exists():
            subprocess.run(["git", "init", "--bare", str(self._git_dir)], check=True, capture_output=True)

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
