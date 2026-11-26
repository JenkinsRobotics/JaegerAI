"""Headless Mineflayer Minecraft embodiment for 24/7 persistence & idle life.

Includes the MIT-licensed headless Node.js Mineflayer bridge adapted from
MetaGPT (`geekan/MetaGPT`, Voyager bridge) under ``./mineflayer/`` (~150 MB RAM,
0 GPU). Implements ``jaeger_contracts.EmbodimentPort`` so Jaeger learns multi-day
goal persistence, checkpointing, and graceful preemption using the exact same
body interface as the physical JP01 droid.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Mapping

MINEFLAYER_DIR = Path(__file__).resolve().parent / "mineflayer"


class MinecraftEmbodiment:
    """Headless Minecraft body backed by SQLite WAL multi-day goal & checkpoint state."""

    name = "minecraft_headless"

    def __init__(
        self,
        state_dir: Path,
        *,
        bridge_host: str = "127.0.0.1",
        bridge_port: int = 3000,
        mc_host: str = "127.0.0.1",
        mc_port: int = 25565,
    ) -> None:
        self._dir = Path(state_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._db = self._dir / "minecraft_embodiment.sqlite3"
        self._lock = threading.RLock()
        self._bridge_host = bridge_host
        self._bridge_port = int(bridge_port)
        self._mc_host = mc_host
        self._mc_port = int(mc_port)
        self._proc: subprocess.Popen[str] | None = None
        self._paused = True
        self._estop_latched = False
        self._estop_reason = ""
        self._state: dict[str, Any] = {
            "connected": False,
            "paused": True,
            "position": {"x": 0, "y": 64, "z": 0},
            "health": 20.0,
            "food": 20.0,
            "inventory": {},
            "active_goal": "Explore world, gather wood, and build a shelter",
            "day_count": 1,
            "last_action": "idle",
            "ticks": 0,
        }
        self._init_db()
        self._restore_latest_checkpoint()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db), timeout=10.0)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _init_db(self) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS mc_checkpoints (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    reason TEXT NOT NULL,
                    state_json TEXT NOT NULL,
                    created_at REAL NOT NULL
                )
                """
            )

    def _restore_latest_checkpoint(self) -> None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT state_json FROM mc_checkpoints ORDER BY id DESC LIMIT 1"
            ).fetchone()
        if row:
            try:
                saved = json.loads(row[0])
                if isinstance(saved, dict):
                    self._state.update(saved)
            except ValueError:
                pass

    def bridge_info(self) -> dict[str, Any]:
        entry = MINEFLAYER_DIR / "index.js"
        return {
            "mineflayer_dir": str(MINEFLAYER_DIR),
            "bridge_present": entry.is_file(),
            "node_available": bool(shutil.which("node")),
            "npm_installed": (MINEFLAYER_DIR / "node_modules").is_dir(),
            "bridge_url": f"http://{self._bridge_host}:{self._bridge_port}",
            "mc_target": f"{self._mc_host}:{self._mc_port}",
            "estimated_ram_mb": 150,
            "gpu_mb": 0,
        }

    def observe(self) -> Mapping[str, Any]:
        with self._lock:
            return {
                "embodiment": self.name,
                "paused": self._paused,
                "estop_latched": self._estop_latched,
                "estop_reason": self._estop_reason,
                "state": dict(self._state),
                "bridge": self.bridge_info(),
            }

    def act(self, action: str, params: Mapping[str, Any] | None = None) -> Mapping[str, Any]:
        with self._lock:
            if self._estop_latched:
                return {"ok": False, "error": f"estop_latched:{self._estop_reason}"}
            p = dict(params or {})
            self._paused = False
            self._state["paused"] = False
            self._state["ticks"] = int(self._state.get("ticks") or 0) + 1
            self._state["last_action"] = action
            if action == "set_goal" and p.get("goal"):
                self._state["active_goal"] = str(p["goal"])
            elif action == "move_to":
                pos = dict(self._state.get("position") or {"x": 0, "y": 64, "z": 0})
                for axis in ("x", "y", "z"):
                    if axis in p:
                        pos[axis] = int(p[axis])
                self._state["position"] = pos
            elif action == "gather" and p.get("item"):
                inv = dict(self._state.get("inventory") or {})
                item = str(p["item"])
                inv[item] = int(inv.get(item) or 0) + max(1, int(p.get("count", 1)))
                self._state["inventory"] = inv
            elif action == "idle_tick":
                self._state["day_count"] = max(1, 1 + (self._state["ticks"] // 240))
            return {"ok": True, "action": action, "state": dict(self._state)}

    def checkpoint(self, reason: str = "periodic") -> Mapping[str, Any]:
        now = time.time()
        with self._lock:
            snap = dict(self._state)
            with self._connect() as conn:
                cur = conn.execute(
                    "INSERT INTO mc_checkpoints (reason, state_json, created_at) VALUES (?, ?, ?)",
                    (reason, json.dumps(snap), now),
                )
                cid = int(cur.lastrowid or 0)
        return {"ok": True, "checkpoint_id": cid, "reason": reason, "timestamp": now, "state": snap}

    def pause(self, reason: str = "preempted") -> Mapping[str, Any]:
        """Immediately pause bot & persist checkpoint when Owner Work preempts Tier-3 idle life."""
        with self._lock:
            self._paused = True
            self._state["paused"] = True
            self._state["last_action"] = f"paused:{reason}"
        return self.checkpoint(reason=f"pause:{reason}")

    def estop(self, reason: str = "operator") -> Mapping[str, Any]:
        with self._lock:
            self._estop_latched = True
            self._estop_reason = reason
            self._paused = True
            self._state["paused"] = True
            if self._proc is not None and self._proc.poll() is None:
                self._proc.terminate()
                self._proc = None
        return self.checkpoint(reason=f"estop:{reason}")

    def release_estop(self) -> None:
        with self._lock:
            self._estop_latched = False
            self._estop_reason = ""

    def list_checkpoints(self, *, limit: int = 10) -> list[dict[str, Any]]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT id, reason, state_json, created_at FROM mc_checkpoints ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [
            {"id": int(r[0]), "reason": r[1], "state": json.loads(r[2] or "{}"), "created_at": float(r[3])}
            for r in rows
        ]


__all__ = ["MINEFLAYER_DIR", "MinecraftEmbodiment"]
