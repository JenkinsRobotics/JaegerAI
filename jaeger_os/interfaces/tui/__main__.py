"""Entry point: ``python -m jaeger_os.interfaces.tui``.

Light wrapper around :func:`jaeger_os.interfaces.tui.app.run`. Honors
two CLI flags:

  ``--banner-only`` — prints the banner + boot panel and exits.
                      Useful for sanity-checking the render in CI or
                      a dry-run; never loads Gemma.
  ``--instance NAME`` — pick the instance to launch. Resolves through
                      ``resolve_instance_dir`` (honours JAEGER_HOME).
                      Was a placeholder pre-0.2.6; now wired through.
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
        # right path even in banner-only previews.
        from pathlib import Path
        from jaeger_os.core.instance.instance import (
            default_instance_name, resolve_instance_dir,
        )
        name = args.instance or default_instance_name()
        instance_dir = Path(resolve_instance_dir(name))
        tui = JaegerTUI(skip_model=True, instance_dir=instance_dir)
        tui.render_boot()
        return 0

    return run(instance_name=args.instance)


if __name__ == "__main__":
    sys.exit(main())
