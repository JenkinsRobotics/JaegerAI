"""Entry point: ``python -m jaeger_os.interfaces.tui``.

Light wrapper around :func:`jaeger_os.interfaces.tui.app.run`. Honors
two CLI flags:

  ``--banner-only`` — prints the banner + boot panel and exits.
                      Useful for sanity-checking the render in CI or
                      a dry-run; never loads Gemma.
  ``--instance NAME`` — placeholder for when the instance loader
                      wires through the TUI; currently ignored,
                      defaults to ``src/jaeger_os/instance/default/``.
"""

from __future__ import annotations

import argparse
import sys

from .app import JaegerTUI, run


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--banner-only", action="store_true",
        help="Render banner + boot panel and exit (no model load).",
    )
    p.add_argument(
        "--instance", type=str, default=None,
        help="Instance name (placeholder; currently uses src/jaeger_os/instance/default/).",
    )
    args = p.parse_args(argv)

    if args.banner_only:
        tui = JaegerTUI(skip_model=True)
        tui.render_boot()
        return 0

    return run()


if __name__ == "__main__":
    sys.exit(main())
