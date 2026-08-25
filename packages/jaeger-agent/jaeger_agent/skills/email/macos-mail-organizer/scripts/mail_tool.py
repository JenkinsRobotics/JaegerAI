#!/usr/bin/env python3
"""CLI wrapper around the Mail.app tools in jaeger_agent.tools.email.

Prefer the registered tools from an agent turn. This script is for
live verification:

    python3 mail_tool.py list
    python3 mail_tool.py get "Google" INBOX 5
    python3 mail_tool.py batch_move "Google" INBOX trash 1,2,3
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# Allow `python scripts/mail_tool.py` from a source checkout.
_PARTS = Path(__file__).resolve().parents
_PKG = _PARTS[5]  # packages/jaeger-agent
if str(_PKG) not in sys.path:
    sys.path.insert(0, str(_PKG))
if len(_PARTS) > 7:
    _REPO = str(_PARTS[7])
    if _REPO not in sys.path:
        sys.path.insert(0, _REPO)


_USAGE = """Usage: mail_tool.py <list|get|read|plan|move|batch_move|sweep|aliases> [args...]

  list
  get <account> [mailbox=INBOX] [limit=10] [offset=0]
  read <account> <mailbox> <id>[,id...]
  plan <account> [mailbox=INBOX] [offset=0]
  move <id> <account> <source> <target>
  batch_move <account> <source> <target> <id>[,id...]
  sweep [--execute] [account]
  aliases <mailbox>
"""


def _dump(payload: object) -> int:
    print(json.dumps(payload, indent=2))
    ok = True
    if isinstance(payload, dict):
        ok = payload.get("ok", payload.get("success", True)) is not False
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    # The registered tools are tier-gated for the agent loop. This CLI is
    # an operator-invoked helper — the human already opted in by running it.
    from jaeger_os.core.safety.permissions import (
        AllowAllProvider, PermissionPolicy, use_policy,
    )
    with use_policy(PermissionPolicy(confirmation=AllowAllProvider())):
        return _main(argv)


def _main(argv: list[str] | None = None) -> int:
    from jaeger_agent.tools.email import (
        alias_candidates,
        batch_move,
        list_mail,
        list_mailboxes,
        move_mail,
        plan_mail_triage,
        read_mail,
        sweep_mail,
    )

    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print(_USAGE, file=sys.stderr)
        return 1
    cmd = args[0].lower()
    if cmd == "list":
        return _dump(list_mailboxes())
    if cmd == "get":
        if len(args) < 2:
            print("Usage: mail_tool.py get <account> [mailbox] [limit] [offset]", file=sys.stderr)
            return 1
        account = args[1]
        mailbox = args[2] if len(args) > 2 else "INBOX"
        limit = int(args[3]) if len(args) > 3 else 10
        offset = int(args[4]) if len(args) > 4 else 0
        return _dump(list_mail(account, mailbox, limit, False, offset))
    if cmd == "read":
        if len(args) < 4:
            print("Usage: mail_tool.py read <account> <mailbox> <id>[,id...]", file=sys.stderr)
            return 1
        return _dump(read_mail(args[1], args[2], args[3]))
    if cmd == "plan":
        if len(args) < 2:
            print("Usage: mail_tool.py plan <account> [mailbox] [offset]", file=sys.stderr)
            return 1
        mailbox = args[2] if len(args) > 2 else "INBOX"
        offset = int(args[3]) if len(args) > 3 else 0
        return _dump(plan_mail_triage(args[1], mailbox, offset))
    if cmd == "move":
        if len(args) < 5:
            print("Usage: mail_tool.py move <id> <account> <source> <target>", file=sys.stderr)
            return 1
        return _dump(move_mail(args[1], args[2], args[3], args[4]))
    if cmd == "batch_move":
        if len(args) < 5:
            print(
                "Usage: mail_tool.py batch_move <account> <source> <target> <id>[,id...]",
                file=sys.stderr,
            )
            return 1
        return _dump(batch_move(args[1], args[2], args[3], args[4]))
    if cmd == "sweep":
        execute = "--execute" in args
        rest = [a for a in args[1:] if a != "--execute"]
        account = rest[0] if rest else None
        return _dump(sweep_mail(account=account, dry_run=not execute))
    if cmd == "aliases":
        if len(args) < 2:
            print("Usage: mail_tool.py aliases <mailbox>", file=sys.stderr)
            return 1
        print(json.dumps(alias_candidates(args[1]), indent=2))
        return 0
    print(f"Unknown command: {cmd}", file=sys.stderr)
    print(_USAGE, file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

