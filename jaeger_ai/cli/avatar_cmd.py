"""``jaeger avatar`` — the living avatar, on stage.

Launches the JaegerAvatar app (the sibling repository) in its own desktop
window: Vita by default — the dynamic, vivid face with its own rig, voice
loop and lip sync. ``--face`` picks any of its packs, ``--browser`` serves
for a browser tab instead of opening a window, and ``--check`` probes the
control link that lets JaegerAI drive the body on stage.

``--gif`` keeps the old zero-boot demo: Lilith cycling through her emotions
as an animated GIF, for eyeballing a change to lilith_face.py.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from . import _common as c


def register(subparsers: Any) -> None:
    parser = subparsers.add_parser(
        "avatar",
        help="open the living avatar window (JaegerAvatar, Vita by default)",
        description=(
            "Launch the JaegerAvatar app in its own window and put a character "
            "on stage. The first run builds the app's environments and takes minutes."
        ),
    )
    parser.add_argument("--face", default="vita", help="character on stage (default: %(default)s)")
    parser.add_argument("--port", type=int, default=8790, help="the app's local port (default: %(default)s)")
    parser.add_argument("--browser", action="store_true", help="serve for a browser instead of opening a window")
    parser.add_argument("--check", action="store_true", help="launch if needed and probe the control link")
    parser.add_argument("--gif", action="store_true", help="the old demo: render Lilith's emotions as a GIF")
    parser.add_argument("--out", default="/tmp/lilith_demo.gif", help="(--gif) output path")
    parser.set_defaults(_handler=run)


def run(args: Any) -> int:
    if args.gif:
        return run_gif_demo(args)
    from ..interfaces import avatar_window
    try:
        if args.check:
            return avatar_window.main(["--check"] + (["--browser"] if args.browser else []))
        url = avatar_window.launch(face=args.face, port=args.port, browser=args.browser)
    except (FileNotFoundError, TimeoutError) as e:
        print(c.red(str(e)))
        return 1
    print(f"avatar on stage: {url}")
    if args.browser:
        print(c.dim("  serving only (no window); open the URL in a browser"))
    return 0


def run_gif_demo(args: Any) -> int:
    repo = Path(__file__).resolve().parents[2]
    script = repo / "dev" / "scripts" / "lilith_demo.py"
    if not script.exists():
        print(c.red(f"missing demo script: {script}"))
        return 1
    venv_py = repo / ".venv" / "bin" / "python"
    py = str(venv_py) if venv_py.exists() else "python3"
    print(c.dim(f"  running {script.name}..."))
    return subprocess.run([py, str(script)], cwd=str(repo)).returncode
