"""CLI entrypoint: ``python -m jaeger_ai`` boots the standalone modular Jaeger Gateway."""

from __future__ import annotations

import asyncio

from jaeger_gateway import serve_modular_gateway


def main() -> int:
    asyncio.run(serve_modular_gateway())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
