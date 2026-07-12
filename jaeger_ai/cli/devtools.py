#!/usr/bin/env python3
"""jaeger_os.cli.devtools — the developer toolbox behind `jaeger --dev`.

Replaces the old repo-root launch.py (removed 2026-07-05): the windowed
dev shell is JaegerOS-dev.app (double-click it, or `jaeger --dev` builds +
runs it); this module keeps the dev TUI + utility verbs.

Surfaces (CLI/TUI -> windowed-app migration, 2026-06-14):

   ./launch          Windowed app — the Swift app if available, otherwise
                     the PySide6 shell.
   ./launch --tui    CLI/TUI — the in-process TUI agent (this terminal
                     becomes the TUI).

The in-process TUI loads the plugin stack directly:

   - persistent Kokoro player + avaudio_io bridge       (kokoro_tts/)
   - Whisper STT hardening (two-pass + fast/accurate)   (nodes/whisper_stt/engine/)
   - persona prefill framework                          (instance bundle)
   - skill system v3 (multi-axis manifest)              (agent/skill_registry/)
   - Gemma 4 + updated registry                         (core/models/)
   - bench infra (writer/aggregator dir fix)            (core/bench/)

   ./launch                   boot the windowed JROS app
   ./launch --tui             boot the in-process TUI in this terminal
   ./launch --tui --no-voice   ... skipping voice startup
   ./launch --stop             kill a lingering TUI singleton
   ./launch --restart          stop, then boot the TUI
   ./launch --status           show whether a TUI is running
   ./launch --reset-audio      sudo killall coreaudiod
   ./launch --clean-logs       truncate <instance>/run/jaeger.log to 0
   ./launch --health           preflight checks

The terminal becomes the TUI.  Ctrl-C / ``/quit`` ends the session;
Gemma + Kokoro + Whisper unload cleanly with the process.

Every run uses the dev instance at
``.jaeger_os/instances/jros-dev/`` — gitignored, so it never ships to
end users.  `jaeger --dev` boots the same instance through this launcher.
"""

from __future__ import annotations

# ─── self-relocate onto the repo's .venv ────────────────────────────────
# ``#!/usr/bin/env python3`` resolves to whatever ``python3`` is first on
# PATH — on this machine that's the pyenv 3.13.7 shim, which has a broken
# OpenSSL build (``unsupported hash type blake2b/blake2s`` floods stderr
# before anything else runs).  The repo's .venv ships a known-good 3.11,
# so re-exec under it before we import anything that could touch hashlib.
# (The companion ``./launch`` bash wrapper also handles this — this is
# the fallback for direct ``python launch.py`` invocations.)
import os as _os
import sys as _sys
from pathlib import Path as _Path
_REPO_ROOT = _Path(__file__).resolve().parents[2]
_VENV_DIR = _REPO_ROOT / ".venv"
_VENV_PY = _VENV_DIR / "bin" / "python"
if _VENV_PY.exists() and not _sys.executable.startswith(str(_VENV_DIR)):
    _os.execv(str(_VENV_PY), [str(_VENV_PY), __file__, *_sys.argv[1:]])
# ────────────────────────────────────────────────────────────────────────

import argparse
import os
import shutil
import signal
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
# The single dev instance, shared with `jaeger --dev`. Lives under the
# repo's gitignored operator-state root (`.jaeger_os/`), so it never
# ships to end users. (Pre-2026-06-19 this was an isolated `sandbox/`
# copy — removed; the two drifted, which only caused confusion.)
DEV_INSTANCE = REPO / ".jaeger_os" / "instances" / "jros-dev"
VENV_PY = REPO / ".venv" / "bin" / "python"
INSTANCE_NAME = "jros-dev"
# Legacy daemon pid-file (0.3.0 pre-pivot architecture).  Stays in tree
# but the launcher no longer spawns it — if a previous --daemon run
# left one lingering, cmd_boot stops it during the boot scroll so the
# TUI can acquire the instance lock.
LEGACY_DAEMON_PID = DEV_INSTANCE / "run" / "jaeger.pid"


# ─── pretty output ────────────────────────────────────────────────────

def say(msg: str, *, prefix: str = "launch") -> None:
    print(f"\033[2m[{prefix}]\033[0m {msg}", flush=True)


def ok(msg: str) -> None:
    print(f"\033[32m✓\033[0m {msg}", flush=True)


def warn(msg: str) -> None:
    print(f"\033[33m⚠\033[0m {msg}", flush=True)


def fail(msg: str) -> None:
    print(f"\033[31m✗\033[0m {msg}", flush=True)


# ─── boot scroll (Gundam-style system check) ──────────────────────────
#
# Mech-cockpit aesthetic: each subsystem prints a "▶ NAME ........... [ .. ]"
# line that flips to "▶ NAME ........... [ READY ]" once verified.  The
# in-process TUI does the heavy warmup (Gemma load, Kokoro prime,
# Whisper warm) AFTER we exec into it — so the scroll here covers only
# what launch.py can check from outside: sandbox bundle, library
# import, legacy-daemon stop, instance lock, model file on disk.

