"""``jaeger webui ...`` — Jaeger's browser interface and private access."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence

from jaeger_ai.cli import _common as c


def _cmd_webui_argv(argv: Sequence[str]) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        print(
            "usage: jaeger webui <verb> [args...]\n"
            "\n"
            "Jaeger WebUI with optional private Tailscale publishing.\n"
            "\n"
            "verbs:\n"
            "  start [--tailscale] [-i NAME]       start Jaeger WebUI + adapter\n"
            "  stop [-i NAME]                      stop Jaeger WebUI + adapter\n"
            "  status [--json] [-i NAME]           ports and health\n"
            "  url [-i NAME]                       print browser URL\n"
            "  servers [status|start|stop|restart] [all|NAME]  local server controls\n"
            "\n"
            "ports:\n"
            "  Jaeger WebUI     Tailscale IPv4:8790      (canonical chat URL; jaeger webui url)\n"
            "  adapter          http://127.0.0.1:8791/   (runner-local)\n"
            "  webhooks         127.0.0.1:8793           (no longer clashes with adapter)\n",
            file=sys.stderr,
        )
        return 0 if argv else 2

    verb, rest = argv[0], list(argv[1:])
    if verb == "servers":
        from jaeger_ai.features.webui.server_controls import main
        return main(rest)
    if verb == "start":
        return _webui_start(rest)
    if verb == "stop":
        return _webui_stop(rest)
    if verb == "status":
        return _webui_status(rest)
    if verb == "url":
        return _webui_url(rest)
    print(f"[jaeger webui] unknown verb {verb!r}", file=sys.stderr)
    return 2


def _parse_instance(argv: list[str]) -> tuple[argparse.Namespace, list[str]]:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("-i", "--instance", default=None)
    args, rest = parser.parse_known_args(argv)
    return args, rest


def _webui_start(argv: list[str]) -> int:
    from jaeger_ai.features.webui import WebUIService

    base, rest = _parse_instance(argv)
    parser = argparse.ArgumentParser(prog="jaeger webui start")
    parser.add_argument("--tailscale", action="store_true")
    args = parser.parse_args(rest)
    svc = WebUIService(base.instance)
    print(f"Starting Jaeger WebUI for instance {svc.instance!r}...")
    res = svc.start(publish_tailscale=True if args.tailscale else None)
    if not res.get("ok"):
        print(c.red(f"✗ {res.get('error') or res}"), file=sys.stderr)
        return 1
    print(c.green("✓ Jaeger WebUI is up."))
    print(f"  Local:   {res['open']}")
    if args.tailscale:
        output = (res.get("tailscale") or {}).get("output")
        print(f"  Tailnet: {output or 'published through Tailscale Serve'}")
    return 0


def _webui_stop(argv: list[str]) -> int:
    from jaeger_ai.features.webui import WebUIService

    base, rest = _parse_instance(argv)
    argparse.ArgumentParser(prog="jaeger webui stop").parse_args(rest)
    svc = WebUIService(base.instance)
    res = svc.stop()
    if not res.get("ok"):
        print(c.red(f"✗ stop failed: {res}"), file=sys.stderr)
        return 1
    print(c.green("✓ Jaeger WebUI stack stopped."))
    return 0


def _webui_status(argv: list[str]) -> int:
    from jaeger_ai.features.webui import WebUIService

    base, rest = _parse_instance(argv)
    parser = argparse.ArgumentParser(prog="jaeger webui status")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(rest)
    svc = WebUIService(base.instance)
    status = svc.status()
    if args.json:
        print(json.dumps(status, indent=2, default=str))
        return 0
    print(f"Instance:            {status['instance']}")
    ad = status["adapter"]
    ad_s = c.green("running") if ad.get("running") else c.dim("stopped")
    print(f"Adapter:             {ad_s}  pid={ad.get('pid')}")
    print(f"  URL:               {ad['url']}")
    print(f"  Health:            {ad['health']}")
    vd = status["webui"]
    vd_s = c.green("running") if vd.get("running") else c.dim("stopped")
    print(f"Jaeger WebUI:         {vd_s}  pid={vd.get('pid')}")
    print(f"  Chat URL:          {status.get('chat_url') or vd['url']}")
    print(f"  Loopback:          {vd['url']}")
    print(f"  Health:            {vd['health']}")
    identity = (vd.get("health") or {}).get("identity") or {}
    if identity:
        ident_s = c.green("ok") if identity.get("ok") else c.red("mismatch")
        print(
            f"  Identity:          {ident_s}  "
            f"bundle={identity.get('bundle_version') or '?'}  "
            f"settings={identity.get('webui_version') or '?'}"
        )
        if identity.get("error"):
            print(f"  Identity error:    {identity['error']}")
    ports = status["ports"]
    print(
        "Ports:               "
        f"adapter={ports['adapter']}  "
        f"webui={ports['webui']}  "
        f"webhooks={ports['webhooks']}"
    )
    return 0


def _webui_url(argv: list[str]) -> int:
    from jaeger_ai.features.webui import WebUIService

    base, _rest = _parse_instance(argv)
    svc = WebUIService(base.instance)
    print(svc.browser_url())
    return 0
