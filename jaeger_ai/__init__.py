"""JaegerAI — Thin product composition root wired 100% onto standalone modular jaeger-* packages."""

from __future__ import annotations

from jaeger_gateway import ModularGatewayRuntime, serve_modular_gateway

__version__ = "1.0.0"
__all__ = ["ModularGatewayRuntime", "serve_modular_gateway", "__version__"]