def _load_tui_banner() -> str:
    """Canonical block-letter banner from jaeger_os.interfaces.tui.banner,
    wrapped in a cyan box with a SYSTEM BOOT subtitle."""
    try:
        if str(REPO) not in sys.path:
            sys.path.insert(0, str(REPO))
        from jaeger_ai.interfaces.tui.banner import JAEGER_ASCII, TAGLINE
        from jaeger_ai import __version__ as JAEGER_VERSION
    except Exception:  # noqa: BLE001
        return "\n\033[36m\033[1mJAEGER-OS\033[0m\n\n"

    banner_lines = JAEGER_ASCII.splitlines()
    banner_w = max(len(ln) for ln in banner_lines)
    inner_pad = 3
    box_w = banner_w + inner_pad * 2

    def pad(line: str) -> str:
        return f"{' ' * inner_pad}{line}{' ' * (banner_w - len(line))}{' ' * inner_pad}"

    def center(text: str) -> str:
        gap = box_w - len(text)
        left = gap // 2
        right = gap - left
        return f"{' ' * left}{text}{' ' * right}"

    subtitle = f"S Y S T E M    B O O T    ·    v{JAEGER_VERSION}"
    horiz = "═" * box_w
    rows: list[str] = []
    rows.append(f"\033[36m╔{horiz}╗\033[0m")
    rows.append(f"\033[36m║\033[0m{' ' * box_w}\033[36m║\033[0m")
    for line in banner_lines:
        rows.append(
            f"\033[36m║\033[0m\033[36m\033[1m{pad(line)}\033[0m\033[36m║\033[0m"
        )
    rows.append(f"\033[36m║\033[0m{' ' * box_w}\033[36m║\033[0m")
    rows.append(
        f"\033[36m║\033[0m\033[2m{center(subtitle)}\033[0m\033[36m║\033[0m"
    )
    rows.append(f"\033[36m║\033[0m{' ' * box_w}\033[36m║\033[0m")
    rows.append(f"\033[36m╚{horiz}╝\033[0m")
    rows.append("")
    rows.append(f"\033[2m{TAGLINE}\033[0m")
    rows.append("")
    return "\n" + "\n".join(rows) + "\n"


BOOT_HEADER = _load_tui_banner()


def _badge(status: str) -> str:
    """Color-coded status label centered in a 9-char slot."""
    colors = {
        "INIT":   "\033[36m",   # cyan
        "READY":  "\033[32m",   # green
        "NOMINAL": "\033[32m",  # green
        "WARMING": "\033[33m",  # yellow
        "SKIP":   "\033[2m",    # dim
        "FAIL":   "\033[31m",   # red
        "STOP":   "\033[33m",   # yellow
        "→":      "\033[36m",   # cyan
    }
    c = colors.get(status, "")
    return f"{c}{status.center(9)}\033[0m"


def scroll(stage: str, status: str, *, suffix: str = "") -> None:
    """Print one row of the boot scroll: ``▶ NAME ........ [ STATUS ] suffix``."""
    dots = "." * max(0, 48 - len(stage))
    line = f"\033[2m▶\033[0m  {stage} {dots} [{_badge(status)}]"
    if suffix:
        line += f"  {suffix}"
    print(line, flush=True)


def _legacy_daemon_pid() -> int | None:
    """Read the legacy daemon's pid file; return pid if it's alive."""
    if not LEGACY_DAEMON_PID.exists():
        return None
    try:
        pid = int(LEGACY_DAEMON_PID.read_text().strip())
    except (ValueError, OSError):
        return None
    try:
        os.kill(pid, 0)
        return pid
    except (OSError, ProcessLookupError):
        return None


def _stop_legacy_daemon(pid: int, *, timeout_s: float = 5.0) -> bool:
    """SIGTERM the lingering daemon and wait for it to exit so the
    instance lock is released before the TUI tries to acquire it."""
    import time as _time
    try:
        os.kill(pid, signal.SIGTERM)
    except (OSError, ProcessLookupError):
        return True
    deadline = _time.monotonic() + timeout_s
    while _time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except (OSError, ProcessLookupError):
            # Clean up the stale pid file too.
            try:
                LEGACY_DAEMON_PID.unlink()
            except OSError:
                pass
            return True
        _time.sleep(0.1)
    return False


def _check_avaudio_bridge() -> tuple[bool, str]:
    """Import the PyObjC AVAudioEngine bridge — real check, no cosmetic.
    The bridge fails to load on hosts missing pyobjc-framework-AVFoundation
    (CI / non-Mac).  Importing the module also resolves the OutputStream
    + InputStream classes so we know they're constructible."""
    try:
        if str(REPO) not in sys.path:
            sys.path.insert(0, str(REPO))
        from jaeger_os.core.audio.avaudio_io import OutputStream, InputStream  # noqa: F401
    except Exception as exc:  # noqa: BLE001
        return False, f"import failed: {exc}"
    return True, "OutputStream + InputStream importable (PyObjC)"


