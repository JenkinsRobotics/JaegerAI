"""``jaeger mcp token`` — per-app MCP caller credentials for the local hub.

    jaeger mcp token issue codex claude ...   # or --all
    jaeger mcp token status
    jaeger mcp token header <app>              # for client header helpers

``issue`` creates any missing token in the caller token store (Keychain plus
the 0600 state copy) and exports a 0600 copy to
``~/.jaeger/secrets/mcp-<app>.token`` for clients that read a token file.
Token values are never printed by ``issue`` or ``status``. ``header`` writes
the Authorization header JSON to stdout for a client's headers helper (Claude
Code ``headersHelper``); it is meant to be piped into that client only.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from jaeger_ai.core.gateway.caller_auth import APP_CALLERS, ensure_tokens, read_token


def secrets_dir() -> Path:
    root = os.environ.get("JAEGER_STATE_DIR") or os.environ.get("JAEGER_STATE_HOME") or "~/.jaeger"
    return Path(root).expanduser() / "secrets"


def token_file(app: str) -> Path:
    return secrets_dir() / f"mcp-{app}.token"


def _export(app: str) -> str:
    value = read_token(app)
    if not value:
        raise SystemExit(f"token for {app!r} missing after issue")
    directory = secrets_dir()
    directory.mkdir(parents=True, exist_ok=True)
    os.chmod(directory, 0o700)
    path = token_file(app)
    tmp = path.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(value)
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)
    return str(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="jaeger mcp token")
    sub = parser.add_subparsers(dest="cmd", required=True)
    issue = sub.add_parser("issue")
    issue.add_argument("apps", nargs="*")
    issue.add_argument("--all", action="store_true")
    sub.add_parser("status")
    header = sub.add_parser("header")
    header.add_argument("app")
    args = parser.parse_args(argv)

    if args.cmd == "issue":
        apps = list(APP_CALLERS) if args.all else args.apps
        unknown = [a for a in apps if a not in APP_CALLERS]
        if not apps or unknown:
            print(f"apps must be from: {', '.join(APP_CALLERS)}", file=sys.stderr)
            return 2
        result = ensure_tokens(apps)
        for app in apps:
            print(f"{app}: {result[app]} -> {_export(app)} (0600)")
        return 0
    if args.cmd == "status":
        for app in APP_CALLERS:
            stored = bool(read_token(app))
            path = token_file(app)
            mode = oct(path.stat().st_mode & 0o777) if path.exists() else "-"
            print(f"{app}: store={'yes' if stored else 'no'} file={mode}")
        return 0
    if args.app not in APP_CALLERS:
        return 2
    value = read_token(args.app)
    if not value:
        return 1
    sys.stdout.write(json.dumps({"Authorization": f"Bearer {value}"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
