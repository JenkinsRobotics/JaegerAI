"""``jaeger avatar`` — see Lilith's face in action.

Single command, zero boot.  Renders a ~16-second animated GIF of
Lilith cycling through every emotion (with breathing, blinking,
and sin-wave lip sync on "speaking") and opens it in the default
viewer.

No brain, no Kokoro, no voice loop, no Swift app required.  Just
the procedural face.

Use this to:
  - Verify the face renders correctly after a change to lilith_face.py
  - Show someone what Lilith looks like without booting the system
  - Visually validate emotion → mouth/eye shape mapping
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from . import _common as c


def register(subparsers: Any) -> None:
    parser = subparsers.add_parser(
        "avatar",
        help="render an animated demo of Lilith's face + open it",
        description=(
            "Render Lilith cycling through every emotion as an "
            "animated GIF + open it.  No system boot required."
        ),
    )
    parser.add_argument(
        "--out", default="/tmp/lilith_demo.gif",
        help="output GIF path (default: /tmp/lilith_demo.gif)",
    )
    parser.add_argument(
        "--no-open", action="store_true",
        help="render the GIF but don't auto-open it",
    )
    parser.add_argument(
        "--size", type=int, default=256,
        help="square frame size in pixels (default: 256)",
    )
    parser.set_defaults(_handler=run_demo)


def run_demo(args: Any) -> int:
    repo = Path(__file__).resolve().parents[2]
    script = repo / "dev_scripts" / "lilith_demo.py"
    if not script.exists():
        print(c.red(f"missing demo script: {script}"))
        return 1
    # The demo script is self-contained; just exec it.  It writes
    # /tmp/lilith_demo.gif and opens it via `open` on macOS.
    venv_py = repo / ".venv" / "bin" / "python"
    py = str(venv_py) if venv_py.exists() else "python3"
    print(c.dim(f"  running {script.name}..."))
    result = subprocess.run([py, str(script)], cwd=str(repo))
    return result.returncode