def _check_whisper_assets() -> tuple[bool, str]:
    """Real check: both Whisper GGML model files exist on disk and
    pywhispercpp's Model class imports.  These are what
    ``jaeger_whisper_stt.nodes.whisper_stt.engine.two_pass`` loads at TUI boot."""
    try:
        from pywhispercpp.constants import MODELS_DIR
        from pywhispercpp.model import Model  # noqa: F401
    except Exception as exc:  # noqa: BLE001
        return False, f"pywhispercpp import failed: {exc}"
    cache = Path(MODELS_DIR)
    needed = [("base.en", "ggml-base.en.bin"),
              ("medium.en", "ggml-medium.en.bin")]
    missing = []
    sizes = []
    for label, fname in needed:
        p = cache / fname
        if not p.exists():
            missing.append(label)
        else:
            sizes.append(f"{label} {p.stat().st_size / 1024**2:.0f}MB")
    if missing:
        return False, f"missing GGML weights: {', '.join(missing)} in {cache}"
    return True, " + ".join(sizes)


def _check_kokoro_package() -> tuple[bool, str]:
    """Real check: kokoro package imports + report version.  The TUI's
    Kokoro warm step will load weights at boot — failure there is a
    different code path; here we verify the package is installed."""
    try:
        import kokoro  # noqa: F401
        version = getattr(kokoro, "__version__", "unknown")
    except Exception as exc:  # noqa: BLE001
        return False, f"kokoro import failed: {exc}"
    try:
        if str(REPO) not in sys.path:
            sys.path.insert(0, str(REPO))
        from jaeger_kokoro_tts.nodes.kokoro_tts.persistent_player import (
            PersistentKokoroPlayer,
        )
        _ = PersistentKokoroPlayer  # avoid F401
    except Exception as exc:  # noqa: BLE001
        return False, f"persistent_player import failed: {exc}"
    return True, f"kokoro v{version} + PersistentKokoroPlayer importable"


def _check_skill_matrix(env: dict[str, str]) -> tuple[bool, str]:
    """Real check: resolve the instance layout, walk
    ``<instance>/skills/`` via ``discover_skills``, report count.  This
    exercises the v3 manifest schema (any malformed manifest raises
    here, not on first agent turn)."""
    try:
        if str(REPO) not in sys.path:
            sys.path.insert(0, str(REPO))
        # The discovery helpers read env vars (JAEGER_HOME etc.) to find
        # the instance — propagate them temporarily for this check.
        saved = {k: os.environ.get(k) for k in
                 ("JAEGER_HOME", "JAEGER_INSTANCE_DIR", "JAEGER_INSTANCE_NAME")}
        for k in saved:
            if env.get(k):
                os.environ[k] = env[k]
        try:
            from jaeger_ai.core.instance.instance import (
                resolve_instance_dir,
            )
            from jaeger_ai.core.instance.instance import InstanceLayout
            from jaeger_ai.agent.skill_registry.skill_loader import discover_skills
            from jaeger_ai.agent.skill_registry.playbook_skills import discover_playbooks
            root = Path(resolve_instance_dir(INSTANCE_NAME))
            layout = InstanceLayout(root=root)
            skills = discover_skills(layout)
            playbooks = discover_playbooks()
        finally:
            # Restore env (some keys may have been unset).
            for k, v in saved.items():
                if v is None and k in os.environ:
                    del os.environ[k]
                elif v is not None:
                    os.environ[k] = v
    except Exception as exc:  # noqa: BLE001
        return False, f"discover failed: {exc}"
    return True, f"{len(skills)} skill(s) + {len(playbooks)} playbook(s) discovered"


def _check_instance_manifest() -> tuple[bool, str]:
    """Real check: load + validate the instance manifest schema."""
    try:
        if str(REPO) not in sys.path:
            sys.path.insert(0, str(REPO))
        from jaeger_ai.core.instance.instance import InstanceLayout
        from jaeger_ai.core.instance.schemas import Manifest, load_yaml
        layout = InstanceLayout(root=DEV_INSTANCE)
        if not layout.manifest_path.exists():
            return False, f"manifest missing at {layout.manifest_path}"
        manifest = load_yaml(layout.manifest_path, Manifest)
        return True, (f"schema_version={manifest.schema_version}  "
                      f"instance={manifest.instance_name!r}")
    except Exception as exc:  # noqa: BLE001
        return False, f"manifest load failed: {exc}"


def _check_tui_importable() -> tuple[bool, str]:
    """Real check: import the TUI module + its run() entry to confirm
    the post-exec target won't crash on a stale import path."""
    try:
        if str(REPO) not in sys.path:
            sys.path.insert(0, str(REPO))
        from jaeger_ai.interfaces.tui.app import run as _tui_run  # noqa: F401
    except Exception as exc:  # noqa: BLE001
        return False, f"TUI import failed: {exc}"
    return True, "jaeger_ai.interfaces.tui.app.run loaded"


