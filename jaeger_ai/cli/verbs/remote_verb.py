"""``jaeger remote`` — private phone access to the resident Jaeger."""

from __future__ import annotations

import json
import sys
from collections.abc import Sequence

from jaeger_ai.cli import _common as c

_USAGE = (
    "usage: jaeger remote {enable|disable|status|doctor|pair}\n"
    "\n"
    "  enable   inspect Tailscale, require WebUI auth, publish WebUI over HTTPS\n"
    "  disable  turn remote access off and remove Tailscale Serve for WebUI\n"
    "  status   compact remote health\n"
    "  doctor   live checks (not config-file existence)\n"
    "  pair     print a one-time iPhone pairing URL\n"
    "\n"
    "The phone is a remote interface to the same resident Jaeger.\n"
    "Gateway stays on loopback. Do not use Tailscale Funnel.\n"
)


def _cmd_remote_argv(argv: Sequence[str]) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        print(_USAGE, file=sys.stderr)
        return 0 if argv else 2
    action = argv[0]
    rest = list(argv[1:])
    json_out = "--json" in rest
    dry = "--dry-run" in rest or "--no-serve" in rest
    no_restart = "--no-restart" in rest
    if action == "enable":
        return _enable(json_out=json_out, serve=not dry, start_webui=not no_restart)
    if action == "disable":
        return _disable(json_out=json_out)
    if action == "status":
        return _status(json_out=json_out)
    if action == "doctor":
        return _doctor(json_out=json_out)
    if action == "pair":
        return _pair(json_out=json_out)
    print(f"[jaeger remote] unknown action {action!r}", file=sys.stderr)
    print(_USAGE, file=sys.stderr)
    return 2


def _enable(*, json_out: bool, serve: bool, start_webui: bool) -> int:
    from jaeger_ai.features.remote_access.service import ascii_qr, enable

    res = enable(serve=serve, start_webui=start_webui)
    if json_out:
        printable = dict(res)
        if printable.get("password"):
            printable["password"] = "<redacted>"
        print(json.dumps(printable, indent=2, default=str))
        return 0 if res.get("ok") else 1
    if not res.get("ok"):
        print(c.red(f"✗ {res.get('error') or res}"), file=sys.stderr)
        if res.get("needs_human"):
            print("Stop here, complete that Tailscale step, then re-run `jaeger remote enable`.")
        return 1
    print(c.green("Remote access is ready."))
    print(f"  Phone URL:  {res.get('origin')}")
    print(f"  Pair URL:   {res.get('pair_url')}")
    print(f"  Expires:    {res.get('pair_expires_in_s')}s (single use)")
    if res.get("password_generated") and res.get("password"):
        print("  Recovery password (shown once, not logged):")
        print(f"    {res.get('password')}")
    print(f"  Trust:      {res.get('trust_boundary')}")
    qr = ascii_qr(str(res.get("pair_url") or res.get("origin") or ""))
    if qr:
        print()
        print(qr)
    print("Scan the pairing URL on the iPhone, authenticate, optionally register a passkey,")
    print("then Add to Home Screen.")
    return 0


def _disable(*, json_out: bool) -> int:
    from jaeger_ai.features.remote_access.service import disable

    res = disable()
    if json_out:
        print(json.dumps(res, indent=2, default=str))
        return 0
    print(c.green("Remote access disabled."))
    return 0


def _status(*, json_out: bool) -> int:
    from jaeger_ai.features.remote_access.service import status_report

    report = status_report()
    if json_out:
        print(json.dumps(report, indent=2, default=str))
        return 0
    print(f"Remote access      {report['remote_access']}")
    print(f"Network            {report['network']}")
    print(f"HTTPS              {report['https']}")
    print(f"Authentication     {report['authentication']}")
    print(f"WebUI              {report['webui']}")
    print(f"Gateway            {report['gateway']}")
    print(f"Entity             {report['entity'] or 'unknown'}")
    print(f"Phone sessions     {report['phone_sessions']}")
    print(f"Public exposure    {report['public_exposure']}")
    if report.get("origin"):
        print(f"Phone URL          {report['origin']}")
    return 0 if report["remote_access"] == "ENABLED" else 1


def _doctor(*, json_out: bool) -> int:
    from jaeger_ai.features.remote_access.service import doctor

    doc = doctor()
    if json_out:
        print(json.dumps(doc, indent=2, default=str))
        return 0 if doc.get("ok") else 1
    checks = doc.get("checks") or {}
    for key, ok in checks.items():
        mark = c.green("PASS") if ok else c.red("FAIL")
        print(f"  {mark}  {key}")
    print(f"Origin: {doc.get('origin')}")
    print(doc.get("trust_boundary") or "")
    return 0 if doc.get("ok") else 1


def _pair(*, json_out: bool) -> int:
    from jaeger_ai.features.remote_access.service import ascii_qr, issue_pairing_token

    pair = issue_pairing_token()
    if json_out:
        print(json.dumps(pair, indent=2))
        return 0
    print(f"Pair URL: {pair['url']}")
    print(f"Expires in {pair['expires_in_s']}s. Single use.")
    qr = ascii_qr(pair["url"])
    if qr:
        print()
        print(qr)
    return 0
