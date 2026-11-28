"""Headless Mineflayer Minecraft embodiment for 24/7 persistence & idle life.

Includes the MIT-licensed headless Node.js Mineflayer bridge adapted from
MetaGPT (`geekan/MetaGPT`, Voyager bridge) under ``./mineflayer/`` (~150 MB RAM,
0 GPU). Runtime npm dependencies are installed outside the repository at
``<state_dir>/runtimes/mineflayer`` (zero in-repo runtime junk!).

Implements ``jaeger_contracts.EmbodimentPort`` with:
- Real Node.js Mineflayer bridge lifecycle (`ensure_bridge`, `connect`, `run_step`, `disconnect`)
- Real live position, health, food, inventory & biome sync when connected to a Minecraft server
- Graceful SQLite WAL checkpoint persistence and offline fallback when no server is running
- Immediate preemption & E-Stop teardown
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import sqlite3
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Mapping

MINEFLAYER_DIR = Path(__file__).resolve().parent / "mineflayer"


def _tcp_open(host: str, port: int, timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True
    except OSError:
        return False


class MinecraftEmbodiment:
    """Headless Minecraft body backed by SQLite WAL multi-day goal state & live Mineflayer bridge."""

    name = "minecraft_headless"

    def __init__(
        self,
        state_dir: Path,
        *,
        bridge_host: str = "127.0.0.1",
        bridge_port: int = 3000,
        mc_host: str | None = None,
        mc_port: int | None = None,
        username: str = "Jaeger",
    ) -> None:
        self._dir = Path(state_dir).expanduser().resolve()
        self._dir.mkdir(parents=True, exist_ok=True)
        self._db = self._dir / "minecraft_embodiment.sqlite3"
        self._lock = threading.RLock()
        self._bridge_host = bridge_host
        self._bridge_port = int(os.environ.get("JAEGER_MC_BRIDGE_PORT") or bridge_port)
        self._mc_host = (mc_host or os.environ.get("JAEGER_MC_HOST") or "127.0.0.1").strip()
        self._mc_port = int(mc_port or os.environ.get("JAEGER_MC_PORT") or 25565)
        self._username = (username or os.environ.get("JAEGER_MC_USERNAME") or "Jaeger").strip()
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
            "biome": "",
            "active_goal": "Explore world, gather wood, and build a shelter",
            "day_count": 1,
            "last_action": "idle",
            "last_error": "",
            "ticks": 0,
            "modes": {
                "self_preservation": {"enabled": True},
                "auto_eat": {"enabled": True},
                "self_defense": {"enabled": True},
                "unstuck": {"enabled": True},
                "follow_player": {"enabled": False, "target": None, "distance": 3},
                "guard_area": {"enabled": False, "anchor": None, "radius": 10},
            },
            "nearby_players": [],
            "chat_inbox": [],
        }
        self._last_chat_id = 0
        self._init_db()
        self._restore_latest_checkpoint()
        # Never claim connected across a process restart until re-verified.
        self._state["connected"] = False

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db), timeout=10.0)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _init_db(self) -> None:
        with self._lock, self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS mc_checkpoints (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    reason TEXT NOT NULL,
                    state_json TEXT NOT NULL,
                    created_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS mc_waypoints (
                    name TEXT PRIMARY KEY,
                    x INTEGER NOT NULL,
                    y INTEGER NOT NULL,
                    z INTEGER NOT NULL,
                    notes TEXT NOT NULL DEFAULT '',
                    updated_at REAL NOT NULL
                );
                """
            )

    def save_location(
        self,
        name: str,
        *,
        x: int | None = None,
        y: int | None = None,
        z: int | None = None,
        notes: str = "",
    ) -> dict[str, Any]:
        clean = str(name or "").strip().lower()
        if not clean:
            return {"ok": False, "error": "Waypoint name is required"}
        with self._lock:
            pos = dict(self._state.get("position") or {"x": 0, "y": 64, "z": 0})
            wx = int(pos["x"] if x is None else x)
            wy = int(pos["y"] if y is None else y)
            wz = int(pos["z"] if z is None else z)
            now = time.time()
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO mc_waypoints (name, x, y, z, notes, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (clean, wx, wy, wz, str(notes or "")[:200], now),
                )
        return {
            "ok": True,
            "waypoint": {"name": clean, "x": wx, "y": wy, "z": wz, "notes": str(notes or "")[:200], "updated_at": now},
        }

    def list_locations(self) -> list[dict[str, Any]]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT name, x, y, z, notes, updated_at FROM mc_waypoints ORDER BY name ASC"
            ).fetchall()
        return [
            {"name": r[0], "x": int(r[1]), "y": int(r[2]), "z": int(r[3]), "notes": r[4], "updated_at": float(r[5])}
            for r in rows
        ]

    def get_location(self, name: str) -> dict[str, Any] | None:
        clean = str(name or "").strip().lower()
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT name, x, y, z, notes, updated_at FROM mc_waypoints WHERE name = ?",
                (clean,),
            ).fetchone()
        if not row:
            return None
        return {"name": row[0], "x": int(row[1]), "y": int(row[2]), "z": int(row[3]), "notes": row[4], "updated_at": float(row[5])}

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

    def _resolve_runtime_dir(self) -> Path | None:
        """Prefer external runtime dir `<state_dir>/runtimes/mineflayer`, falling back to package dir."""
        ext = self._dir / "runtimes" / "mineflayer"
        if (ext / "index.js").is_file() and (ext / "node_modules").is_dir():
            return ext
        if (MINEFLAYER_DIR / "index.js").is_file() and (MINEFLAYER_DIR / "node_modules").is_dir():
            return MINEFLAYER_DIR
        return None

    def bridge_info(self) -> dict[str, Any]:
        runtime_dir = self._resolve_runtime_dir()
        entry = (runtime_dir / "index.js") if runtime_dir else (MINEFLAYER_DIR / "index.js")
        node_bin = shutil.which("node") or ("/opt/homebrew/bin/node" if Path("/opt/homebrew/bin/node").is_file() else "")
        return {
            "mineflayer_dir": str(runtime_dir or MINEFLAYER_DIR),
            "bridge_present": entry.is_file(),
            "node_available": bool(node_bin),
            "npm_installed": runtime_dir is not None,
            "bridge_running": _tcp_open(self._bridge_host, self._bridge_port, timeout=0.15),
            "server_reachable": _tcp_open(self._mc_host, self._mc_port, timeout=0.15),
            "bridge_url": f"http://{self._bridge_host}:{self._bridge_port}",
            "mc_target": f"{self._mc_host}:{self._mc_port}",
            "estimated_ram_mb": 150,
            "gpu_mb": 0,
        }

    def _bridge_get(self, path: str, *, timeout: float = 10.0) -> Any:
        url = f"http://{self._bridge_host}:{self._bridge_port}{path}"
        req = urllib.request.Request(
            url,
            headers={"Accept": "application/json"},
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return json.loads(raw) if raw.strip() else {}

    def _bridge_post(self, path: str, payload: Mapping[str, Any], *, timeout: float = 30.0) -> Any:
        url = f"http://{self._bridge_host}:{self._bridge_port}{path}"
        data = json.dumps(dict(payload)).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return json.loads(raw) if raw.strip() else {}

    def ensure_bridge(self, *, startup_timeout_s: float = 10.0) -> bool:
        """Start the headless Node.js Mineflayer HTTP bridge if not already listening."""
        if _tcp_open(self._bridge_host, self._bridge_port, timeout=0.2):
            return True
        runtime_dir = self._resolve_runtime_dir()
        node_bin = shutil.which("node") or ("/opt/homebrew/bin/node" if Path("/opt/homebrew/bin/node").is_file() else "")
        if runtime_dir is None or not node_bin:
            return False
        with self._lock:
            if self._proc is None or self._proc.poll() is not None:
                log_path = self._dir / "logs" / "mineflayer.log"
                log_path.parent.mkdir(parents=True, exist_ok=True)
                log_fh = log_path.open("a", encoding="utf-8")
                self._proc = subprocess.Popen(
                    [node_bin, "index.js", str(self._bridge_port)],
                    cwd=str(runtime_dir),
                    stdout=log_fh,
                    stderr=log_fh,
                    text=True,
                )
        deadline = time.monotonic() + max(2.0, float(startup_timeout_s))
        while time.monotonic() < deadline:
            if _tcp_open(self._bridge_host, self._bridge_port, timeout=0.25):
                return True
            if self._proc is not None and self._proc.poll() is not None:
                return False
            time.sleep(0.2)
        return False

    def _ingest_observation(self, obs_events: Any) -> None:
        """Sync live Mineflayer observation array (handling Voyager's JSON-stringified res.json) into self._state."""
        if isinstance(obs_events, str):
            try:
                obs_events = json.loads(obs_events)
            except ValueError:
                return
        if not isinstance(obs_events, list):
            return
        for item in obs_events:
            if not (isinstance(item, list) and len(item) == 2):
                continue
            kind, data = item[0], item[1]
            if not isinstance(data, dict):
                continue
            status_obj = data.get("status") if kind == "observe" and isinstance(data.get("status"), dict) else (data if kind == "status" else None)
            if isinstance(status_obj, dict):
                pos = status_obj.get("position")
                if isinstance(pos, dict):
                    self._state["position"] = {
                        "x": int(round(float(pos.get("x", 0)))),
                        "y": int(round(float(pos.get("y", 64)))),
                        "z": int(round(float(pos.get("z", 0)))),
                    }
                if "health" in status_obj:
                    self._state["health"] = float(status_obj["health"])
                if "food" in status_obj:
                    self._state["food"] = float(status_obj["food"])
                if "biome" in status_obj:
                    self._state["biome"] = str(status_obj["biome"])
            inv_obj = data.get("inventory") if kind == "observe" and isinstance(data.get("inventory"), dict) else (data if kind == "inventory" else None)
            if isinstance(inv_obj, dict):
                self._state["inventory"] = {str(k): int(v) for k, v in inv_obj.items() if isinstance(v, (int, float))}

    def connect(
        self,
        *,
        mc_host: str | None = None,
        mc_port: int | None = None,
        username: str | None = None,
    ) -> dict[str, Any]:
        """Connect Mineflayer bot to the configured Minecraft Java server."""
        with self._lock:
            if self._estop_latched:
                return {"ok": False, "error": f"estop_latched:{self._estop_reason}"}
            if mc_host:
                self._mc_host = str(mc_host).strip()
            if mc_port:
                self._mc_port = int(mc_port)
            if username:
                self._username = str(username).strip()
        if not self.ensure_bridge():
            return {
                "ok": False,
                "error": "mineflayer_bridge_unavailable (install runtime deps under ~/.jaeger/runtimes/mineflayer)",
                "bridge": self.bridge_info(),
            }
        if not _tcp_open(self._mc_host, self._mc_port, timeout=1.0):
            return {
                "ok": False,
                "error": f"minecraft_server_unreachable at {self._mc_host}:{self._mc_port}",
                "bridge": self.bridge_info(),
            }
        try:
            obs = self._bridge_post(
                "/start",
                {
                    "host": self._mc_host,
                    "port": self._mc_port,
                    "username": self._username,
                    "waitTicks": 10,
                },
                timeout=35.0,
            )
            with self._lock:
                self._state["connected"] = True
                self._state["paused"] = False
                self._paused = False
                self._state["last_action"] = "connected"
                self._state["last_error"] = ""
                self._ingest_observation(obs)
            self.checkpoint(reason="connected")
            return {"ok": True, "connected": True, "state": dict(self._state)}
        except (urllib.error.URLError, urllib.error.HTTPError, OSError, ValueError) as exc:
            with self._lock:
                self._state["connected"] = False
                self._state["last_error"] = str(exc)[:240]
            return {"ok": False, "connected": False, "error": str(exc)[:240]}

    def disconnect(self) -> dict[str, Any]:
        """Gracefully disconnect bot from Minecraft server."""
        try:
            if _tcp_open(self._bridge_host, self._bridge_port, timeout=0.25):
                self._bridge_post("/stop", {}, timeout=5.0)
        except Exception:  # noqa: BLE001
            pass
        with self._lock:
            self._state["connected"] = False
            self._paused = True
            self._state["paused"] = True
            self._state["last_action"] = "disconnected"
        self.checkpoint(reason="disconnect")
        return {"ok": True, "connected": False}

    def run_step(self, code: str, *, programs: str = "") -> dict[str, Any]:
        """Execute a Mineflayer JS step on the live connected bot and sync observations."""
        with self._lock:
            if self._estop_latched:
                return {"ok": False, "error": f"estop_latched:{self._estop_reason}"}
            if not self._state.get("connected"):
                return {"ok": False, "error": "not_connected"}
        try:
            obs = self._bridge_post("/step", {"code": code, "programs": programs}, timeout=45.0)
            with self._lock:
                self._state["ticks"] = int(self._state.get("ticks") or 0) + 1
                self._state["day_count"] = max(1, 1 + (self._state["ticks"] // 240))
                self._state["last_action"] = "step"
                self._state["last_error"] = ""
                self._ingest_observation(obs)
            return {"ok": True, "live": True, "state": dict(self._state)}
        except (urllib.error.URLError, urllib.error.HTTPError, OSError, ValueError) as exc:
            with self._lock:
                self._state["connected"] = False
                self._state["last_error"] = str(exc)[:240]
            return {"ok": False, "live": False, "error": str(exc)[:240]}

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

    def get_radar(self, *, radius: int = 8) -> dict[str, Any]:
        """Fetch a lightweight 0-GPU live top-down terrain/entity/player radar slice."""
        with self._lock:
            live = bool(self._state.get("connected"))
            snap = dict(self._state)
        if not live:
            return {
                "ok": True,
                "connected": False,
                "radius": max(4, min(int(radius), 10)),
                "bot": {
                    "username": self._username,
                    **(snap.get("position") or {"x": 0, "y": 64, "z": 0}),
                    "health": snap.get("health", 20.0),
                    "food": snap.get("food", 20.0),
                    "biome": snap.get("biome", ""),
                },
                "grid": [],
                "entities": [],
                "nearby_players": list(snap.get("nearby_players") or []),
                "inventory": dict(snap.get("inventory") or {}),
                "modes": dict(snap.get("modes") or {}),
                "chat_inbox": list(snap.get("chat_inbox") or [])[-10:],
            }
        try:
            r = max(4, min(int(radius), 10))
            data = self._bridge_get(f"/radar?radius={r}", timeout=6.0)
            if isinstance(data, dict):
                with self._lock:
                    if isinstance(data.get("nearby_players"), list):
                        self._state["nearby_players"] = data["nearby_players"]
                    if isinstance(data.get("modes"), dict):
                        self._state["modes"] = data["modes"]
                    if isinstance(data.get("inventory"), dict):
                        self._state["inventory"] = data["inventory"]
                    if isinstance(data.get("bot"), dict):
                        b = data["bot"]
                        self._state["position"] = {"x": int(b.get("x", 0)), "y": int(b.get("y", 64)), "z": int(b.get("z", 0))}
                        if "health" in b:
                            self._state["health"] = float(b["health"])
                        if "food" in b:
                            self._state["food"] = float(b["food"])
                return data
        except (urllib.error.URLError, urllib.error.HTTPError, OSError, ValueError) as exc:
            return {"ok": False, "connected": False, "error": str(exc)[:200]}
        return {"ok": False, "connected": False, "error": "empty_radar"}

    def poll_chat_inbox(self, *, since_id: int | None = None) -> dict[str, Any]:
        """Poll inbound player chat messages & nearby players from the live Mineflayer bridge."""
        with self._lock:
            live = bool(self._state.get("connected"))
            cursor = self._last_chat_id if since_id is None else int(since_id)
        if not live:
            with self._lock:
                return {
                    "ok": True,
                    "live": False,
                    "last_id": self._last_chat_id,
                    "messages": list(self._state.get("chat_inbox") or []),
                    "nearby_players": list(self._state.get("nearby_players") or []),
                }
        try:
            data = self._bridge_get(f"/chat-inbox?since_id={cursor}", timeout=8.0)
            msgs = list(data.get("messages") or [])
            players = list(data.get("nearby_players") or [])
            last_id = int(data.get("last_id") or cursor)
            with self._lock:
                self._last_chat_id = max(self._last_chat_id, last_id)
                self._state["nearby_players"] = players
                if msgs:
                    inbox = list(self._state.get("chat_inbox") or []) + msgs
                    self._state["chat_inbox"] = inbox[-30:]
            return {
                "ok": True,
                "live": True,
                "last_id": last_id,
                "messages": msgs,
                "nearby_players": players,
            }
        except (urllib.error.URLError, urllib.error.HTTPError, OSError, ValueError) as exc:
            return {"ok": False, "live": True, "error": str(exc)[:240], "messages": [], "nearby_players": []}

    def _run_coop_bridge(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        try:
            res = self._bridge_post("/coop", payload, timeout=45.0)
            with self._lock:
                if res.get("observation") is not None:
                    self._ingest_observation(res["observation"])
                if isinstance(res.get("modes"), dict) and isinstance(res["modes"].get("modes"), dict):
                    self._state["modes"] = res["modes"]["modes"]
                if isinstance(res.get("nearby_players"), list):
                    self._state["nearby_players"] = res["nearby_players"]
                self._state["last_error"] = "" if res.get("ok") else str(res.get("summary") or res.get("error") or "")
            return {
                "ok": bool(res.get("ok")),
                "live": True,
                "summary": str(res.get("summary") or ""),
                "nearby_players": res.get("nearby_players") or [],
                "modes": self._state.get("modes") or {},
                "state": dict(self._state),
            }
        except (urllib.error.URLError, urllib.error.HTTPError, OSError, ValueError) as exc:
            with self._lock:
                self._state["last_error"] = str(exc)[:240]
            return {"ok": False, "live": True, "error": str(exc)[:240]}

    def act(self, action: str, params: Mapping[str, Any] | None = None) -> Mapping[str, Any]:
        p = dict(params or {})
        if action == "connect":
            return self.connect(
                mc_host=p.get("host"),
                mc_port=int(p["port"]) if p.get("port") else None,
                username=p.get("username"),
            )
        if action == "disconnect":
            return self.disconnect()
        if action == "step":
            return self.run_step(str(p.get("code") or ""), programs=str(p.get("programs") or ""))
        if action == "read_chat":
            since = int(p["since_id"]) if p.get("since_id") is not None else None
            return self.poll_chat_inbox(since_id=since)
        if action == "save_location":
            return self.save_location(
                str(p.get("name") or p.get("location") or ""),
                x=int(p["x"]) if p.get("x") is not None else None,
                y=int(p["y"]) if p.get("y") is not None else None,
                z=int(p["z"]) if p.get("z") is not None else None,
                notes=str(p.get("notes") or ""),
            )
        if action == "list_locations":
            locs = self.list_locations()
            return {"ok": True, "locations": locs, "count": len(locs)}
        if action == "goto_location":
            loc = self.get_location(str(p.get("name") or p.get("location") or ""))
            if loc is None:
                return {"ok": False, "error": f"Unknown waypoint: {p.get('name') or p.get('location')}"}
            return self.act("move_to", {"x": loc["x"], "y": loc["y"], "z": loc["z"]})
        if action == "join_guide":
            if _tcp_open(self._bridge_host, self._bridge_port, timeout=0.25):
                try:
                    return self._bridge_get(f"/join-guide?java_port={self._mc_port}&bedrock_port={int(p.get('bedrock_port') or 19132)}", timeout=5.0)
                except Exception:  # noqa: BLE001
                    pass
            return {
                "ok": True,
                "guide": {
                    "java": {"address": f"{self._mc_host}:{self._mc_port}"},
                    "bedrock": {"port": int(p.get("bedrock_port") or 19132)},
                },
                "available_blueprints": ["shelter", "monument", "farm", "town_hall"],
            }
        if action == "lan_broadcast":
            enabled = bool(p.get("enabled", True))
            if _tcp_open(self._bridge_host, self._bridge_port, timeout=0.25):
                try:
                    return self._bridge_post("/lan-broadcast", {**p, "enabled": enabled}, timeout=5.0)
                except Exception as exc:  # noqa: BLE001
                    return {"ok": False, "error": str(exc)[:200]}
            return {"ok": False, "error": "mineflayer_bridge_not_running"}

        with self._lock:
            if self._estop_latched:
                return {"ok": False, "error": f"estop_latched:{self._estop_reason}"}
            live = bool(self._state.get("connected"))
            self._paused = False
            self._state["paused"] = False
            self._state["ticks"] = int(self._state.get("ticks") or 0) + 1
            self._state["last_action"] = action

        if live:
            if action == "set_mode":
                mode_name = str(p.get("mode") or "").strip()
                enabled = bool(p.get("enabled", True))
                body: dict[str, Any] = {"mode": mode_name, "enabled": enabled}
                if p.get("player") or p.get("target"):
                    body["target"] = str(p.get("player") or p.get("target"))
                if p.get("distance") is not None:
                    body["distance"] = int(p["distance"])
                try:
                    res = self._bridge_post("/modes", body, timeout=10.0)
                    with self._lock:
                        if isinstance(res.get("modes"), dict):
                            self._state["modes"] = res["modes"]
                    return {"ok": bool(res.get("ok")), "live": True, "modes": self._state.get("modes"), "state": dict(self._state)}
                except (urllib.error.URLError, urllib.error.HTTPError, OSError, ValueError) as exc:
                    return {"ok": False, "live": True, "error": str(exc)[:240]}
            if action in (
                "follow_player", "go_to_player", "give_to_player", "eat", "go_to_bed",
                "nearby_players", "stop_actions", "guard_area", "build_blueprint",
            ):
                return self._run_coop_bridge({**p, "action": action})
            if action == "move_to":
                pos = dict(self._state.get("position") or {"x": 0, "y": 64, "z": 0})
                x = int(p.get("x", pos["x"]))
                y = int(p.get("y", pos["y"]))
                z = int(p.get("z", pos["z"]))
                js = f"await bot.pathfinder.goto(new GoalNear({x}, {y}, {z}, 1));"
                return self.run_step(js)
            if action == "chat" and p.get("message"):
                msg = json.dumps(str(p["message"])[:200])
                return self.run_step(f"bot.chat({msg});")
            if action == "gather" and p.get("item"):
                return self._run_coop_bridge({
                    "action": "collect_blocks",
                    "item": str(p["item"]),
                    "count": max(1, min(int(p.get("count", 1)), 16)),
                })
            if action == "idle_tick":
                # Gentle autonomous exploration step around current coordinates
                pos = self._state.get("position") or {"x": 0, "y": 64, "z": 0}
                dx = 4 if (int(self._state["ticks"]) % 2 == 0) else -4
                js = f"await bot.pathfinder.goto(new GoalNearXZ({int(pos['x']) + dx}, {int(pos['z']) + 2}, 2));"
                res = self.run_step(js)
                if res.get("ok"):
                    return {**res, "acted": True, "summary": f"Explored to {res['state']['position']}"}
                return {**res, "acted": False}

        with self._lock:
            if action == "set_goal" and p.get("goal"):
                self._state["active_goal"] = str(p["goal"])
            elif action == "set_mode" and p.get("mode"):
                modes = dict(self._state.get("modes") or {})
                mname = str(p["mode"]).strip()
                entry = dict(modes.get(mname) or {})
                entry["enabled"] = bool(p.get("enabled", True))
                if p.get("player") or p.get("target"):
                    entry["target"] = str(p.get("player") or p.get("target"))
                if p.get("distance") is not None:
                    entry["distance"] = int(p["distance"])
                modes[mname] = entry
                self._state["modes"] = modes
            elif action == "follow_player":
                target = str(p.get("player") or p.get("username") or "").strip()
                modes = dict(self._state.get("modes") or {})
                modes["follow_player"] = {"enabled": True, "target": target or None, "distance": int(p.get("distance") or 3)}
                self._state["modes"] = modes
            elif action == "guard_area":
                pos = dict(self._state.get("position") or {"x": 0, "y": 64, "z": 0})
                anchor = {
                    "x": int(p.get("x", pos["x"])),
                    "y": int(p.get("y", pos["y"])),
                    "z": int(p.get("z", pos["z"])),
                }
                modes = dict(self._state.get("modes") or {})
                modes["guard_area"] = {"enabled": True, "anchor": anchor, "radius": int(p.get("radius") or 10)}
                modes["follow_player"] = {"enabled": False, "target": None, "distance": 3}
                self._state["modes"] = modes
            elif action == "stop_actions":
                modes = dict(self._state.get("modes") or {})
                modes["follow_player"] = {"enabled": False, "target": None, "distance": 3}
                modes["guard_area"] = {"enabled": False, "anchor": None, "radius": 10}
                self._state["modes"] = modes
            elif action == "eat":
                self._state["food"] = 20.0
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
            return {"ok": True, "live": False, "acted": False, "action": action, "state": dict(self._state)}

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
            self._state["connected"] = False
            self._terminate_bridge_locked()
        return self.checkpoint(reason=f"estop:{reason}")

    def _terminate_bridge_locked(self) -> None:
        if self._proc is not None and self._proc.poll() is None:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=2.0)
            except Exception:  # noqa: BLE001
                try:
                    self._proc.kill()
                except Exception:  # noqa: BLE001
                    pass
        self._proc = None

    def close(self) -> None:
        with self._lock:
            self._terminate_bridge_locked()

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
