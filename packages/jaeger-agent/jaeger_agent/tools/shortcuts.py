"""Shortcuts — two tools over the macOS ``shortcuts`` CLI.

  • list_shortcuts()              — READ_ONLY: what's installed.
  • run_shortcut(name, input=None) — EXTERNAL_EFFECT: runs whatever the
    user (or something they installed) built in Shortcuts.app.

Shortcuts.app automations can do ANYTHING their author wired up — send
messages, move files, drive other apps, hit the network. Running one is
not a small, auditable action the way ``open_on_host`` is, so
``run_shortcut`` sits at the same tier as ``send_email`` /
``send_message``: it goes through the standard tier-2 confirmation flow
every time, "always"-grants included.

Both wrap the ``shortcuts`` CLI (ships with macOS 12+, no install
needed): ``shortcuts list`` and ``shortcuts run <name> [-i <file>]
[-o <file>]``. The CLI takes input as a FILE, not stdin — a string
``input`` is written to a temp file first; the shortcut's OUTPUT (if
any) is captured the same way and read back, then both temp files are
cleaned up.
"""

from __future__ import annotations

import platform
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from jaeger_os.core.tools.tool_registry import register_tool_from_function
from jaeger_os.core.safety.permissions import PermissionTier, requires_tier

_TIMEOUT_LIST_S = 10
_TIMEOUT_RUN_S = 60


def _not_macos_error() -> dict[str, Any]:
    return {"error": f"Shortcuts is only available on macOS (got {platform.system()})"}


def list_shortcuts() -> dict[str, Any]:
    """List every shortcut installed in Shortcuts.app, via ``shortcuts
    list``. Actionable error if the ``shortcuts`` CLI is missing (pre-
    Monterey) or Shortcuts has nothing installed."""
    if platform.system() != "Darwin":
        return {"listed": False, **_not_macos_error()}
    if shutil.which("shortcuts") is None:
        return {"listed": False,
                 "error": "the `shortcuts` CLI is not on PATH (needs macOS 12 Monterey+)"}
    try:
        out = subprocess.run(
            ["shortcuts", "list"],
            check=False, capture_output=True, text=True, timeout=_TIMEOUT_LIST_S,
        )
    except Exception as exc:  # noqa: BLE001 — never raise, surface as a tool error
        return {"listed": False, "error": f"{type(exc).__name__}: {exc}"}
    if out.returncode != 0:
        return {"listed": False,
                 "error": (out.stderr or out.stdout or "shortcuts list failed").strip()}
    names = [ln.strip() for ln in out.stdout.splitlines() if ln.strip()]
    if not names:
        return {"listed": True, "shortcuts": [],
                 "note": "no shortcuts installed — nothing in Shortcuts.app yet"}
    return {"listed": True, "shortcuts": names, "count": len(names)}


def run_shortcut(name: str, input: str | None = None) -> dict[str, Any]:
    """Run a shortcut by exact name via ``shortcuts run``, optionally
    feeding it text input and capturing its text output.

    EXTERNAL EFFECT: a shortcut can do anything its author built into
    it — this is NOT a scoped, predictable action like open_on_host,
    so it goes through the standard tier-2 confirmation flow every
    single call (no implicit trust from a prior "always" on a
    different shortcut). Use list_shortcuts() first if you're not
    certain of the exact name — an unknown name is an actionable
    error, not a silent no-op.
    """
    name_clean = (name or "").strip()
    if not name_clean:
        return {"ran": False, "error": "empty shortcut name"}
    if platform.system() != "Darwin":
        return {"ran": False, **_not_macos_error()}
    if shutil.which("shortcuts") is None:
        return {"ran": False,
                 "error": "the `shortcuts` CLI is not on PATH (needs macOS 12 Monterey+)"}

    with tempfile.TemporaryDirectory(prefix="jaeger-shortcut-") as tmpdir:
        args = ["shortcuts", "run", name_clean]
        in_path = None
        if input is not None and input != "":
            in_path = Path(tmpdir) / "input.txt"
            in_path.write_text(input, encoding="utf-8")
            args += ["-i", str(in_path)]
        out_path = Path(tmpdir) / "output.txt"
        args += ["-o", str(out_path)]

        try:
            proc = subprocess.run(
                args, check=False, capture_output=True, text=True,
                timeout=_TIMEOUT_RUN_S,
            )
        except subprocess.TimeoutExpired:
            return {"ran": False, "error": f"shortcut {name_clean!r} timed out after {_TIMEOUT_RUN_S}s"}
        except Exception as exc:  # noqa: BLE001
            return {"ran": False, "error": f"{type(exc).__name__}: {exc}"}

        if proc.returncode != 0:
            stderr = (proc.stderr or proc.stdout or "").strip()
            if "not found" in stderr.lower() or "doesn't exist" in stderr.lower():
                return {"ran": False, "name": name_clean,
                         "error": (f"no shortcut named {name_clean!r} — call "
                                   "list_shortcuts() to see what's installed")}
            return {"ran": False, "name": name_clean,
                     "error": stderr or "shortcuts run failed"}

        output_text = None
        if out_path.exists():
            try:
                output_text = out_path.read_text(encoding="utf-8").strip() or None
            except (OSError, UnicodeDecodeError):
                output_text = None

    return {"ran": True, "name": name_clean, "output": output_text}


# ── Agent-facing tool wrappers ────────────────────────────────────────


@register_tool_from_function(name="list_shortcuts", side_effect="read")
@requires_tier(PermissionTier.READ_ONLY, skill="shortcuts", operation="list_shortcuts",
               summary="list installed Shortcuts.app automations")
def _t_list_shortcuts() -> dict:
    """List every shortcut installed in Shortcuts.app — use this before
    run_shortcut when you're not sure of the exact name. Returns
    {shortcuts: [names]} or {listed: False, error}."""
    return list_shortcuts()


@register_tool_from_function(name="run_shortcut")
@requires_tier(PermissionTier.EXTERNAL_EFFECT, skill="shortcuts",
               operation="run_shortcut",
               summary="run a Shortcuts.app automation")
def _t_run_shortcut(name: str, input: str | None = None) -> dict:
    """Run a macOS Shortcuts.app automation by exact name — the tool
    for "run my <X> shortcut" / any user-built automation. Optional
    `input` is text fed to the shortcut; its text output (if any) comes
    back as `output`. A shortcut can do ANYTHING the user built it to
    do (send messages, move files, hit the network) — this is NOT a
    small predictable action, so it is EXTERNAL EFFECT tier and asks
    for confirmation every call. Call list_shortcuts() first if you
    aren't sure of the exact name. Returns {ran, name, output} or
    {ran: False, error}."""
    return run_shortcut(name=name, input=input)


__all__ = ["list_shortcuts", "run_shortcut"]
