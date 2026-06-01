"""Package entry point — lets you run jaeger as `python -m jaeger_os`.

Equivalent to `python -m jaeger_os.main`. Delegates to `main.main()`
which routes to either CLI chat (default) or the voice loop daemon
(when `--voice` is passed). See `python -m jaeger_os --help` and
`python -m jaeger_os --voice --help`.
"""

from __future__ import annotations

from .main import main


if __name__ == "__main__":
    raise SystemExit(main())
