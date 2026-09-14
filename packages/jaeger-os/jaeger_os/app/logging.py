"""One log-line shape + the bus mirror.

``[HH:MM:SS] [source] [LEVEL]  message`` to stderr; operator-relevant
lines also ride ``/sys/log`` so any surface can render them (the CC01
LogBox pattern, generalized).

Levels are open strings, not an enum: ``boot``, ``ok``, ``info``,
``warn``, ``error`` and ``debug`` get a colour, anything else prints
uncoloured. A log call must never be the thing that takes a node down,
so an unknown level is not an error.
"""

from __future__ import annotations

import dataclasses
import os
import sys
import time
from typing import Any

SYS_LOG = "/sys/log"

#: level -> ANSI colour. The timestamp/source prefix is always dim, so
#: a wall of log lines reads as one column of context and one column of
#: message.
_COLORS = {"boot": "\033[96m", "ok": "\033[92m", "warn": "\033[93m",
           "error": "\033[91m", "debug": "\033[90m"}
_DIM = "\033[90m"
_RESET = "\033[0m"

#: Width the boot-banner keys are right-aligned to. One number, so a run
#: of :func:`kv` calls forms a column no matter who calls them.
_KEY_WIDTH = 10

#: Env var that turns ``level="debug"`` lines on. ``1`` (or ``all``) for
#: everything; otherwise a comma-separated source list —
#: ``JAEGER_DEBUG=stt-fast,mic``. Per-source matters more than it looks:
#: on a robot with a dozen nodes, a single global switch buries the one
#: subsystem you are actually debugging.
DEBUG_ENV = "JAEGER_DEBUG"


def debug_enabled(source: str = "") -> bool:
    """Is per-action debug output on, for this source?

    Read per call, not cached: an operator flipping the var in a running
    shell and restarting one node should not have to restart the world,
    and this is a string compare on a path that only runs when someone
    is already reading logs.
    """
    want = (os.environ.get(DEBUG_ENV) or "").strip()
    if not want:
        return False
    if want in ("1", "all", "true"):
        return True
    return source in {s.strip() for s in want.split(",") if s.strip()}


def _color() -> bool:
    """Colour only when stderr is a terminal and NO_COLOR is unset.

    Checked per call rather than cached at import: pytest's capsys and
    every subprocess pipe replace ``sys.stderr`` after import, and a
    cached answer would emit escape codes into captured output.
    """
    if os.environ.get("NO_COLOR"):
        return False
    try:
        return sys.stderr.isatty()
    except Exception:  # noqa: BLE001 — a stub stderr is not a log failure
        return False


@dataclasses.dataclass
class LogLine:
    source: str
    level: str = "info"
    line: str = ""
    ts: float = 0.0
    topic: str = SYS_LOG


def log(source: str, line: str, *, level: str = "info",
        bus: Any = None) -> None:
    # `debug` is the one level that can be off. It exists so a module can
    # narrate every action it takes — which is worth having built in, and
    # unusable unless it is silent by default. Dropped before the bus
    # mirror too: a trace nobody asked to see should not cost a publish
    # to every /sys/log subscriber either.
    if level == "debug" and not debug_enabled(source):
        return
    ts = time.time()
    stamp = time.strftime("%H:%M:%S", time.localtime(ts))
    prefix = f"[{stamp}] [{source}]"
    tag = f"[{level.upper()}]"
    if _color():
        prefix = f"{_DIM}{prefix}{_RESET}"
        shade = _COLORS.get(level.lower())
        if shade:
            tag = f"{shade}{tag}{_RESET}"
    print(f"{prefix} {tag}  {line}", file=sys.stderr, flush=True)
    if bus is not None:
        try:
            bus.publish(LogLine(source=source, level=level, line=line,
                                ts=ts))
        except Exception:  # noqa: BLE001 — logging never raises
            pass


def kv(source: str, key: str, value: Any, *, bus: Any = None) -> None:
    """One right-aligned ``key : value`` line, for boot banners.

    The alignment is the point — ``node`` / ``host`` / ``version``
    printed one per line only reads as a block if the colons line up,
    and they only line up if one function owns the width.
    """
    log(source, f"{key:>{_KEY_WIDTH}} : {value}", bus=bus)


__all__ = ["LogLine", "log", "kv", "debug_enabled", "DEBUG_ENV", "SYS_LOG"]
