"""``jaeger webui ...`` — Hermes WebUI temporary browser UI surface.

Uses the existing settings catalog toggle ``containers.use_hermes_webui``
(plugin-style enablement) plus the Apple container + hermes-webui-adapter.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Sequence

from jaeger_ai.cli import _common as c


def _cmd_webui_argv(argv: Sequence[str]) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        print(
            "usage: jaeger webui <verb> [args...]\n"
            "\n"
            "Hermes WebUI as Jaeger's temporary browser UI.\n"
            "Enable:  jaeger settings set containers.use_hermes_webui true\n"
            "\n"
            "verbs:\n"
            "  start [--force] [--instance NAME]   start container + adapter\n"
            "  stop  [--keep-container] [-i NAME]  stop adapter (+ container)\n"
            "  status [--json] [-i NAME]           toggle, ports, health\n"
            "  url [-i NAME]                       print browser URL\n"
            "\n"
            "ports:\n"
            "  container UI  http://127.0.0.1:8787/   (Apple container)\n"
            "  adapter       http://127.0.0.1:8791/   (runner-local)\n"
            "  vendor UI     http://127.0.0.1:8790/   (scripts/run-jaeger-webui.sh)\n"
            "  webhooks      127.0.0.1:8793           (no longer clashes with adapter)\n",
            file=sys.stderr,
        )
        return 0 if argv else 2

    verb, rest = argv[0], list(argv[1:])
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
    from jaeger_ai.features.hermes_webui import HermesWebUIService

    base, rest = _parse_instance(argv)
    parser = argparse.ArgumentParser(prog="jaeger webui start")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(rest)
    svc = HermesWebUIService(base.instance)
    print(
        f"Starting Hermes WebUI for instance {svc.instance!r} "
        f"(toggle={'on' if svc.enabled else 'off'})..."
    )
    res = svc.start(force=args.force)
    if not res.get("ok"):
        print(c.red(f"✗ {res.get('error') or res}"), file=sys.stderr)
        if res.get("container") and not res["container"].get("ok"):
            print(c.red(f"  container: {res['container'].get('error')}"), file=sys.stderr)
        if res.get("adapter") and not res["adapter"].get("ok"):
            print(c.red(f"  adapter: {res['adapter'].get('error')}"), file=sys.stderr)
        return 1
    urls = svc.urls()
    print(c.green("✓ Hermes WebUI stack is up."))
    print(f"  Open:    {urls.container_ui}")
    print(f"  Adapter: {urls.adapter}")
    print(f"  Vendor:  {urls.vendor_ui}  (optional: ./scripts/run-jaeger-webui.sh)")
    return 0


def _webui_stop(argv: list[str]) -> int:
    from jaeger_ai.features.hermes_webui import HermesWebUIService

    base, rest = _parse_instance(argv)
    parser = argparse.ArgumentParser(prog="jaeger webui stop")
    parser.add_argument("--keep-container", action="store_true")
    args = parser.parse_args(rest)
    svc = HermesWebUIService(base.instance)
    res = svc.stop(stop_container=not args.keep_container)
    if not res.get("ok"):
        print(c.red(f"✗ stop failed: {res}"), file=sys.stderr)
        return 1
    print(c.green("✓ Hermes WebUI stack stopped."))
    return 0


def _webui_status(argv: list[str]) -> int:
    from jaeger_ai.features.hermes_webui import HermesWebUIService

    base, rest = _parse_instance(argv)
    parser = argparse.ArgumentParser(prog="jaeger webui status")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(rest)
    svc = HermesWebUIService(base.instance)
    status = svc.status()
    if args.json:
        print(json.dumps(status, indent=2, default=str))
        return 0
    enabled = c.green("on") if status["enabled"] else c.dim("off")
    print(f"Hermes WebUI toggle: {enabled}  (containers.use_hermes_webui)")
    print(f"Instance:            {status['instance']}")
    ctn = status["container"]
    state = ctn.get("state")
    state_s = c.green(state) if state == "running" else c.dim(str(state))
    print(f"Container:           {ctn['id']}  [{state_s}]")
    print(f"  URL:               {ctn['url']}")
    print(f"  Health:            {ctn['health']}")
    ad = status["adapter"]
    ad_s = c.green("running") if ad.get("running") else c.dim("stopped")
    print(f"Adapter:             {ad_s}  pid={ad.get('pid')}")
    print(f"  URL:               {ad['url']}")
    print(f"  Health:            {ad['health']}")
    ports = status["ports"]
    print(
        "Ports:               "
        f"container={ports['container_webui']}  "
        f"adapter={ports['adapter']}  "
        f"vendor={ports['vendor_webui']}  "
        f"webhooks={ports['webhooks']}"
    )
    return 0


def _webui_url(argv: list[str]) -> int:
    from jaeger_ai.features.hermes_webui import HermesWebUIService

    base, _rest = _parse_instance(argv)
    svc = HermesWebUIService(base.instance)
    print(svc.urls().container_ui)
    return 0
