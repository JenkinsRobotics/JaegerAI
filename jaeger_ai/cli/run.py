"""Entry point invoked by ``./run.sh`` (the 0.2.3 launcher).

The real agent code lives in :mod:`jaeger_os.main` and stays there —
tests, benchmarks, and out-of-tree integrations have been importing
``jaeger_os.main`` since 0.1.x, and that import surface is preserved.

This module exists so the visible "this is what you run" file matches
the rest of the install-shape vocabulary introduced in 0.2.3:

    ./install.sh     ← installer
    ./run.sh         ← launcher
    run.py           ← what run.sh invokes

``run.sh`` execs ``python src/jaeger_os/run.py "$@"``. We delegate to
``jaeger_os.main:main()`` and forward its exit code, so the
command-line surface is identical to running ``python -m
jaeger_os.main`` in the old pip-install model.
"""

from __future__ import annotations

import sys

from jaeger_ai.main import main as _main


if __name__ == "__main__":
    raise SystemExit(_main())
else:
    # Importing ``jaeger_os.cli.run`` (rather than executing it as a script)
    # exposes the same name ``main`` callers may have expected from the
    # old module. Re-export is one line — keeps the surface tidy.
    main = _main  # noqa: F401
