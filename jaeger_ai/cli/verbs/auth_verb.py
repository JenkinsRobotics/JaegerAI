"""``jaeger auth`` — per-caller Gateway tokens (macOS Keychain).

``init`` creates any missing caller token; ``status`` lists which callers have
one. Token values are never printed, logged, or written to config files.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Sequence

_USAGE = (
    "usage: jaeger auth {init|status} [--json]\n"
    "\n"
    "  init    create any missing per-caller Gateway token in the Keychain\n"
    "          (service ai.jaeger.gateway.caller; existing tokens are kept)\n"
    "  status  list callers, their scopes and whether a token exists\n"
    "\n"
    "Values are never printed. Each client (menu bar, CLI, WebUI, IDE, bridge,\n"
    "jaegerd, MCP, A2A) reads only its own token.\n"
)


def _status_rows() -> list[dict]:
    from jaeger_ai.core.gateway.caller_auth import CALLERS, TokenStoreError, read_token

    rows = []
    for name, spec in CALLERS.items():
        try:
            present: bool | None = bool(read_token(name))
            error = ""
        except TokenStoreError as exc:
            present, error = None, str(exc)
        rows.append({"caller": name, "actor": spec.actor, "scopes": sorted(spec.scopes),
                     "session_prefix": spec.session_prefix, "token": present, "error": error})
    return rows


def _store_label() -> str:
    from jaeger_ai.core.gateway.caller_auth import KEYCHAIN_SERVICE, _token_dir

    directory = _token_dir()
    return f"files in {directory} (0600)" if directory else f"macOS Keychain service {KEYCHAIN_SERVICE}"


def _cmd_auth_argv(argv: Sequence[str]) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        print(_USAGE, file=sys.stderr)
        return 0 if argv else 2
    action, rest = argv[0], list(argv[1:])
    json_out = "--json" in rest
    from jaeger_ai.core.gateway.caller_auth import TokenStoreError, ensure_tokens

    if action == "init":
        try:
            result = ensure_tokens()
        except TokenStoreError as exc:
            print(f"[jaeger auth] could not store caller tokens: {exc}", file=sys.stderr)
            return 1
        if json_out:
            print(json.dumps({"store": _store_label(), "callers": result}, indent=2))
        else:
            print(f"Caller tokens ({_store_label()}):")
            for name, state in result.items():
                print(f"  {name:<8} {state}")
            print("Restart running Jaeger services so every client picks up its token.")
        return 0
    if action == "status":
        rows = _status_rows()
        if json_out:
            print(json.dumps({"store": _store_label(), "callers": rows}, indent=2))
        else:
            print(f"Caller tokens ({_store_label()}):")
            for row in rows:
                state = {True: "present", False: "MISSING", None: "ERROR"}[row["token"]]
                prefix = f" sessions {row['session_prefix']}*" if row["session_prefix"] else ""
                print(f"  {row['caller']:<8} {state:<8} {row['actor']:<14} "
                      f"{','.join(row['scopes'])}{prefix}" + (f"  ({row['error']})" if row["error"] else ""))
        return 0 if all(row["token"] for row in rows) else 1
    print(_USAGE, file=sys.stderr)
    return 2
