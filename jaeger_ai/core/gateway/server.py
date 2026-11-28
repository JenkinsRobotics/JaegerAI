"""LaunchAgent-compatible entrypoint: ``python -m jaeger_ai.core.gateway.server``."""

from __future__ import annotations

import asyncio

from jaeger_gateway import ModularGatewayRuntime, create_gateway_app, serve_modular_gateway


def main() -> int:
    asyncio.run(serve_modular_gateway())
    return 0


__all__ = ["ModularGatewayRuntime", "create_gateway_app", "main", "serve_modular_gateway"]

if __name__ == "__main__":
    raise SystemExit(main())
