"""Jaeger-owned Agentgateway (MCP 8811 + A2A 8812).

Jaeger installs and runs the public ``agentgateway`` binary. ARES does not
own this process, this config, or these ports.
"""

from .service import GatewayError, locate_binary, status as gateway_status

__all__ = ["GatewayError", "gateway_status", "locate_binary"]
