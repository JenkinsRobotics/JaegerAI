"""``jaeger gateway {install,start,stop,status}``."""

from __future__ import annotations

import argparse
import sys
from typing import Any

from .config import ensure_config
from .constants import (
    A2A_BACKEND_PORT,
    A2A_GATEWAY_PORT,
    MCP_GATEWAY_PORT,
    MCP_HTTP_PORT,
    VERSION,
    config_path,
    token_path,
)
from .install import InstallError, install_binary
from .service import GatewayError, start as start_gateway, status as gateway_status, stop as stop_gateway


def _print_status(row: dict[str, Any]) -> None:
    running = "running" if row.get("running") else "stopped"
    print(f"agentgateway {row.get('version')}: {running}")
    if row.get("pid"):
        print(f"  pid     {row['pid']}")
    print(f"  binary  {row.get('binary') or '(not installed)'}")
    print(f"  config  {row.get('config') or '(missing)'}")
    print(f"  token   {row.get('token_file')} (contents never printed)")
    ports = row.get("ports") or {}
    print(
        f"  ports   MCP {ports.get('mcp_gateway')} -> 127.0.0.1:{ports.get('mcp_http')}/mcp; "
        f"A2A {ports.get('a2a_gateway')} -> 127.0.0.1:{ports.get('a2a_backend')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="jaeger gateway",
        description=(
            "Install and run the public Agentgateway binary as a Jaeger-owned "
            f"loopback proxy (MCP :{MCP_GATEWAY_PORT}, A2A :{A2A_GATEWAY_PORT}). "
            "Targets Jaeger MCP HTTP and the Jaeger A2A backend — not ARES."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("install", help=f"download Agentgateway {VERSION} into ~/.jaeger/bin")
    sub.add_parser("start", help="write config if needed and start the binary")
    sub.add_parser("stop", help="stop the Jaeger-owned Agentgateway process")
    sub.add_parser("status", help="show binary, config, pid, and ports")
    args = parser.parse_args(argv)

    try:
        if args.command == "install":
            path = install_binary()
            ensure_config()
            print(f"Installed Agentgateway {VERSION} at {path}")
            print(f"Config: {config_path()}")
            print(f"Token file: {token_path()} (not printed)")
            return 0
        if args.command == "start":
            row = start_gateway()
            state = "already running" if row.get("already_running") else "started"
            print(f"Agentgateway {state} (pid {row['pid']})")
            print(f"Config: {row['config']}")
            print(
                f"Bring up backends separately: `jaeger mcp --http` (:{MCP_HTTP_PORT}) "
                f"and `jaeger a2a` (:{A2A_BACKEND_PORT})"
            )
            return 0
        if args.command == "stop":
            row = stop_gateway()
            if row.get("stopped"):
                print(f"Stopped Agentgateway (pid {row.get('pid')})")
            else:
                print("Agentgateway was not running")
            return 0
        _print_status(gateway_status())
        return 0
    except (GatewayError, InstallError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
