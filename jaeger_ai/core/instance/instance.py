"""Instance directory: path resolution, layout, lockfile, manifest.

An *instance* is a writable per-robot directory that holds identity, config,
memory, logs, skills, and (M2) credentials. Resolution order:

  1. JAEGER_INSTANCE_DIR env var, if set
  2. /var/lib/jaeger/<instance>/   if running as a system service (uid 0)
  3. ~/.jaeger/<instance>/         user mode (default)

`<instance>` defaults to "default" and can be overridden with
JAEGER_INSTANCE_NAME or via the wizard.

Locking uses fcntl on `.lock` so two Jaeger processes can never share an
instance dir. Stale locks are detected via the PID written into the file
AND (0.8.1) a process-shape check — a recorded pid that's dead, or alive
but not actually a jaeger process (see :mod:`procshape`), is broken
automatically with a loud log instead of wedging every future boot.
"""

from __future__ import annotations

import contextlib
import errno
import fcntl
import os
import shutil
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jaeger_ai.core.instance.procshape import is_real_jaeger_command, pid_cmdline
from jaeger_ai.core.instance.schemas import (
    SCHEMA_VERSION,
    Config,
    Identity,
    Manifest,
    dump_json,
    dump_yaml,
    load_json,
    load_yaml,
)


# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------
# Order (top wins). See docs/instance_layout.md → "Resolver order".
#
#   1. --instance NAME CLI flag (handled by caller; passed to this fn)
#   2. JAEGER_INSTANCE_DIR env var — explicit path (use for sandbox dev
#      via dev/scripts/dev_env.sh; for tests; for one-off destinations).
#   3. JAEGER_INSTANCE_NAME env var → ~/.jaeger/instances/<name>/
#   4. ~/.jaeger/active_instance file → ~/.jaeger/instances/<that>/
#   5. ~/.jaeger/instances/default/
#
# (1) is handled by the caller (CLI argparse) and arrives here as the
# ``name`` argument when present. (2)-(5) are honoured below.
#
# Earlier releases also had:
#   - /var/lib/jaeger/<name>/ when uid==0 (system service mode)
#   - jaeger_os/instance/<name>/ bundled into the source tree
#
# System-service mode is still here; the bundled location is GONE
# (INST-10 in docs/ROADMAP_0.2.0.md) — the wheel ships no
# ``jaeger_os/instance/`` directory and the resolver no longer
# falls through to one. Dev checkouts opt into a sandbox via
# JAEGER_INSTANCE_DIR (see dev/scripts/dev_env.sh).
SYSTEM_ROOT = Path("/var/lib/jaeger")
INSTANCES_DIR_NAME = "instances"
ACTIVE_INSTANCE_FILE = "active_instance"
# jaeger_os/core/instance/instance.py → .parent.parent.parent = jaeger_os/
PACKAGE_ROOT = Path(__file__).resolve().parent.parent.parent

# 0.2.6: operator state lives under ``<install_root>/.jaeger_os/`` —
# sibling to ``jaeger_os/`` — instead of the user's home ``~/.jaeger/``.
# This collapses the two-dir installs Hermes / ComfyUI / A1111 already
# avoid into one place: ``ls <install_root>`` shows the framework
# (``jaeger_os/``) and the operator's state (``.jaeger_os/``) side by
# side. ``git pull`` only touches the framework; ``.jaeger_os/`` is
# gitignored in full.
OPERATOR_STATE_DIR_NAME = ".jaeger_os"


