"""Explicit operator entry point; no implicit startup or credential provisioning."""

import argparse
import asyncio
import json
from pathlib import Path

from .server import run


def main():
    parser = argparse.ArgumentParser(description="Isolated ARES MCP Events facade")
    parser.add_argument("config", help="Absolute path to public configuration JSON")
    parser.add_argument(
        "--disconnect",
        action="store_true",
        help="Locally revoke the configured owner; never exposed over MCP",
    )
    args = parser.parse_args()
    path = Path(args.config)
    if not path.is_absolute():
        parser.error("Configuration path must be absolute")
    config = json.loads(path.read_text())
    if args.disconnect:
        from .security import KeychainSecrets
        from .service import Events
        from .store import Store

        # This operation has no Gateway, token consumer, listener or outbound HTTP.
        events = Events(Store(config["state_file"]), KeychainSecrets(), None)
        asyncio.run(events.disconnect(config["subject"]))
    else:
        run(config)


if __name__ == "__main__":
    main()
