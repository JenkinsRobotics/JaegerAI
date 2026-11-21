"""Per-instance virtual environment management.

Each instance gets its own venv at ``<instance>/venv/`` so the agent
can install third-party packages a skill needs WITHOUT touching the
framework's own environment. The framework venv stays pristine; the
instance venv is the agent's sandbox for dependencies.

  • ensure_venv(layout)        — create the instance venv if missing
  • venv_python(layout)        — path to the venv's python interpreter
  • venv_exists(layout)        — is the venv present + usable
  • install_into_venv(...)     — pip-install a package into the venv

Used by:
  • the ``install_package`` agent tool (tier-gated)
  • the ``run_in_venv`` agent tool (executes against this interpreter)
"""

from __future__ import annotations

import re
import os
import sys
import threading
import tempfile
import subprocess
import venv as _stdlib_venv
from pathlib import Path
from typing import Any


# A pip requirement spec: package name + optional extras + optional
# version constraint. Examples that must pass:
#   requests   discord.py   requests==2.31.0   httpx>=0.27
#   requests[security]   uvicorn[standard]>=0.30
# Examples that must FAIL (injection / garbage):
#   requests; rm -rf /     foo && bar     $(curl evil)
_REQUIREMENT_RE = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._-]*"          # package name
    r"(?:\[[A-Za-z0-9,_-]+\])?"             # optional extras
    r"(?:\s*(?:==|>=|<=|~=|!=|<|>)\s*[A-Za-z0-9.*+!_-]+)?$"  # optional version
)

_VENV_LOCK = threading.RLock()

_INSTALL_TIMEOUT_S = 300  # pip can be slow on a big wheel; cap at 5 min.


def instance_venv_dir(layout: Any) -> Path:
    """Return ``<instance>/venv`` (may not exist yet)."""
    return layout.root / "venv"


def venv_python(layout: Any) -> Path:
    """Path to the instance venv's python interpreter.

    POSIX layout (``bin/python``). Windows would be ``Scripts/python.exe``
    — jaeger targets macOS/Linux so we use the POSIX path."""
    return instance_venv_dir(layout) / "bin" / "python"


def venv_pip(layout: Any) -> Path:
    """Path to the instance venv's pip."""
    return instance_venv_dir(layout) / "bin" / "pip"


def venv_exists(layout: Any) -> bool:
    """An interpreter file is insufficient: copied macOS binaries can lack dylibs."""
    py = venv_python(layout)
    if not py.is_file():
        return False
    try:
        check = subprocess.run([str(py), "-I", "-B", "-c", "import sys; print(sys.prefix)"],
                               capture_output=True, text=True, timeout=10)
        return check.returncode == 0 and Path(check.stdout.strip()).resolve() == instance_venv_dir(layout).resolve()
    except (OSError, subprocess.SubprocessError, ValueError):
        return False


def ensure_venv(layout: Any) -> Path:
    """Create or repair the interpreter while retaining installed packages.

    Symlinks preserve the base interpreter's shared-library location on macOS.
    A broken existing interpreter is backed up before repair; a Python minor
    version change requires explicit migration rather than losing packages.
    """
    with _VENV_LOCK:
        vdir = instance_venv_dir(layout)
        if venv_exists(layout):
            return vdir
        existing = vdir.exists()
        cfg = vdir / "pyvenv.cfg"
        if existing and cfg.exists():
            match = re.search(r"^version\s*=\s*(\d+)\.(\d+)", cfg.read_text(), re.M)
            if match and tuple(map(int, match.groups())) != sys.version_info[:2]:
                raise RuntimeError("instance venv uses another Python version; migrate it explicitly to retain packages")
        if existing:
            backup = Path(tempfile.mkdtemp(prefix="interpreter-backup-", dir=str(vdir)))
            # Keep the old binaries/config for recovery, never delete site-packages.
            for name in ("python", "python3", f"python{sys.version_info.major}.{sys.version_info.minor}"):
                path = vdir / "bin" / name
                if path.exists() or path.is_symlink():
                    os.replace(path, backup / name)
            if cfg.exists():
                import shutil
                shutil.copy2(cfg, backup / cfg.name)
        builder = _stdlib_venv.EnvBuilder(
            system_site_packages=False, with_pip=not venv_pip(layout).exists(),
            symlinks=True, upgrade_deps=False,
        )
        builder.create(str(vdir))
        if not venv_exists(layout):
            raise RuntimeError("instance venv interpreter failed its startup probe")
        return vdir


def is_valid_requirement(spec: str) -> bool:
    """True when ``spec`` is a safe pip requirement string.

    Rejects shell metacharacters, spaces around the name, and anything
    that doesn't look like ``name[extras]<op>version``. Defense in depth
    — installs go through ``subprocess`` with an argv list (never
    ``shell=True``) so injection isn't possible regardless, but a strict
    allowlist keeps obviously-bad input out of the pip call entirely."""
    spec = (spec or "").strip()
    if not spec or len(spec) > 128:
        return False
    return bool(_REQUIREMENT_RE.match(spec))


def install_into_venv(
    layout: Any,
    package: str,
    *,
    timeout_s: int = _INSTALL_TIMEOUT_S,
) -> dict[str, Any]:
    """Pip-install ``package`` into the instance venv.

    Creates the venv first if needed. Returns a structured result dict:
      {ok, package, stdout, stderr, exit_code}  on a completed run
      {ok: False, error: ...}                   on validation / setup failure

    NEVER raises to the caller — the agent should see a structured
    error it can surface. Uses an argv list (no shell) so a malicious
    package string can't inject commands."""
    spec = (package or "").strip()
    if not is_valid_requirement(spec):
        return {
            "ok": False,
            "package": spec,
            "error": (f"invalid package spec {spec!r} — must be a plain pip "
                      "requirement like 'requests' or 'httpx>=0.27'"),
        }
    # OSV malware check — refuse a package with a known MAL-* advisory.
    # Fail-open: an unreachable OSV never blocks a legitimate install.
    try:
        from jaeger_os.core.safety.osv_check import check_pypi_package
        malware = check_pypi_package(spec)
    except Exception:  # noqa: BLE001
        malware = None
    if malware:
        return {"ok": False, "package": spec, "error": malware}
    try:
        ensure_venv(layout)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "package": spec,
                "error": f"could not create instance venv: {exc}"}

    pip = venv_pip(layout)
    if not pip.is_file():
        # Fall back to `python -m pip` if the pip shim is missing.
        cmd = [str(venv_python(layout)), "-m", "pip", "install", spec]
    else:
        cmd = [str(pip), "install", spec]

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True, text=True, timeout=timeout_s,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "package": spec,
                "error": f"pip install timed out after {timeout_s}s"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "package": spec,
                "error": f"pip install failed to launch: {exc}"}

    MAX = 8000
    return {
        "ok": proc.returncode == 0,
        "package": spec,
        "exit_code": proc.returncode,
        "stdout": proc.stdout[-MAX:],
        "stderr": proc.stderr[-MAX:],
    }


def list_installed(layout: Any) -> dict[str, Any]:
    """Return the packages installed in the instance venv via
    ``pip list --format=json``. Empty list if the venv doesn't exist."""
    if not venv_exists(layout):
        return {"venv_exists": False, "packages": []}
    pip = venv_pip(layout)
    cmd = ([str(pip), "list", "--format=json"] if pip.is_file()
           else [str(venv_python(layout)), "-m", "pip", "list", "--format=json"])
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        import json
        pkgs = json.loads(proc.stdout) if proc.returncode == 0 else []
    except Exception:  # noqa: BLE001
        pkgs = []
    return {"venv_exists": True, "packages": pkgs}
