"""Code-execution skills.

  • run_python(code, timeout_s) — execute a Python snippet in a sandboxed
                                  subprocess (fresh interpreter, fresh
                                  tempdir cwd, capped output, hard timeout)
  • run_shell(command, timeout_s) — run a shell command. HIGHEST-risk
                                  tool: tier-4 gated + confirmation +
                                  audit. For git / npm / brew / ffmpeg —
                                  anything the pure-Python tools can't do.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from typing import Any

from jaeger_os.core.tools.tool_registry import register_tool_from_function
from jaeger_ai.core.context import _audit, _require_layout
from jaeger_os.core.safety.command_guard import hardline_guard
from jaeger_os.core.safety.permissions import PermissionTier, requires_tier
from jaeger_ai.core.runtime.tool_interrupt import ToolInterrupted, run_interruptible


def run_python(code: str, timeout_s: float = 10.0) -> dict[str, Any]:
    """Execute Python code in a fresh, isolated subprocess.

    Runtime rules — enforced by the subprocess boundary:
      - Fresh subprocess (`python -s -E`): no user site-packages, no
        inherited environment.
      - cwd AND sys.path[0] are the instance ``skills/`` workspace, so
        code can both ``open()`` and ``import`` the files ``write_file``
        just created. "Write a file then run it" is the core code
        workflow and depends on this.
      - 10s default timeout (overridable).
      - 200 KB cap on captured stdout/stderr.

    Returns {ok, exit_code, stdout, stderr, elapsed_s, timed_out}.
    """
    cleaned = (code or "").strip()
    if not cleaned:
        return {"ok": False, "error": "empty code"}
    MAX = 200_000
    started = time.perf_counter()
    timed_out = False
    interrupted = False
    # Run inside the agent's skills/ workspace so generated code sees the
    # files it just wrote. Falls back to the scratch dir when no instance
    # is bound (standalone tests).
    workdir = None
    try:
        from jaeger_ai.core.context import _require_layout
        workdir = _require_layout().skills_dir
        workdir.mkdir(parents=True, exist_ok=True)
    except Exception:
        workdir = None
    with tempfile.TemporaryDirectory(prefix="jaeger_run_") as scratch:
        run_dir = str(workdir) if workdir is not None else scratch
        # Execute as a real script file inside the workspace: that puts
        # the workspace on sys.path[0] (so `import sibling` works even
        # under `-I` isolation) and gives tracebacks true line numbers.
        script = os.path.join(run_dir, f".jaeger_run_{os.urandom(4).hex()}.py")
        try:
            with open(script, "w", encoding="utf-8") as fh:
                fh.write(cleaned)
            proc = run_interruptible(
                [sys.executable, "-s", "-E", script],
                timeout=timeout_s,
                cwd=run_dir,
                env={"PATH": os.environ.get("PATH", ""), "HOME": scratch},
            )
            stdout, stderr, exit_code = proc.stdout, proc.stderr, proc.returncode
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            exit_code = -1
            stdout = (exc.stdout.decode() if isinstance(exc.stdout, bytes) else (exc.stdout or "")) or ""
            stderr = (exc.stderr.decode() if isinstance(exc.stderr, bytes) else (exc.stderr or "")) or ""
        except ToolInterrupted as exc:
            # The turn was cancelled mid-run — the child has been killed.
            interrupted = True
            exit_code = 130
            stdout = (exc.stdout.decode() if isinstance(exc.stdout, bytes) else (exc.stdout or "")) or ""
            stderr = (exc.stderr.decode() if isinstance(exc.stderr, bytes) else (exc.stderr or "")) or ""
        finally:
            try:
                os.unlink(script)
            except OSError:
                pass
    elapsed = time.perf_counter() - started
    return {
        "ok": exit_code == 0 and not timed_out and not interrupted,
        "exit_code": exit_code,
        "stdout": stdout[:MAX],
        "stderr": stderr[:MAX],
        "elapsed_s": round(elapsed, 3),
        "timed_out": timed_out,
        "interrupted": interrupted,
    }


@hardline_guard("command")
@requires_tier(
    PermissionTier.PRIVILEGED,
    skill="shell",
    operation="run_shell",
    summary="run an arbitrary shell command",
)
def run_shell(command: str, timeout_s: float = 60.0) -> dict[str, Any]:
    """Run a shell command — git, npm, brew, ffmpeg, anything the
    pure-Python tools can't reach.

    THIS IS THE HIGHEST-RISK TOOL. It is gated at PRIVILEGED (tier 4),
    so every call routes through the permission confirmation flow — the
    human sees and approves the exact command before it runs. Every
    invocation is written to the instance audit log. A small set of
    catastrophic commands (``rm -rf /``, ``mkfs``, fork bombs, writing to
    a raw disk device, …) is refused unconditionally by the hardline
    guard — below even the tier prompt.

    Sandboxing is partial by nature (a shell command can do anything
    the OS lets the user do): the command runs with a fresh tempdir as
    cwd and a hard timeout, but it is NOT filesystem-confined the way
    file_write is. Use it deliberately; prefer install_package /
    run_in_venv / run_python when they can do the job.

    Returns ``{ok, exit_code, stdout, stderr, elapsed_s, timed_out}``.
    """
    cleaned = (command or "").strip()
    if not cleaned:
        return {"ok": False, "error": "empty command"}
    timeout = max(1.0, min(float(timeout_s or 60.0), 600.0))

    # Audit every shell invocation, even before it runs — the audit log
    # is the tamper-evident record of what the agent was permitted to do.
    try:
        layout = _require_layout()
        _audit("run_shell", {"command": cleaned[:500], "timeout_s": timeout})
    except Exception:  # noqa: BLE001
        pass

    MAX = 200_000
    started = time.perf_counter()
    timed_out = False
    interrupted = False
    with tempfile.TemporaryDirectory(prefix="jaeger_shell_") as scratch:
        try:
            proc = run_interruptible(
                ["/bin/sh", "-c", cleaned],
                timeout=timeout,
                cwd=scratch,
            )
            stdout, stderr, exit_code = proc.stdout, proc.stderr, proc.returncode
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            exit_code = -1
            stdout = (exc.stdout.decode() if isinstance(exc.stdout, bytes)
                      else (exc.stdout or "")) or ""
            stderr = (exc.stderr.decode() if isinstance(exc.stderr, bytes)
                      else (exc.stderr or "")) or ""
        except ToolInterrupted as exc:
            # The turn was cancelled mid-command — the child was killed.
            interrupted = True
            exit_code = 130
            stdout = (exc.stdout.decode() if isinstance(exc.stdout, bytes)
                      else (exc.stdout or "")) or ""
            stderr = (exc.stderr.decode() if isinstance(exc.stderr, bytes)
                      else (exc.stderr or "")) or ""
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}",
                    "command": cleaned}
    elapsed = time.perf_counter() - started
    return {
        "ok": exit_code == 0 and not timed_out and not interrupted,
        "command": cleaned,
        "exit_code": exit_code,
        "stdout": stdout[:MAX],
        "stderr": stderr[:MAX],
        "elapsed_s": round(elapsed, 3),
        "timed_out": timed_out,
        "interrupted": interrupted,
    }


@register_tool_from_function(name="execute_code")
@requires_tier(PermissionTier.WRITE_LOCAL, skill="code",
               operation="execute_code",
               summary="run Python code in the skills workspace")
def _t_execute_code(code: str, timeout_s: float = 10.0) -> dict:
    """Run Python code and return its output. Reach for this for
    computational work: arithmetic that can't be done with
    `calculate`, string transforms, quick logic — and to run files
    you wrote with write_file (code runs IN the skills/ workspace,
    so `import name` and `open('file')` see them). To run a file you
    wrote, pass Python (e.g. code="import fib10" or
    open('fib10.py').read()) — NOT a shell line like
    "python fib10.py", which is not valid Python. 10s default
    timeout. Isolated from packages installed via install_package.

    For the current date / day / time / timezone, use `get_time` —
    it's the ONLY source of truth, not Python's clock."""
    return run_python(code=code, timeout_s=timeout_s)


@register_tool_from_function(name="terminal")
def _t_terminal(command: str, timeout_s: float = 60.0) -> dict:
    """Run a non-Python command-line program — git, npm, brew,
    ffmpeg. For Python code use execute_code; for files use
    write_file / read_file / list_skill_dir. PRIVILEGED-tier: each
    call prompts the user, so reach for it only when the task
    genuinely needs a shell program."""
    return run_shell(command=command, timeout_s=timeout_s)
