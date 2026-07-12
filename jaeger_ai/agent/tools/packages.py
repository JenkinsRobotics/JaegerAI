"""Dependency-install + venv-execution tools.

  • install_package(package)        — pip-install into the instance venv
  • run_in_venv(code, timeout_s)    — execute code against the instance venv
  • list_venv_packages()           — what's installed in the instance venv

These are the Phase-1/2 capabilities that turn the agent from a "tool
router" into something that can build its own integrations: a skill
that needs ``discord.py`` is dead without ``install_package``, and an
installed package is useless without ``run_in_venv`` (the sandboxed
``run_python`` uses ``python -I`` so it can't see venv site-packages).

``install_package`` is gated at ``PRIVILEGED`` (tier 4) — installing a
dependency mutates the instance environment, so it routes through the
permission policy's confirmation flow. ``run_in_venv`` is gated at
``WRITE_LOCAL`` (tier 1) since it runs code but only inside the
instance's own venv + a scratch cwd.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
import time
from typing import Any

from jaeger_os.core.tools.tool_registry import register_tool_from_function
from jaeger_ai.core.context import _require_layout
from jaeger_os.core.safety.permissions import PermissionTier, requires_tier
from jaeger_ai.core.runtime.tool_interrupt import ToolInterrupted, run_interruptible
from jaeger_ai.core.runtime.venv import (
    ensure_venv,
    install_into_venv,
    list_installed,
    venv_exists,
    venv_python,
)


@requires_tier(
    PermissionTier.PRIVILEGED,
    skill="packages",
    operation="install_package",
    summary="pip-install a third-party package into the instance venv",
)
def install_package(package: str) -> dict[str, Any]:
    """Install a Python package into the instance's own virtual env.

    Use this when a skill you're building needs a third-party library
    (e.g. ``discord.py`` for a Discord integration). The package lands
    in ``<instance>/venv/`` — isolated from the framework — and becomes
    importable by ``run_in_venv``.

    Tier-4 (PRIVILEGED): installing a dependency mutates the instance
    environment, so this routes through the permission confirmation
    flow. Returns ``{ok, package, exit_code, stdout, stderr}`` or
    ``{ok: False, error: ...}``."""
    layout = _require_layout()
    return install_into_venv(layout, package)


def list_venv_packages() -> dict[str, Any]:
    """List the packages installed in the instance venv. Read-only —
    use it to check whether a dependency is already available before
    calling install_package."""
    layout = _require_layout()
    return list_installed(layout)


@requires_tier(
    PermissionTier.WRITE_LOCAL,
    skill="packages",
    operation="run_in_venv",
    summary="run Python against the instance venv (sees installed packages)",
)
def run_in_venv(code: str, timeout_s: float = 30.0) -> dict[str, Any]:
    """Execute Python code against the instance venv's interpreter.

    Unlike ``run_python`` (which uses ``python -I`` — isolated, no
    site-packages, 10s cap), this runs against ``<instance>/venv/``'s
    interpreter so packages installed via ``install_package`` ARE
    importable. Use it to test/run code that depends on installed
    libraries.

    Still sandboxed: a fresh tempdir cwd, captured output (200 KB cap),
    a hard timeout (default 30s, max 300s). Returns ``{ok, exit_code,
    stdout, stderr, elapsed_s, timed_out}``."""
    cleaned = (code or "").strip()
    if not cleaned:
        return {"ok": False, "error": "empty code"}
    layout = _require_layout()
    # Create the venv on first use so run_in_venv works even before any
    # install_package call (the agent might just want a longer-running
    # or non-isolated execution than run_python allows).
    try:
        ensure_venv(layout)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"could not create instance venv: {exc}"}
    if not venv_exists(layout):
        return {"ok": False, "error": "instance venv unavailable"}

    timeout = max(1.0, min(float(timeout_s or 30.0), 300.0))
    MAX = 200_000
    started = time.perf_counter()
    timed_out = False
    interrupted = False
    py = str(venv_python(layout))
    with tempfile.TemporaryDirectory(prefix="jaeger_venv_run_") as scratch:
        try:
            proc = run_interruptible(
                # NB: no -I here (that's the whole point — venv
                # site-packages must be visible). cwd is still a fresh
                # tempdir so the code can't scribble on the workspace.
                [py, "-c", cleaned],
                timeout=timeout,
                cwd=scratch,
                env={"PATH": os.environ.get("PATH", ""), "HOME": scratch},
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
            # The turn was cancelled mid-run — the child was killed.
            interrupted = True
            exit_code = 130
            stdout = (exc.stdout.decode() if isinstance(exc.stdout, bytes)
                      else (exc.stdout or "")) or ""
            stderr = (exc.stderr.decode() if isinstance(exc.stderr, bytes)
                      else (exc.stderr or "")) or ""
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


@register_tool_from_function(name="install_package")
def _t_install_package(package: str) -> dict:
    """Install a third-party Python package into this instance's
    own venv (isolated from the framework). Use when a skill you're
    building needs a library — e.g. `discord.py` for a Discord
    integration. PRIVILEGED tier: routes through the confirmation
    flow. After installing, use run_in_venv (not run_python) to run
    code that imports it."""
    return install_package(package=package)


@register_tool_from_function(name="list_venv_packages")
def _t_list_venv_packages() -> dict:
    """List packages installed in this instance's venv. Read-only —
    check here before install_package to see if a dependency is
    already available."""
    return list_venv_packages()


@register_tool_from_function(name="run_in_venv")
def _t_run_in_venv(code: str, timeout_s: float = 30.0) -> dict:
    """Execute Python against this instance's venv interpreter so
    packages installed via install_package ARE importable. Sandboxed
    cwd, 30s default timeout (max 300s). Use this — not run_python —
    for code that depends on installed libraries."""
    return run_in_venv(code=code, timeout_s=timeout_s)