def install_root() -> Path:
    """The directory containing this install — ``$JAEGER_HOME`` when
    set, else the parent of the framework package.

    ``run.sh`` exports ``JAEGER_HOME=$REPO_ROOT`` before invoking
    python, so the env var carries the install location through. The
    PACKAGE_ROOT fallback covers test contexts that import ``jaeger_os``
    directly without going through the launcher.
    """
    override = os.environ.get("JAEGER_HOME", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return PACKAGE_ROOT.parent


def operator_state_root() -> Path:
    """The ``.jaeger_os/`` dir alongside the framework package."""
    return install_root() / OPERATOR_STATE_DIR_NAME


# Legacy alias kept for any internal call-site that still references it
# before the migration sweep finishes. The semantics changed in 0.2.6:
# ``USER_ROOT`` is no longer ``~/.jaeger`` — it's now
# ``<install_root>/.jaeger_os``. The name is preserved to avoid a
# wholesale rename.
USER_ROOT = operator_state_root()


def user_instances_root() -> Path:
    """Where instances live: ``<install_root>/.jaeger_os/instances/``."""
    return operator_state_root() / INSTANCES_DIR_NAME


def active_instance_path() -> Path:
    """Where the sticky-default file lives:
    ``<install_root>/.jaeger_os/active_instance``."""
    return operator_state_root() / ACTIVE_INSTANCE_FILE


def read_active_instance() -> str | None:
    """Read the sticky-default instance name from
    ``~/.jaeger/active_instance``, or ``None`` if the file is missing
    or empty. Whitespace-only contents count as missing."""
    path = active_instance_path()
    if not path.exists():
        return None
    try:
        text = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return text or None


def write_active_instance(name: str | None) -> None:
    """Set the sticky-default instance. ``None`` removes the file.

    Called by ``jaeger instance use <name>``. The wizard does NOT
    write this — it's the user's deliberate "from now on, this one
    is the default" gesture.
    """
    path = active_instance_path()
    if name is None or not name.strip():
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(name.strip() + "\n", encoding="utf-8")


def default_instance_name() -> str:
    """Pick the default instance name. Order:

      1. ``JAEGER_INSTANCE_NAME`` env var (explicit per-shell pin)
      2. ``~/.jaeger/active_instance`` file (sticky default written
         by ``jaeger instance use``)
      3. Literal ``"default"``.
    """
    env = os.environ.get("JAEGER_INSTANCE_NAME", "").strip()
    if env:
        return env
    sticky = read_active_instance()
    if sticky:
        return sticky
    # No env pin and no sticky default. Don't conjure a phantom "default":
    # if the operator has exactly ONE instance, that IS their default (so a
    # bare ``jaeger`` runs it instead of creating a duplicate "default").
    # "default" itself, or any ambiguity, falls through to the literal — and
    # a truly-fresh install (zero instances) still triggers first-boot setup.
    inst_root = operator_state_root() / "instances"
    names = ([p.name for p in inst_root.iterdir()
              if p.is_dir() and ".bak." not in p.name]   # ignore wizard backups
             if inst_root.exists() else [])
    if "default" not in names and len(names) == 1:
        return names[0]
    return "default"


def is_pip_installed() -> bool:
    """True when the package lives under ``site-packages`` /
    ``dist-packages``. Catches pip, pipx, system-wide installs, and
    venvs. Editable installs (``pip install -e .``) and dev checkouts
    are reported False because their resolved path doesn't have a
    site-packages ancestor.

    Exposed for tests, the wizard, ``--doctor`` reporting, and
    ``jaeger update``'s install-method detection.
    """
    return any(
        p.name in ("site-packages", "dist-packages")
        for p in PACKAGE_ROOT.parents
    )


def detect_install_method() -> str:
    """Return one of: ``"pipx"``, ``"pip"``, ``"dev-checkout"``,
    ``"unknown"``. Used by the wizard (INST-3) to stamp the new
    instance's ``distribution.yaml`` and by ``jaeger update``
    (INST-7) to pick the right upgrade command.

    Detection cascade:
      - Not pip-installed → ``"dev-checkout"`` (running from a source
        tree; editable installs land here).
      - ``pipx`` in ``PACKAGE_ROOT``'s ancestors → ``"pipx"``
        (pipx installs each app under
        ``~/.local/pipx/venvs/<app>/...``).
      - Otherwise pip-installed → ``"pip"``.
    """
    if not is_pip_installed():
        return "dev-checkout"
    for p in PACKAGE_ROOT.parents:
        if p.name == "pipx" or "pipx" in p.parts:
            return "pipx"
    return "pip"


def resolve_instance_dir(name: str | None = None) -> Path:
    """Pick the on-disk path for this instance. See module-level
    docstring for the priority order.

    When ``name`` is passed (i.e. the CLI ``--instance`` flag was
    set), it overrides every env-var / sticky-file lookup. When
    ``name`` is ``None``, ``default_instance_name()`` consults
    env var → sticky file → literal ``"default"``.
    """
    # (2) Explicit path override always wins. Bypasses the nesting —
    # used by the dev sandbox (``sandbox/jros-dev/``) and by tests.
    override = os.environ.get("JAEGER_INSTANCE_DIR", "").strip()
    if override:
        return Path(override).expanduser().resolve()

    inst = name or default_instance_name()

    # System service: use /var/lib/jaeger/<name>/ when running as root.
    # No ``instances/`` nesting here — system-service paths are FHS-shaped.
    if os.geteuid() == 0 and SYSTEM_ROOT.parent.exists():
        return (SYSTEM_ROOT / inst).resolve()

    # User-mode (both pip-installed and dev-checkout-without-sandbox):
    # ``~/.jaeger/instances/<name>/``. The nesting under ``instances/``
    # is the 0.2.0 shape (INST-10) — meta files (active_instance,
    # jaeger.env, backups/) sit at ``~/.jaeger/`` alongside.
    return (user_instances_root() / inst).resolve()


# 0.2.6: ``resolve_user_dir()`` removed along with the User layer.
# Persona/skills/prompts now live inside the per-instance directory at
# ``<install_root>/.jaeger_os/instances/<name>/``. See the architecture
# note in dev docs/architecture/system_runtime_user.md → "0.2.6: two
# layers, not three" for the rationale (each agent is self-contained;
# nothing meaningful was shared across the User-layer boundary).


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class InstanceLayout:
    """Centralized knowledge of where each piece of instance state lives.

    Every other Jaeger module asks the layout for paths — no hard-coded
    strings sprinkled across the codebase. If we ever change a directory
    name (e.g. memory/ → state/), it's a one-line change here.

    Invariant: `root` is always a fully-resolved (symlink-canonicalized)
    path. On macOS `/var` is a symlink to `/private/var`, so without
    canonicalization a `target.relative_to(root)` comparison would fail
    even when `target` is plainly inside `root`. We normalize in
    `__post_init__` so every downstream caller gets the same shape.
    """
    root: Path

    def __post_init__(self) -> None:
        resolved = self.root.expanduser().resolve()
        if resolved != self.root:
            object.__setattr__(self, "root", resolved)

    @property
    def identity_path(self) -> Path:        return self.root / "identity.yaml"
    @property
    def config_path(self) -> Path:          return self.root / "config.yaml"
    @property
    def manifest_path(self) -> Path:        return self.root / "manifest.json"
    @property
    def credentials_dir(self) -> Path:      return self.root / "credentials"
    @property
    def skills_dir(self) -> Path:           return self.root / "skills"
    @property
    def memory_dir(self) -> Path:           return self.root / "memory"
    @property
    def logs_dir(self) -> Path:             return self.root / "logs"
    @property
    def lock_path(self) -> Path:            return self.root / ".lock"
    @property
    def audit_log_path(self) -> Path:       return self.logs_dir / "audit.log"
    @property
    def latency_log_path(self) -> Path:     return self.logs_dir / "latency.jsonl"
    @property
    def distribution_path(self) -> Path:    return self.root / "distribution.yaml"
    @property
    def home_dir(self) -> Path:             return self.root / "home"
    @property
    def workspace_dir(self) -> Path:        return self.root / "workspace"

    def exists(self) -> bool:
        return self.identity_path.exists() and self.config_path.exists() and self.manifest_path.exists()

    def ensure_dirs(self) -> None:
        for d in (self.credentials_dir, self.skills_dir, self.memory_dir,
                  self.logs_dir, self.workspace_dir):
            d.mkdir(parents=True, exist_ok=True)
        # 0700 on credentials/ so an OS-level snoop sees an empty dir at best.
        try:
            os.chmod(self.credentials_dir, 0o700)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Lockfile
# ---------------------------------------------------------------------------
class InstanceLock:
    """Exclusive flock on the instance .lock file.

    Holds an open file handle (kept alive for the process lifetime) and
    writes the holding PID into the file for debug visibility. Stale
    locks from a crashed prior run are detected by a PID-alive check.
    """

    def __init__(self, layout: InstanceLayout) -> None:
        self._path = layout.lock_path
        self._fh: Any = None

    def acquire(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        fh = self._path.open("a+", encoding="utf-8")
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            if exc.errno not in (errno.EWOULDBLOCK, errno.EACCES):
                fh.close()
                raise
            fh.seek(0)
            old = (fh.read() or "").strip()
            fh.close()
            holder = _pid_alive(old)
            if holder is not None:
                raise RuntimeError(
                    f"instance {self._path.parent.name!r} is locked by pid {holder} (still running). "
                    "Refusing to start a second copy."
                ) from exc
            # 0.8.1 field bug #3: stale — either the recorded pid is
            # gone, or it's alive but NOT jaeger-shaped (see
            # _pid_alive's docstring; that case already logged loudly
            # there). Break the lock automatically and retry ONCE
            # instead of making the operator `rm` it by hand — a
            # crashed/broken-bundle launch must not permanently wedge
            # every future boot.
            print(
                f"[jaeger] breaking stale instance lock at {self._path} "
                f"(recorded pid {old or '?'} is gone or not a jaeger process).",
                file=sys.stderr, flush=True,
            )
            with contextlib.suppress(FileNotFoundError):
                self._path.unlink()
            fh = self._path.open("a+", encoding="utf-8")
            try:
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as retry_exc:
                fh.close()
                raise RuntimeError(
                    f"stale lock at {self._path} was broken, but another "
                    "process grabbed it immediately after (a launch race) "
                    "— try again."
                ) from retry_exc

        fh.seek(0)
        fh.truncate()
        fh.write(f"{os.getpid()}\n")
        fh.flush()
        self._fh = fh

    def release(self) -> None:
        if self._fh is None:
            return
        with contextlib.suppress(OSError):
            fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
        with contextlib.suppress(OSError):
            self._fh.close()
        self._fh = None
        with contextlib.suppress(OSError):
            self._path.unlink()


def _pid_alive(pid_str: str) -> int | None:
    """Return the holder's PID if the lock looks genuinely held, else
    ``None`` (stale — caller may break it).

    Two checks, in order (0.8.1 field bug #3 — "stale-lock detection"):

      1. Is the PID alive at all (``os.kill(pid, 0)``)? Dead → stale,
         the classic case. Catchable exits (SIGTERM/SIGINT, any
         exception during boot) already release the lock via
         ``InstanceLock.release()`` — ``boot_for_tui`` and the
         daemon/bridge/TUI entry points all call it from a ``finally``
         — so a truly-dead PID here means an UNCATCHABLE exit
         (SIGKILL, OOM-kill, power loss): exactly the field report
         ("a crashed launch left a headless Python agent holding the
         instance lock").
      2. Is the alive PID actually **jaeger-shaped**? A live PID that
         is NOT a jaeger process — because the OS recycled the dead
         jaeger's PID for something unrelated before this check ran,
         or because something else entirely is squatting the number —
         must not block a fresh boot forever just for being alive.
         Verified with the same ``ps``-based cmdline check
         ``jaeger kill`` uses (:mod:`jaeger_os.core.instance.
         procshape`) so lock-breaking and the kill sweep never
         disagree about what "jaeger" means. A cmdline lookup that
         can't be read (``ps`` unavailable/timeout) fails CLOSED —
         treated as still held — so a transient ``ps`` hiccup never
         breaks a lock that is genuinely in use.
    """
    try:
        pid = int(pid_str)
    except (TypeError, ValueError):
        return None
    if pid <= 0:
        return None
    try:
        os.kill(pid, 0)
    except OSError as exc:
        if exc.errno == errno.ESRCH:
            return None
        # EPERM: process exists, owned by another user — fall through
        # to the cmdline check below (``ps`` can usually still read it).

    cmdline = pid_cmdline(pid)
    if cmdline is not None and not is_real_jaeger_command(cmdline):
        print(
            f"[jaeger] instance lock claims pid {pid}, but that pid is "
            f"NOT a jaeger process (cmdline: {cmdline!r}) — treating the "
            "lock as stale and breaking it.",
            file=sys.stderr, flush=True,
        )
        return None
    return pid


# ---------------------------------------------------------------------------
# Manifest version check
# ---------------------------------------------------------------------------
class CoreVersionMismatch(RuntimeError):
    """Raised when the installed core version differs from the one the
    instance was created against. M2 will add a migration runner; for
    M1 we refuse-to-start and surface a clear instruction."""


def check_manifest(layout: InstanceLayout) -> Manifest:
    manifest = load_json(layout.manifest_path, Manifest)
    if manifest.schema_version != SCHEMA_VERSION:
        raise CoreVersionMismatch(
            f"instance {manifest.instance_name!r} was created against core "
            f"{manifest.schema_version!r}, but installed core is {SCHEMA_VERSION!r}. "
            "Run `python main.py jaeger_os --migrate` to apply pending "
            "migrations, or back up the instance and re-run the wizard."
        )
    return manifest


def touch_manifest_started(layout: InstanceLayout, manifest: Manifest) -> None:
    dump_json(layout.manifest_path, manifest.with_started_now())


# ---------------------------------------------------------------------------
# Backup-rename (used by the wizard for re-run safety)
# ---------------------------------------------------------------------------
def backup_instance_dir(layout: InstanceLayout) -> Path:
    """Rename the existing instance dir aside so the wizard can rebuild
    cleanly without ever destroying state. Returns the backup path."""
    if not layout.root.exists():
        return layout.root  # nothing to back up
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    backup = layout.root.with_name(f"{layout.root.name}.bak.{ts}")
    shutil.move(str(layout.root), str(backup))
    print(f"[jaeger] backed up existing instance to {backup}", file=sys.stderr, flush=True)
    return backup


# ---------------------------------------------------------------------------
# Convenience: load all three files in one shot (raises if missing/invalid)
# ---------------------------------------------------------------------------
def load_instance(layout: InstanceLayout) -> tuple[Identity, Config, Manifest]:
    identity = load_yaml(layout.identity_path, Identity)
    config = load_yaml(layout.config_path, Config)
    manifest = check_manifest(layout)
    return identity, config, manifest
