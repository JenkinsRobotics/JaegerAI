"""Per-instance subprocess environment — INST-4.

When the user opts in, subprocesses spawned by the agent see
``HOME=<instance>/home/`` instead of the operating user's home.
That gives each instance its own ``.gitconfig``, ``.ssh/``,
``.npmrc``, etc., so:

  - Skill-authoring ``git commit`` calls use the agent's identity,
    not the user's.
  - ``ssh`` from the agent picks the instance's deploy key.
  - npm caches don't bleed across instances.

The opt-in is signalled by the wizard populating
``<instance>/home/.gitconfig`` (or any populated marker — see
``has_instance_home``). When that's absent the helper falls back
to the user's real ``HOME`` so existing 0.1.x instances are
undisturbed.

This module is **pure**: pass it a layout, get back an env dict.
Call sites do their own ``subprocess.run(..., env=...)`` so the
existing argument plumbing stays unchanged.
"""

from __future__ import annotations

import os
from typing import Any

from jaeger_ai.core.instance.instance import InstanceLayout


# Files that, if present in ``<instance>/home/``, count as the user
# having "populated" the per-instance HOME. Any one of these flips
# subprocesses over to the per-instance jail.
_HOME_MARKERS: tuple[str, ...] = (
    ".gitconfig",
    ".ssh/config",
    ".npmrc",
    ".cargo/config.toml",
    ".jaeger-home-marker",  # explicit opt-in even with no other files
)


def has_instance_home(layout: InstanceLayout) -> bool:
    """True when the instance's ``home/`` directory exists AND
    contains at least one marker file. Empty dirs don't count —
    the wizard creates ``home/`` for every instance, but only a
    populated one signals "use me as HOME"."""
    home = layout.home_dir
    if not home.is_dir():
        return False
    for marker in _HOME_MARKERS:
        if (home / marker).exists():
            return True
    return False


def subprocess_env_for_instance(
    layout: InstanceLayout,
    *,
    base_env: dict[str, str] | None = None,
) -> dict[str, str]:
    """Return an env dict suitable for ``subprocess.run(env=...)``.

    When the instance has populated its own ``home/``, ``HOME`` is
    swapped to point at it (and ``USERPROFILE`` on Windows, though
    the agent is Unix-targeted). Otherwise the base env is returned
    unchanged so existing instances keep working with the user's
    real home.

    ``base_env`` defaults to ``os.environ.copy()``. Pass an explicit
    one in tests / for env-restricted spawns.
    """
    env = dict(base_env) if base_env is not None else os.environ.copy()
    if has_instance_home(layout):
        home_path = str(layout.home_dir)
        env["HOME"] = home_path
        # Windows analogue — set even on Unix so cross-platform code
        # paths agree on what HOME means.
        env["USERPROFILE"] = home_path
        # Common subdirs that some tools (ssh, git) look for via
        # absolute defaults — point them at the jail too. Best-effort:
        # tools that hard-code ``~`` instead of $HOME won't pick this
        # up, which is fine — the agent's main offenders (git, ssh,
        # npm) all honour $HOME.
        env["XDG_CONFIG_HOME"] = str(layout.home_dir / ".config")
        env["XDG_CACHE_HOME"] = str(layout.home_dir / ".cache")
    return env


def populate_instance_home(layout: InstanceLayout, *,
                            git_name: str | None = None,
                            git_email: str | None = None,
                            ssh_key_source: str | None = None) -> None:
    """Initialise ``<instance>/home/`` with a per-instance gitconfig
    (and optionally a copied SSH key). Called by the wizard's
    optional Step 7. Idempotent — re-running overwrites cleanly.

    ``git_name`` + ``git_email`` write ``<home>/.gitconfig``.
    ``ssh_key_source`` copies the file to ``<home>/.ssh/id_jaeger``
    (and ``id_jaeger.pub`` if a sibling exists), with 0600 perms.

    Writes a ``.jaeger-home-marker`` file so the env helper picks up
    the jail even when only one of git or ssh is set up — the
    marker is the unambiguous "user opted in" signal.
    """
    home = layout.home_dir
    home.mkdir(parents=True, exist_ok=True)
    home.chmod(0o700)

    if git_name or git_email:
        body = "[user]\n"
        if git_name:
            body += f"  name = {git_name}\n"
        if git_email:
            body += f"  email = {git_email}\n"
        (home / ".gitconfig").write_text(body, encoding="utf-8")

    if ssh_key_source:
        from pathlib import Path
        src = Path(ssh_key_source).expanduser()
        if src.exists() and src.is_file():
            ssh_dir = home / ".ssh"
            ssh_dir.mkdir(exist_ok=True)
            ssh_dir.chmod(0o700)
            dst = ssh_dir / "id_jaeger"
            dst.write_bytes(src.read_bytes())
            dst.chmod(0o600)
            pub = src.with_suffix(src.suffix + ".pub")
            if pub.exists():
                (ssh_dir / "id_jaeger.pub").write_bytes(pub.read_bytes())
                (ssh_dir / "id_jaeger.pub").chmod(0o644)

    # Always drop the marker so the env helper recognises the
    # opt-in even if neither git nor ssh inputs were provided.
    (home / ".jaeger-home-marker").write_text(
        "# This file marks this directory as a per-instance HOME jail.\n"
        "# Removing it makes subprocesses fall back to the user's real HOME.\n"
        "# Written by `jaeger setup` (INST-4).\n",
        encoding="utf-8",
    )


__all__ = [
    "has_instance_home",
    "subprocess_env_for_instance",
    "populate_instance_home",
]