def _model_file_on_disk(env: dict[str, str]) -> tuple[bool, str]:
    """Resolve the configured LLM model and return (exists, label)."""
    config_yaml = DEV_INSTANCE / "config.yaml"
    if not config_yaml.exists():
        return False, "no config.yaml"
    try:
        text = config_yaml.read_text()
    except OSError:
        return False, "config.yaml unreadable"
    raw = ""
    for line in text.splitlines():
        if line.strip().startswith("model_path:"):
            raw = line.split(":", 1)[1].strip().strip('"\'')
            break
    if not raw:
        return False, "model_path missing from config.yaml"
    if raw.startswith("/"):
        p = Path(raw)
        if p.exists():
            return True, f"{p.name} ({p.stat().st_size / 1024 ** 3:.1f} GB)"
        return False, f"not at {raw}"
    try:
        if str(REPO) not in sys.path:
            sys.path.insert(0, str(REPO))
        from jaeger_ai.core.models.model_resolver import resolve_model_path
        resolved = resolve_model_path(raw)
    except Exception as exc:  # noqa: BLE001
        return False, f"resolver error: {exc}"
    if resolved and Path(resolved).exists():
        p = Path(resolved)
        return True, f"{raw} → {p.name} ({p.stat().st_size / 1024 ** 3:.1f} GB)"
    return False, f"{raw!r} unresolvable"


# ─── dev env ──────────────────────────────────────────────────────────

def dev_env() -> dict[str, str]:
    """Build the env the TUI subprocess inherits.

    Points JAEGER_HOME / JAEGER_INSTANCE_* at the dev instance so the
    TUI's instance resolver picks up ``.jaeger_os/instances/jros-dev/``.
    PYTHONPATH puts the top-level ``jaeger_os/`` first so the TUI imports
    the code you're editing, not a stale install."""
    env = dict(os.environ)
    env["JAEGER_HOME"] = str(DEV_INSTANCE.parent.parent)
    env["JAEGER_INSTANCE_DIR"] = str(DEV_INSTANCE)
    env["JAEGER_INSTANCE_NAME"] = INSTANCE_NAME
    pp = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{REPO}:{pp}" if pp else str(REPO)
    return env


def verify_library_path(env: dict[str, str], *, quiet: bool = False) -> bool:
    """Confirm ``import jaeger_ai`` resolves to the top-level package,
    not a stale install or the deleted sandbox copy."""
    proc = subprocess.run(
        [str(VENV_PY), "-c", "import jaeger_ai; print(jaeger_ai.__file__)"],
        env=env, capture_output=True, text=True,
    )
    if proc.returncode != 0:
        fail(f"import jaeger_ai failed: {proc.stderr.strip()}")
        return False
    resolved = Path(proc.stdout.strip()).parent.resolve()
    expected = (REPO / "jaeger_ai").resolve()
    if resolved != expected:
        fail(f"jaeger_ai resolves to {resolved}, expected {expected}")
        return False
    if not quiet:
        ok(f"library    {resolved}")
    return True


# ─── TUI singleton management ─────────────────────────────────────────
#
# The in-process TUI takes an exclusive lock on the instance (so two
# TUIs can't load Gemma into the same instance dir).  We don't manage
# that lock here — we just look up the running pid via pgrep so
# --status / --stop can report it.

