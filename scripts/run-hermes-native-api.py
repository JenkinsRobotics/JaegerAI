#!/usr/bin/env python3
"""Expose Hermes' own Runs API inside its existing container.

This is a lifecycle launcher, not an alternative agent loop. Hermes owns its
SessionDB, tools, inference, approval policy, and native Runs implementation.
Only the API platform is started; no messaging gateway/cron platforms are started.
Rollback is stopping this process; the existing WebUI/default profile is unchanged.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import secrets
from pathlib import Path
import signal
import stat
import sys


def provision_key(path: Path) -> None:
    """Create once, privately; never overwrite or print an existing credential."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        api_options(path, "127.0.0.1", 8645)
        return
    with os.fdopen(descriptor, "w") as output:
        output.write(secrets.token_urlsafe(48) + "\n")


def api_options(key_file: Path, host: str, port: int) -> dict:
    if not 1024 <= port <= 65535:
        raise ValueError("Native API port must be in 1024..65535")
    if host not in {"127.0.0.1", "0.0.0.0"}:
        raise ValueError("Use explicit container loopback or container ingress")
    info = key_file.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077:
        raise ValueError("Native API credential must be a private regular file (0600)")
    key = key_file.read_text().strip()
    if len(key) < 32:
        raise ValueError("Native API credential is missing or too short")
    return {"key": key, "host": host, "port": port, "cors_origins": []}


async def serve(options: dict) -> int:
    from gateway.config import PlatformConfig
    from gateway.platforms.api_server import APIServerAdapter
    from run_agent import AIAgent

    # Same narrow cloud-stop fix used by the existing WebUI-created agents.
    overlay = Path(__file__).resolve().parents[1] / "integrations/hermes_webui"
    sys.path.insert(0, str(overlay))
    from jaeger_agent_compat import install
    from jaeger_hermes_runs import resumable_adapter
    install(AIAgent)
    adapter = resumable_adapter(APIServerAdapter)(PlatformConfig(enabled=True, extra=options))
    stopped = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stopped.set)
    try:
        if not await adapter.connect():
            return 1
        print("Hermes native Runs API ready (authenticated; no model invoked)", flush=True)
        await stopped.wait()
        return 0
    finally:
        await adapter.disconnect()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--key-file", type=Path, required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8645)
    parser.add_argument("--provision-key", action="store_true", help="Create a private credential, without starting a server")
    args = parser.parse_args()
    if args.provision_key:
        provision_key(args.key_file)
        print("Hermes native API credential ready (not displayed)")
        return 0
    options = api_options(args.key_file, args.host, args.port)
    # Native runtime discovery uses the already selected Hermes home. Never
    # substitute another profile or embed credentials into command arguments.
    from dotenv import load_dotenv
    home = Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes")))
    load_dotenv(home / ".env", override=False)
    return asyncio.run(serve(options))


if __name__ == "__main__":
    raise SystemExit(main())
