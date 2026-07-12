"""Package entry point — lets you run jaeger as `python -m jaeger_ai`.

Equivalent to `python -m jaeger_ai.main`. Delegates to `main.main()`
which routes to either CLI chat (default) or the voice loop daemon
(when `--voice` is passed). See `python -m jaeger_ai --help` and
`python -m jaeger_ai --voice --help`.
"""

from __future__ import annotations

from .main import main


if __name__ == "__main__":
    raise SystemExit(main())
