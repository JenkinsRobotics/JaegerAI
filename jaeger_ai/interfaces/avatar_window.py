"""The living avatar: launch the JaegerAvatar app and drive it over its control link.

JaegerAvatar (the sibling repository; JAEGER_AVATAR_HOME overrides the default path) is the
dynamic, vivid face — Vita by default, with its own rig, voice loop, lip sync and stage. This
module launches it in its own desktop window, remembers the control token it was given, and
speaks avatar-control/v1 to it: feelings, reactions and actions for the body on stage.

Commands are only accepted while a stage is showing the avatar (the app refuses commands
into the void), so `feel("joy")` with no window open reports that rather than pretending.

  python3 -m jaeger_ai.interfaces.avatar_window --check   # launch if needed, probe the link
"""
from __future__ import annotations

import json
import os
import secrets
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

HOME = Path(os.environ.get("JAEGER_AVATAR_HOME", Path.home() / "GITHUB/JaegerAvatar"))
STATE = Path.home() / ".jaeger_ai" / "avatar.json"   # where the launched app's url and token are remembered
DEFAULT_FACE = "vita"
DEFAULT_PORT = 8790


def _get(url: str, timeout: float = 2.0) -> Any:
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read())


def serving(port: int = DEFAULT_PORT) -> bool:
    """Whether the avatar app answers on this machine."""
    try:
        return bool(_get(f"http://127.0.0.1:{port}/health"))
    except (OSError, ValueError):
        return False


def launch(face: str = DEFAULT_FACE, port: int = DEFAULT_PORT, browser: bool = False, wait_s: int = 120) -> str:
    """The avatar on stage: starts the app when it isn't running (its own window, or --browser to serve only)
    and returns the stage URL. The first run installs the app's environments and takes minutes."""
    if not HOME.joinpath("main.py").is_file():
        raise FileNotFoundError(f"JaegerAvatar is not at {HOME} (set JAEGER_AVATAR_HOME)")
    if not serving(port):
        token = os.environ.get("JAEGER_AVATAR_CONTROL_TOKEN") or secrets.token_urlsafe(18)
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps({"url": f"http://127.0.0.1:{port}", "token": token}))
        subprocess.Popen(["python3", str(HOME / "main.py"), "--port", str(port), *(["--browser"] if browser else [])],
                         cwd=HOME, env={**os.environ, "JAEGER_AVATAR_CONTROL_TOKEN": token},
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        deadline = time.time() + wait_s
        while not serving(port):
            if time.time() > deadline:
                raise TimeoutError(f"the avatar app did not answer within {wait_s}s")
            time.sleep(1)
    return f"http://127.0.0.1:{port}/?face={face}"


class AvatarLink:
    """avatar-control/v1 client: tell the body on stage how to feel, react and move.

    The token is the one `launch()` chose (remembered in ~/.jaeger_ai/avatar.json), or
    JAEGER_AVATAR_CONTROL_TOKEN for an app someone started themselves."""

    def __init__(self, url: str | None = None, token: str | None = None):
        remembered = {}
        try:
            remembered = json.loads(STATE.read_text())
        except (OSError, ValueError):
            pass
        self.url = (url or remembered.get("url") or f"http://127.0.0.1:{DEFAULT_PORT}").rstrip("/")
        self.token = token or os.environ.get("JAEGER_AVATAR_CONTROL_TOKEN") or remembered.get("token") or ""

    def command(self, op: str, value: Any = None, ttl_ms: int = 5000) -> Any:
        body = json.dumps({"op": op, "value": value, "ttl_ms": ttl_ms}).encode()
        req = urllib.request.Request(f"{self.url}/control", body,
                                     {"Content-Type": "application/json", "X-Avatar-Token": self.token})
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            raise RuntimeError(json.loads(e.read()).get("error", str(e))) from None

    def feel(self, emotion: str, ttl_ms: int = 30000) -> Any:
        return self.command("emotion", emotion, ttl_ms)

    def react(self, name: str) -> Any:
        return self.command("reaction", name)

    def act(self, name: str) -> Any:
        return self.command("act", name)

    def gaze(self, x: float, y: float, ttl_ms: int = 5000) -> Any:
        return self.command("gaze", [x, y], ttl_ms)

    def stop(self) -> Any:
        return self.command("stop")

    def state(self) -> Any:
        return _get(f"{self.url}/control/state")


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if "--check" in args:   # the runnable check: the app answers and the control link tells the truth
        url = launch(browser="--browser" in args)
        print("avatar app:", url)
        try:
            print("control accepted:", AvatarLink().feel("joy"))
        except RuntimeError as e:
            if "No avatar attached" in str(e):
                print("control link alive; no stage is showing the avatar yet (open the window and it will be)")
            else:
                raise
        return 0
    print(launch())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
