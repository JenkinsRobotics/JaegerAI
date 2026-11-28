"""Living Avatar integration (ported from origin/jaeger-avatar into standalone jaeger-avatar).

Launches the optional sibling JaegerAvatar app (Vita by default; override path with
`JAEGER_AVATAR_HOME`, port with `JAEGER_AVATAR_PORT`, default 8791 to avoid colliding
with the Gateway WebUI on 8790) and speaks `avatar-control/v1` over localhost:
`feel`, `react`, `act`, `gaze`, `stop`, and `state`.
"""

from __future__ import annotations

import json
import os
import secrets
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

__all__ = [
    "AvatarLink",
    "DEFAULT_AVATAR_PORT",
    "DEFAULT_FACE",
    "avatar_app_serving",
    "launch_avatar_app",
]

DEFAULT_FACE = "vita"
DEFAULT_AVATAR_PORT = 8791


def _default_avatar_home() -> Path:
    env_home = (os.environ.get("JAEGER_AVATAR_HOME") or "").strip()
    if env_home:
        return Path(env_home).expanduser()
    for cand in (Path.home() / "GitHub" / "JaegerAvatar", Path.home() / "GITHUB" / "JaegerAvatar"):
        if cand.is_dir():
            return cand
    return Path.home() / "GitHub" / "JaegerAvatar"


def _state_file(state_dir: Path | None = None) -> Path:
    if state_dir is not None:
        return Path(state_dir).expanduser().resolve() / "avatar_link.json"
    env_state = (os.environ.get("JAEGER_STATE_DIR") or "").strip()
    base = Path(env_state).expanduser() if env_state else (Path.home() / ".jaeger")
    return base / "avatar_link.json"


def _get_json(url: str, timeout: float = 1.5) -> Any:
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", errors="replace"))


def avatar_app_serving(port: int | None = None) -> bool:
    """Return True if the sibling JaegerAvatar stage answers on localhost."""
    p = int(port or os.environ.get("JAEGER_AVATAR_PORT") or DEFAULT_AVATAR_PORT)
    try:
        return bool(_get_json(f"http://127.0.0.1:{p}/health", timeout=1.0))
    except (OSError, ValueError):
        return False


def launch_avatar_app(
    *,
    face: str = DEFAULT_FACE,
    port: int | None = None,
    browser: bool = False,
    wait_s: int = 120,
    state_dir: Path | None = None,
) -> str:
    """Launch JaegerAvatar if not already serving and return its stage URL."""
    home = _default_avatar_home()
    p = int(port or os.environ.get("JAEGER_AVATAR_PORT") or DEFAULT_AVATAR_PORT)
    if not (home / "main.py").is_file():
        raise FileNotFoundError(f"JaegerAvatar not found at {home} (set JAEGER_AVATAR_HOME)")
    if not avatar_app_serving(p):
        token = (os.environ.get("JAEGER_AVATAR_CONTROL_TOKEN") or "").strip() or secrets.token_urlsafe(18)
        sf = _state_file(state_dir)
        sf.parent.mkdir(parents=True, exist_ok=True)
        sf.write_text(json.dumps({"url": f"http://127.0.0.1:{p}", "token": token}, indent=2) + "\n", encoding="utf-8")
        subprocess.Popen(
            ["python3", str(home / "main.py"), "--port", str(p), *(["--browser"] if browser else [])],
            cwd=str(home),
            env={**os.environ, "JAEGER_AVATAR_CONTROL_TOKEN": token},
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        deadline = time.time() + max(5, int(wait_s))
        while not avatar_app_serving(p):
            if time.time() > deadline:
                raise TimeoutError(f"JaegerAvatar did not answer on :{p} within {wait_s}s")
            time.sleep(0.5)
    return f"http://127.0.0.1:{p}/?face={face}"


class AvatarLink:
    """`avatar-control/v1` client to drive emotion, reactions, actions & gaze on the living stage."""

    def __init__(
        self,
        url: str | None = None,
        token: str | None = None,
        *,
        state_dir: Path | None = None,
    ) -> None:
        remembered: dict[str, Any] = {}
        sf = _state_file(state_dir)
        for cand in (sf, Path.home() / ".jaeger_ai" / "avatar.json"):
            try:
                if cand.is_file():
                    remembered = json.loads(cand.read_text(encoding="utf-8"))
                    break
            except (OSError, ValueError):
                continue
        default_port = int(os.environ.get("JAEGER_AVATAR_PORT") or DEFAULT_AVATAR_PORT)
        self.url = (url or remembered.get("url") or f"http://127.0.0.1:{default_port}").rstrip("/")
        self.token = (token or os.environ.get("JAEGER_AVATAR_CONTROL_TOKEN") or remembered.get("token") or "").strip()

    def is_alive(self) -> bool:
        try:
            return bool(_get_json(f"{self.url}/health", timeout=0.5))
        except (OSError, ValueError):
            return False

    def command(self, op: str, value: Any = None, ttl_ms: int = 5000) -> Any:
        body = json.dumps({"op": op, "value": value, "ttl_ms": ttl_ms}).encode("utf-8")
        req = urllib.request.Request(
            f"{self.url}/control",
            data=body,
            headers={"Content-Type": "application/json", "X-Avatar-Token": self.token},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=3.0) as r:
                return json.loads(r.read().decode("utf-8", errors="replace"))
        except urllib.error.HTTPError as exc:
            try:
                msg = json.loads(exc.read().decode("utf-8", errors="replace")).get("error", str(exc))
            except Exception:  # noqa: BLE001
                msg = str(exc)
            raise RuntimeError(msg) from None

    def feel(self, emotion: str, ttl_ms: int = 30000) -> Any:
        return self.command("emotion", emotion, ttl_ms)

    def react(self, name: str) -> Any:
        return self.command("reaction", name)

    def act(self, name: str) -> Any:
        return self.command("act", name)

    def gaze(self, x: float, y: float, ttl_ms: int = 5000) -> Any:
        return self.command("gaze", [float(x), float(y)], ttl_ms)

    def stop(self) -> Any:
        return self.command("stop")

    def state(self) -> Any:
        return _get_json(f"{self.url}/control/state", timeout=2.0)