def tui_running() -> int | None:
    """Returns the pid of a running in-process TUI, or None."""
    proc = subprocess.run(
        ["pgrep", "-f", "jaeger_ai.interfaces.tui"],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        return None
    for line in proc.stdout.split():
        try:
            pid = int(line)
        except ValueError:
            continue
        # pgrep matches this launch.py if the user's invocation
        # included "jaeger_ai.interfaces.tui" in argv — filter ourselves
        # out by checking the pid isn't our own or our parent.
        if pid in (os.getpid(), os.getppid()):
            continue
        return pid
    return None


def tui_stop() -> None:
    pid = tui_running()
    if pid is None:
        return
    say(f"stopping TUI (pid={pid})…")
    try:
        os.kill(pid, signal.SIGTERM)
    except (OSError, ProcessLookupError):
        pass


# ─── housekeeping commands ────────────────────────────────────────────

def reset_audio() -> int:
    """Force coreaudiod to respawn — the canonical fix for the
    ``AVAudioEngine output start failed: error 2003329396`` wedge.
    Prompts for the sudo password in YOUR terminal (won't run headless).
    """
    say("sudo killall coreaudiod  (you'll be prompted for password)…")
    proc = subprocess.run(["sudo", "killall", "coreaudiod"])
    if proc.returncode != 0:
        fail(f"killall failed (rc={proc.returncode})")
        return proc.returncode
    ok("coreaudiod killed — macOS will respawn it in ~1s")
    ok("relaunch the TUI; audio should be unwedged")
    return 0


def clean_logs() -> int:
    """Truncate the instance log to 0 bytes in place."""
    log = DEV_INSTANCE / "run" / "jaeger.log"
    if not log.exists():
        warn(f"no log at {log}")
        return 0
    size_before = log.stat().st_size
    try:
        with open(log, "w"):
            pass
    except OSError as exc:
        fail(f"couldn't truncate {log}: {exc}")
        return 1
    ok(f"truncated jaeger.log ({size_before / 1024 / 1024:.1f} MB → 0 B)")
    return 0


def health(env: dict[str, str]) -> int:
    """``launch --health`` — delegates to the ONE doctor (``jaeger
    doctor``). Launch keeps NO health checks of its own: the doctor
    (deps/config + runtime substrate, ``core.diagnostics.run_doctor``)
    is the single source for both the user-facing CLI and this launcher.
    Runs against the dev instance via the dev env."""
    return subprocess.run(
        [str(VENV_PY), "-m", "jaeger_ai.cli.run", "--doctor", "--doctor-check"],
        env=env,
    ).returncode


# ─── high-level actions ───────────────────────────────────────────────

def cmd_status(env: dict[str, str]) -> int:
    print()
    print(f"dev instance : {DEV_INSTANCE}")
    verify_library_path(env)
    pid = tui_running()
    if pid is not None:
        ok(f"TUI   running pid={pid}")
    else:
        print("\033[2m  TUI   not running\033[0m")
    print()
    return 0


def cmd_stop(env: dict[str, str]) -> int:
    tui_stop()
    ok("stopped")
    return 0


def cmd_boot(env: dict[str, str], *, no_voice: bool) -> int:
    """Gundam-style boot scroll, then ``os.execvpe`` into
    ``python -m jaeger_os.interfaces.tui``.  Each row of the scroll is
    something launch.py can actually verify from outside the TUI; the
    heavy warmup (Gemma load, Kokoro prime, Whisper warm) runs INSIDE
    the TUI process once we hand off.  The "▶ NEURAL CORE / AUDITORY
    CORTEX / VOCAL SYNTHESIZER" lines mark the work the TUI is about
    to start so the operator sees the cockpit lighting up the way the
    pre-pivot launcher did."""
    import time as _time
    boot_start = _time.monotonic()

    if not VENV_PY.exists():
        fail(f".venv not at {VENV_PY} — run ./install.sh first")
        return 1

    print(BOOT_HEADER)

    # ── COCKPIT VALIDATION ──────────────────────────────────────────
    scroll("COCKPIT VALIDATION", "INIT", suffix="dev instance + launch profile")
    if not DEV_INSTANCE.exists():
        scroll("COCKPIT VALIDATION", "FAIL",
               suffix=f"dev instance missing: {DEV_INSTANCE}")
        say("run ./run.sh setup jros-dev to create it")
        return 1
    scroll("COCKPIT VALIDATION", "READY", suffix=str(DEV_INSTANCE))

    # ── CORE FRAMEWORK LINK ─────────────────────────────────────────
    scroll("CORE FRAMEWORK LINK", "INIT",
           suffix="verifying jaeger_ai imports resolve to repo")
    if not verify_library_path(env, quiet=True):
        scroll("CORE FRAMEWORK LINK", "FAIL")
        return 1
    scroll("CORE FRAMEWORK LINK", "READY", suffix=str(REPO / "jaeger_ai"))

    # ── LEGACY DAEMON (archived 0.3.0 path) ─────────────────────────
    # If a previous ``--daemon`` run left a daemon holding the
    # instance lock, the in-process TUI can't acquire it.  Stop the
    # old daemon as part of the scroll so the operator sees the lock
    # get released.
    legacy_pid = _legacy_daemon_pid()
    if legacy_pid is not None:
        scroll("LEGACY DAEMON", "STOP",
               suffix=f"pid={legacy_pid} — releasing instance lock")
        if not _stop_legacy_daemon(legacy_pid):
            scroll("LEGACY DAEMON", "FAIL",
                   suffix=f"pid {legacy_pid} won't exit")
            return 1
        scroll("LEGACY DAEMON", "READY",
               suffix=f"pid {legacy_pid} stopped; lock released")
    else:
        scroll("LEGACY DAEMON", "SKIP", suffix="not running (archived path)")

    # ── INSTANCE LOCK ───────────────────────────────────────────────
    # InstanceLock uses ``jaeger.pid`` as the lock file: the lock is
    # "held" if jaeger.pid exists AND the pid in it is alive.  After
    # _stop_legacy_daemon, both jaeger.pid is gone AND the pid is dead.
    # We re-check in case some other process took the lock between
    # then and now.
    if _legacy_daemon_pid() is not None:
        scroll("INSTANCE LOCK", "FAIL",
               suffix="instance lock re-acquired by another process")
        return 1
    scroll("INSTANCE LOCK", "READY", suffix="available for in-process TUI")

    # ── INSTANCE MANIFEST (real load + schema validation) ──────────
    scroll("INSTANCE MANIFEST", "INIT",
           suffix="loading + validating <instance>/manifest.yaml")
    ok_m, label = _check_instance_manifest()
    if not ok_m:
        scroll("INSTANCE MANIFEST", "FAIL", suffix=label)
        return 1
    scroll("INSTANCE MANIFEST", "READY", suffix=label)

    # ── NEURAL CORE (Gemma weights — real file existence check) ────
    scroll("NEURAL CORE       (Gemma weights)", "INIT",
           suffix="resolving model_path → GGUF on disk")
    found, label = _model_file_on_disk(env)
    if not found:
        scroll("NEURAL CORE       (Gemma weights)", "FAIL", suffix=label)
        return 1
    scroll("NEURAL CORE       (Gemma weights)", "READY", suffix=label)

    # ── AVAUDIO BRIDGE (real import) ────────────────────────────────
    scroll("AVAUDIO BRIDGE", "INIT",
           suffix="importing PyObjC AVAudioEngine wrapper")
    ok_a, label = _check_avaudio_bridge()
    if not ok_a:
        scroll("AVAUDIO BRIDGE", "FAIL", suffix=label)
        return 1
    scroll("AVAUDIO BRIDGE", "READY", suffix=label)

    # ── AUDITORY CORTEX (real Whisper asset + module check) ────────
    scroll("AUDITORY CORTEX   (Whisper STT)", "INIT",
           suffix="checking GGML weights + pywhispercpp import")
    ok_w, label = _check_whisper_assets()
    if not ok_w:
        scroll("AUDITORY CORTEX   (Whisper STT)", "FAIL", suffix=label)
        return 1
    scroll("AUDITORY CORTEX   (Whisper STT)", "READY", suffix=label)

    # ── VOCAL SYNTHESIZER (real Kokoro package check) ──────────────
    scroll("VOCAL SYNTHESIZER (Kokoro TTS)", "INIT",
           suffix="importing kokoro + persistent_player")
    ok_k, label = _check_kokoro_package()
    if not ok_k:
        scroll("VOCAL SYNTHESIZER (Kokoro TTS)", "FAIL", suffix=label)
        return 1
    scroll("VOCAL SYNTHESIZER (Kokoro TTS)", "READY", suffix=label)

    # ── SKILL MATRIX (real registry walk + v3 manifest validation) ─
    scroll("SKILL MATRIX      (v3 registry)", "INIT",
           suffix="walking <instance>/skills/ + validating manifests")
    ok_s, label = _check_skill_matrix(env)
    if not ok_s:
        scroll("SKILL MATRIX      (v3 registry)", "FAIL", suffix=label)
        return 1
    scroll("SKILL MATRIX      (v3 registry)", "READY", suffix=label)

    # ── TUI MODULE (real import — confirms the post-exec target loads) ──
    scroll("OPERATOR INTERFACE", "INIT",
           suffix="importing jaeger_ai.interfaces.tui")
    ok_t, label = _check_tui_importable()
    if not ok_t:
        scroll("OPERATOR INTERFACE", "FAIL", suffix=label)
        return 1
    scroll("OPERATOR INTERFACE", "READY", suffix=label)

    # ── Behaviour overrides ─────────────────────────────────────────
    if no_voice:
        env = dict(env)
        env["JAEGER_TUI_NO_VOICE"] = "1"
        scroll("VOICE BEHAVIOR", "SKIP",
               suffix="--no-voice: mic + Kokoro skipped on TUI boot")

    # ── HANDOFF ─────────────────────────────────────────────────────
    scroll("OPERATOR INTERFACE", "→",
           suffix=f"handing terminal to rich-tui (boot {_time.monotonic() - boot_start:.1f}s)")
    print()
    sys.stdout.flush()

    os.execvpe(
        str(VENV_PY),
        [str(VENV_PY), "-m", "jaeger_ai.interfaces.tui",
         "--instance", INSTANCE_NAME],
        env,
    )
    fail("could not exec TUI")
    return 1



def cmd_boot_windowed(env: dict[str, str], dev: bool = False) -> int:
    """Exec into the windowed-app shell — PySide6 menu-bar tray + chat
    window. The agent + model load INSIDE that process, on the main
    thread (Metal-safe), before the window appears — so expect a short
    load on boot, same as the TUI."""
    if not VENV_PY.exists():
        fail(f".venv not at {VENV_PY} — run ./install.sh first")
        return 1
    if not DEV_INSTANCE.exists():
        fail(f"dev instance not found at {DEV_INSTANCE}")
        say("run ./run.sh setup jros-dev to create it", prefix="launch")
        return 1
    # Toolkit routing: Swift native app (default) vs the PySide6 shell.
    if _ui_toolkit() == "swift":
        rc = _boot_swift(env, dev=dev)
        if rc is not None:
            return rc
        warn("Swift app unavailable — falling back to the PySide6 shell")
    say("launching the windowed app — menu-bar tray + chat window "
        "(the model loads on boot)…", prefix="launch")
    sys.stdout.flush()
    os.execvpe(
        str(VENV_PY),
        [str(VENV_PY), "-m", "jaeger_ai.core.windowed"],
        env,
    )
    fail("could not exec the windowed app")
    return 1


SWIFT_DIR = REPO / "jaeger_ai" / "interfaces" / "swift"


def _ui_toolkit() -> str:
    """Read interaction.ui from the dev instance config (default 'swift')."""
    try:
        from jaeger_ai.core.instance.instance import InstanceLayout
        from jaeger_ai.core.instance.schemas import Config, load_yaml
        cfg = load_yaml(InstanceLayout(root=DEV_INSTANCE).config_path, Config)
        return cfg.interaction.ui
    except Exception:  # noqa: BLE001
        return "swift"


def _boot_swift(env: dict[str, str], dev: bool = False) -> int | None:
    """Run the native Swift app. Returns an exit code once it finishes, or
    None to signal 'unavailable → fall back to PySide6'.

    Packaged-app-first (Phase 2): a bare ``./launch`` RUNS the existing
    JaegerOS-dev.app (the dev shell — pinned to the jros-dev instance via
    its Info.plist LSEnvironment) and only builds when nothing is built
    yet; ``./launch --dev`` forces a rebuild. The PRODUCT app
    (JaegerOS.app, default instance) builds via
    ``Scripts/build-app.sh --release`` and never routes through here.

    The dev app self-locates the repo's ``jaeger`` launcher by walking up
    from its own bundle path, so no PATH injection is needed."""
    if not (SWIFT_DIR / "Package.swift").exists():
        return None
    bundle = SWIFT_DIR / ".build" / "JaegerOS-dev.app"
    bundle_bin = bundle / "Contents" / "MacOS" / "JaegerOS"
    # Rebuild when forced, missing, OR stale (build-commit stamp older than
    # the Swift tree) — the stale case is what keeps a station that pulls by
    # hand from launching an app that lags the core it talks to.
    from jaeger_ai.cli._common import swift_app_is_stale
    if dev or swift_app_is_stale(REPO, bundle):
        if not shutil.which("swift"):
            if not bundle_bin.exists():
                return None
            warn("swift toolchain missing — launching the existing (stale) app")
        else:
            say("building JaegerOS-dev.app (Scripts/build-app.sh --dev)…",
                prefix="launch")
            build = subprocess.run(
                [str(SWIFT_DIR / "Scripts" / "build-app.sh"), "--dev"],
                cwd=str(SWIFT_DIR))
            if build.returncode != 0:
                warn("swift app build failed")
                return None
    if not bundle_bin.exists():
        return None
    say("launching JaegerOS-dev — menu-bar tray + chat window…", prefix="launch")
    sys.stdout.flush()
    return subprocess.run([str(bundle_bin)], env=env).returncode


# ─── main ─────────────────────────────────────────────────────────────

def cmd_update() -> int:
    """`jaeger update` — the dev update loop, one command:
    git pull, reinstall deps if they changed, rebuild the dev app if the
    Swift tree changed, then a doctor hint. Safe on a dirty tree (ff-only)."""
    import hashlib
    req = REPO / "requirements.txt"
    before = hashlib.sha1(req.read_bytes()).hexdigest() if req.exists() else ""
    say("git pull --ff-only…", prefix="update")
    pull = subprocess.run(["git", "-C", str(REPO), "pull", "--ff-only"],
                          capture_output=True, text=True)
    print(pull.stdout.strip() or pull.stderr.strip())
    if pull.returncode != 0:
        fail("pull failed (no upstream, diverged, or offline) — resolve and rerun")
        return 1
    changed = subprocess.run(
        ["git", "-C", str(REPO), "diff", "--name-only", "HEAD@{1}", "HEAD"],
        capture_output=True, text=True).stdout.splitlines() \
        if "Already up to date" not in pull.stdout else []
    after = hashlib.sha1(req.read_bytes()).hexdigest() if req.exists() else ""
    if before != after or any(f in ("pyproject.toml",) for f in changed):
        say("dependencies changed — reinstalling…", prefix="update")
        subprocess.run([str(VENV_PY), "-m", "pip", "install", "-q",
                        "-r", str(req), "-e", str(REPO)], cwd=str(REPO))
        ok("deps reinstalled")
    # Staleness beats "what did THIS pull change": the bundle's build-commit
    # stamp catches pulls done by hand outside this command and rebuilds that
    # failed last time — a diff-keyed check misses both.
    from jaeger_ai.cli._common import swift_app_is_stale
    if swift_app_is_stale(REPO, SWIFT_DIR / ".build" / "JaegerOS-dev.app"):
        say("Swift app lags the tree — rebuilding JaegerOS-dev.app…",
            prefix="update")
        subprocess.run([str(REPO / "jaeger_ai/interfaces/swift/Scripts/build-app.sh"),
                        "--dev"])
    ok("up to date — run `jaeger dev --health` to verify")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--stop", action="store_true",
                        help="stop a lingering TUI singleton")
    parser.add_argument("--restart", action="store_true",
                        help="stop, then boot")
    parser.add_argument("--status", action="store_true",
                        help="print what's running and exit")
    parser.add_argument("--no-voice", action="store_true",
                        help="tell the TUI to skip voice startup")
    parser.add_argument("--tui", action="store_true",
                        help="boot the CLI/TUI in-process agent (Pattern 0). "
                             "A bare ./launch boots the windowed JROS app.")
    parser.add_argument("--update", action="store_true",
                        help="git pull + reinstall deps + rebuild the dev app as needed")
    parser.add_argument("--dev", action="store_true",
                        help="rebuild the Swift app before launching it "
                             "(a bare ./launch runs the existing build)")
    # Housekeeping
    parser.add_argument("--reset-audio", action="store_true",
                        help="sudo killall coreaudiod — unwedge CoreAudio")
    parser.add_argument("--clean-logs", action="store_true",
                        help="truncate <instance>/run/jaeger.log to 0")
    parser.add_argument("--health", action="store_true",
                        help="preflight checks and exit")
    parser.add_argument("--tts-test", action="store_true",
                        help="run the 0.4 Track B.1 TTS node integration "
                             "gate (loads real Kokoro + speaks a test "
                             "phrase through the bus) and exit")
    parser.add_argument("--tts-boot-test", action="store_true",
                        help="boot-only TTS node check — loads Kokoro, "
                             "verifies node lifecycle, no audio output. "
                             "Safe for headless/CI runs.")
    parser.add_argument("--mode",
                        choices=["monolithic", "multiprocess"],
                        default="monolithic",
                        help="node transport mode for the TUI boot "
                             "(0.4; monolithic = all nodes inproc, "
                             "current behaviour; multiprocess = each "
                             "node its own subprocess via ZMQ — needs "
                             "Track A.7 broker + Track B node split)")
    args = parser.parse_args()

    if not DEV_INSTANCE.exists():
        fail(f"dev instance not found at {DEV_INSTANCE}")
        say("run ./run.sh setup jros-dev to create it", prefix="launch")
        return 1

    env = dev_env()

    if args.reset_audio:
        return reset_audio()
    if args.clean_logs:
        return clean_logs()
    if args.health:
        return health(env)
    if args.status:
        return cmd_status(env)
    if args.stop:
        return cmd_stop(env)
    if args.update:
        return cmd_update()
    if args.tts_test or args.tts_boot_test:
        # 0.4 Track B.1 TTS node integration gate.  --tts-test speaks
        # audibly through the speakers (operator audio gate);
        # --tts-boot-test loads Kokoro + checks node lifecycle without
        # audio output (safe for headless / autonomous runs).
        import subprocess as _sp
        tts_test_path = _REPO_ROOT / "dev" / "scripts" / "tts_node_test.py"
        cmd = [_sys.executable, str(tts_test_path)]
        if args.tts_boot_test:
            cmd.append("--boot-only")
        return _sp.call(cmd, env=env)
    if args.mode == "multiprocess":
        # Track A.7 + Track B work — the node-splitting + broker
        # pieces aren't in place yet.  Fail loudly so the operator
        # knows they need to wait, rather than silently falling back.
        print("[launch] --mode multiprocess not yet operational",
              file=_sys.stderr)
        print("[launch] needs: Track A.7 (broker) + Track B (audio_io "
              "node split)", file=_sys.stderr)
        print("[launch] try ./launch (default monolithic) instead",
              file=_sys.stderr)
        return 2
    # Default path: in-process TUI exactly as 0.3.0 shipped.  All
    # 0.4 transport + node infrastructure is loaded but dormant —
    # the brain still calls Kokoro/Whisper in-process; Track B
    # is what wires the audio_io node onto the Bus.
    env["JAEGER_NODE_MODE"] = args.mode  # "monolithic" for now
    # ── Surface routing (CLI/TUI vs windowed app) ──────────────────
    # ``--tui`` boots the CLI/TUI in-process agent (Pattern 0);
    # ``--restart`` and ``--no-voice`` are TUI modifiers so they imply it
    # too. A bare ``./launch`` boots the windowed app (Pattern 1: PySide6
    # menu-bar tray + chat window), which runs through the chassis
    # JaegerApp with a Tier-1 [core] (jaeger.windowed.toml).
    if args.tui or args.restart or args.no_voice:
        if args.restart:
            cmd_stop(env)
        return cmd_boot(env, no_voice=args.no_voice)
    # Bare ./launch → the windowed app (PySide6 menu-bar tray + chat
    # window). The agent boots inside that process.
    return cmd_boot_windowed(env, dev=args.dev)


if __name__ == "__main__":
    raise SystemExit(main())
