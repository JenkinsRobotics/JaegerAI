"""SQLite WAL Lifelong Minecraft Skill Library (Voyager MIT pattern, zero vector-DB daemon).

Loads the 11 MIT-licensed MineDojo/Voyager JS control primitives from
``./control_primitives/`` and stores newly authored, verified JS skills in
SQLite WAL so Jaeger retains every learned Minecraft ability across restarts
and multi-day Episode 02 sessions.
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

CONTROL_PRIMITIVES_DIR = Path(__file__).resolve().parent / "control_primitives"
_TOK_RE = re.compile(r"[a-z0-9_]{2,}")


@dataclass(slots=True)
class MinecraftSkill:
    name: str
    description: str
    code: str
    version: int
    verified_runs: int
    tags: list[str]
    updated_at: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_control_primitives() -> dict[str, str]:
    """Load bundled MIT Voyager JS control primitives from disk."""
    out: dict[str, str] = {}
    if not CONTROL_PRIMITIVES_DIR.is_dir():
        return out
    for js in sorted(CONTROL_PRIMITIVES_DIR.glob("*.js")):
        out[js.stem] = js.read_text(encoding="utf-8")
    return out


class MinecraftSkillLibrary:
    """Persistent SQLite WAL skill store with lightweight lexical scoring (0 MB external DB)."""

    def __init__(self, state_dir: Path) -> None:
        self._dir = Path(state_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._db = self._dir / "minecraft_skills.sqlite3"
        self._lock = threading.RLock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db), timeout=10.0)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _init_db(self) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS mc_skills (
                    name TEXT PRIMARY KEY,
                    description TEXT NOT NULL,
                    code TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    verified_runs INTEGER NOT NULL,
                    tags_json TEXT NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )

    def upsert_skill(
        self,
        *,
        name: str,
        description: str,
        code: str,
        tags: list[str] | None = None,
        verified: bool = True,
    ) -> MinecraftSkill:
        clean = re.sub(r"[^A-Za-z0-9_]", "_", (name or "skill").strip())
        now = time.time()
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT version, verified_runs FROM mc_skills WHERE name = ?",
                (clean,),
            ).fetchone()
            ver = (int(row[0]) + 1) if row else 1
            runs = (int(row[1]) + (1 if verified else 0)) if row else (1 if verified else 0)
            skill = MinecraftSkill(
                name=clean,
                description=description.strip(),
                code=code,
                version=ver,
                verified_runs=runs,
                tags=list(tags or []),
                updated_at=now,
            )
            conn.execute(
                """
                INSERT INTO mc_skills (name, description, code, version, verified_runs, tags_json, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    description=excluded.description,
                    code=excluded.code,
                    version=excluded.version,
                    verified_runs=excluded.verified_runs,
                    tags_json=excluded.tags_json,
                    updated_at=excluded.updated_at
                """,
                (skill.name, skill.description, skill.code, skill.version, skill.verified_runs, json.dumps(skill.tags), now),
            )
            return skill

    def list_skills(self) -> list[MinecraftSkill]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT name, description, code, version, verified_runs, tags_json, updated_at FROM mc_skills ORDER BY verified_runs DESC, updated_at DESC"
            ).fetchall()
        return [
            MinecraftSkill(
                name=r[0],
                description=r[1],
                code=r[2],
                version=int(r[3]),
                verified_runs=int(r[4]),
                tags=json.loads(r[5] or "[]"),
                updated_at=float(r[6]),
            )
            for r in rows
        ]

    def retrieve(self, query: str, *, top_k: int = 5) -> list[MinecraftSkill]:
        q_toks = set(_TOK_RE.findall((query or "").lower()))
        skills = self.list_skills()
        if not q_toks:
            return skills[:top_k]
        scored: list[tuple[float, MinecraftSkill]] = []
        for sk in skills:
            hay = set(_TOK_RE.findall(f"{sk.name} {sk.description} {' '.join(sk.tags)}".lower()))
            overlap = len(q_toks & hay)
            if overlap > 0:
                score = overlap + min(2.0, sk.verified_runs * 0.1)
                scored.append((score, sk))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [sk for _, sk in scored[:top_k]]


__all__ = ["CONTROL_PRIMITIVES_DIR", "MinecraftSkill", "MinecraftSkillLibrary", "load_control_primitives"]
