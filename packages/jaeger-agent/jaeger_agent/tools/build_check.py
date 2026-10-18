"""run_build_check — the team's build/test checker.

Runs a short list of build/test commands inside a project root and checks that
expected files exist. The JSON it returns is the evidence a builder or
reviewer reports, and the Gateway runs the same checker for
``POST /v1/projects/{id}/check`` so a pass is recorded from the host, not taken
from the model's word. No shell: each command is split and executed directly
with a minimal environment, a timeout and output tails.
"""
from __future__ import annotations

import os
import shlex
import subprocess
import time
from pathlib import Path
from typing import Any

from jaeger_os.core.tools.tool_registry import register_tool_from_function

#: First words a check command may start with.
CHECK_COMMANDS = frozenset({"npm", "node", "python3", "pytest", "make", "swift", "git", "ls", "test"})
_NPM_OK = frozenset({"test", "run", "start", "ls"})
TAIL = 1500


def check_project(root: str, commands: list[str], expect_files: list[str] | None = None,
                  timeout_s: float = 300.0) -> dict[str, Any]:
    base = Path(root).expanduser()
    if not base.is_absolute() or not base.is_dir():
        return {"ok": False, "error": f"root is not an existing absolute directory: {root}"}
    base = base.resolve()
    results: list[dict[str, Any]] = []
    env = {k: v for k, v in os.environ.items() if k in {"PATH", "HOME", "TMPDIR", "LANG", "LC_ALL", "USER"}}
    env["CI"] = "1"
    env["npm_config_offline"] = "true"
    for raw in commands or []:
        cmd = str(raw or "").strip()
        try:
            argv = shlex.split(cmd)
        except ValueError as exc:
            results.append({"cmd": cmd, "ok": False, "exit_code": None, "error": f"unparseable: {exc}"})
            continue
        if not argv or argv[0] not in CHECK_COMMANDS:
            results.append({"cmd": cmd, "ok": False, "exit_code": None,
                            "error": f"not a check command (allowed: {sorted(CHECK_COMMANDS)})"})
            continue
        if argv[0] == "npm" and (len(argv) < 2 or argv[1] not in _NPM_OK):
            results.append({"cmd": cmd, "ok": False, "exit_code": None, "error": "npm subcommand not allowed"})
            continue
        if argv[0] == "git" and (len(argv) < 2 or argv[1] not in {"status", "diff", "log"}):
            results.append({"cmd": cmd, "ok": False, "exit_code": None, "error": "git subcommand not allowed"})
            continue
        started = time.monotonic()
        try:
            proc = subprocess.run(argv, cwd=str(base), env=env, capture_output=True, text=True,
                                  timeout=max(1.0, float(timeout_s)), stdin=subprocess.DEVNULL)
            out = (proc.stdout or "") + (("\n" + proc.stderr) if proc.stderr else "")
            results.append({"cmd": cmd, "ok": proc.returncode == 0, "exit_code": proc.returncode,
                            "seconds": round(time.monotonic() - started, 2), "output_tail": out[-TAIL:]})
        except subprocess.TimeoutExpired:
            results.append({"cmd": cmd, "ok": False, "exit_code": None, "error": f"timed out after {timeout_s}s"})
        except OSError as exc:
            results.append({"cmd": cmd, "ok": False, "exit_code": None, "error": str(exc)})
    missing = []
    for rel in expect_files or []:
        p = (base / str(rel)).resolve()
        try:
            p.relative_to(base)
        except ValueError:
            missing.append(f"{rel} (outside root)")
            continue
        if not p.exists():
            missing.append(str(rel))
    ok = bool(results or expect_files) and all(r["ok"] for r in results) and not missing
    return {"ok": ok, "root": str(base), "results": results, "missing_files": missing,
            "checked_files": list(expect_files or []), "checker": "run_build_check/v1"}


@register_tool_from_function(name="run_build_check", side_effect="external")
def run_build_check(root: str = "", commands: str = "npm test", expect_files: str = "",
                    timeout_s: float = 300.0) -> dict[str, Any]:
    """Build/test checker: run check commands in the project root and verify files.

    root: the project root (defaults to the bound project). commands: comma- or
    newline-separated, e.g. "npm test". expect_files: comma-separated paths
    relative to root that must exist. Returns ok plus per-command exit codes and
    output tails. Use its JSON as your evidence; never claim a pass without it."""
    if not root:
        try:
            from jaeger_agent.core.workspace import get_project_root
            bound = get_project_root()
            root = str(bound) if bound else ""
        except Exception:  # noqa: BLE001
            root = ""
    if not root:
        return {"ok": False, "error": "no root given and no project is bound"}
    try:
        from jaeger_agent.core.workspace import get_project_root
        bound = get_project_root()
        if bound is not None:
            Path(root).expanduser().resolve().relative_to(Path(bound).resolve())
    except ValueError:
        return {"ok": False, "error": f"root must be inside the bound project {bound}"}
    except Exception:  # noqa: BLE001
        pass
    cmds = [c.strip() for part in str(commands or "").split("\n") for c in part.split(",") if c.strip()]
    files = [f.strip() for f in str(expect_files or "").split(",") if f.strip()]
    return check_project(root, cmds, files, timeout_s=timeout_s)
