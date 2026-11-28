"""CLI entrypoint: ``python -m jaeger_ai`` dispatches to the JaegerAI Operator CLI."""

from __future__ import annotations

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
