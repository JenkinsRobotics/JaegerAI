"""Entry point: ``python -m jaeger_os.interfaces.tui``.

Light wrapper around :func:`jaeger_os.interfaces.tui.app.run`. Honors
two CLI flags:

  ``--banner-only`` — prints the banner + boot panel and exits.
                      Useful for sanity-checking the render in CI or
                      a dry-run; never loads Gemma.
  ``--instance NAME`` — pick the instance to launch. Resolves through
                      ``resolve_instance_dir`` (honours JAEGER_HOME).
                      Was a placeholder pre-0.2.6; now wired through.

J5B (2026-06-14) — the chassis boots HERE rather than in launch.py
because launch.py ``os.execvpe``s into this module, replacing its
process image (so any chassis state launch.py set up would be
discarded). Booting in this process gives the chassis ownership of
the slot file + atexit teardown for the lifetime that actually
matters: while the TUI is running.
"""

from __future__ import annotations

import argparse
import pathlib
import sys

from .app import JaegerTUI, run


_REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]


def _boot_chassis() -> int:
    """Take the chassis single-instance slot + register atexit
    teardown. The manifest (jaeger.toml) sets ``event_loop = "none"``
    and disables every [[node]] / [[surface]] so JaegerApp.boot
    returns immediately after the slot + supervisor watchdog + signal
    handlers are wired — JROS keeps owning the TUI loop. Returns 0
    on success, non-zero if another JROS is already running.
    """
    from jaeger_os.app import JaegerApp
    from jaeger_os.app.app import SecondInstanceError
    try:
        JaegerApp(_REPO_ROOT).boot()
    except SecondInstanceError as exc:
        print(f"jaeger-os: {exc}", file=sys.stderr)
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--banner-only", action="store_true",
        help="Render banner + boot panel and exit (no model load).",
    )
    p.add_argument(
        "--instance", type=str, default=None,
        help=(
            "Instance name to launch. Resolves to "
            "<install_root>/.jaeger_os/instances/<name>/. When omitted, "
            "falls back to JAEGER_INSTANCE_NAME env var, then the "
            "sticky-default file, then the literal 'default'."
        ),
    )
    args = p.parse_args(argv)

    if args.banner_only:
        # 0.2.6: thread --instance through so the banner reflects the
        # right path even in banner-only previews. Banner-only never
        # boots the chassis — it's a dry-run that should leave no
        # slot file / no atexit handler.
        from pathlib import Path
        from jaeger_os.core.instance.instance import (
            default_instance_name, resolve_instance_dir,
        )
        name = args.instance or default_instance_name()
        instance_dir = Path(resolve_instance_dir(name))
        tui = JaegerTUI(skip_model=True, instance_dir=instance_dir)
        tui.render_boot()
        return 0

    # Boot the chassis FIRST — slot acquisition is the part that has
    # to refuse a second launch loudly. If the slot is taken, exit
    # before the TUI starts paying its real boot cost (model load,
    # warm jobs, etc.).
    rc = _boot_chassis()
    if rc:
        return rc

    return run(instance_name=args.instance)


def _exit(rc: int) -> "int":
    """The F1 exit mitigation (STATUS.md, main.py ``main()``): when the
    in-process ggml/Metal runtime was loaded, a normal interpreter exit
    runs C++ static destructors that abort in ``ggml_metal_device_free``
    — SIGABRT + a crash report on every quit. ``jaeger dev --tui`` execs
    straight into this module, so the guard in ``jaeger_os.main.main()``
    never runs on that path (the operator's log: abort right after
    "shutdown complete"). All orderly cleanup has already happened here;
    flush and skip the doomed destructors."""
    import os
    if "llama_cpp" in sys.modules or "_pywhispercpp" in sys.modules:
        try:
            sys.stdout.flush()
            sys.stderr.flush()
        except Exception:  # noqa: BLE001 — never let a flush block the exit
            pass
        os._exit(rc)
    return rc


if __name__ == "__main__":
    sys.exit(_exit(main()))
