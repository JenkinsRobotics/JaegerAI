"""``jaeger container ...`` — manage Apple container tools and services.

Verbs:
  jaeger container list [--all]
  jaeger container start <name>
  jaeger container stop <name>
  jaeger container delete <name> [--force]
  jaeger container status <name>
  jaeger container create <name> --image <image> [-p host:container] [-v host:container]
  jaeger container system [start|stop|status]
"""

from __future__ import annotations

import argparse
import sys
from typing import Sequence

from jaeger_ai.cli import _common as c
from jaeger_ai.core.runtime import container_service as cs


def _cmd_container_argv(argv: Sequence[str]) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        print(
            "usage: jaeger container <verb> [args...]\n"
            "\n"
            "verbs:\n"
            "  list [--all]                           list installed/running containers\n"
            "  start <name>                           start a container tool\n"
            "  stop <name>                            stop a running container\n"
            "  status <name>                          show details, state, and recent logs\n"
            "  delete <name> [--force]                delete a container tool from disk\n"
            "  create <name> --image <img...>         create a new container tool\n"
            "  system <start|stop|status>             manage the background container service\n"
            "\n"
            "examples:\n"
            "  jaeger container list\n"
            "  jaeger container start ares-openclaw\n"
            "  jaeger container status hermes-webui-hermes-webui\n",
            file=sys.stderr,
        )
        return 0 if argv else 2

    verb, rest = argv[0], argv[1:]
    if verb == "list":
        return _container_list(rest)
    if verb == "start":
        return _container_start(rest)
    if verb == "stop":
        return _container_stop(rest)
    if verb == "status":
        return _container_status(rest)
    if verb == "delete":
        return _container_delete(rest)
    if verb == "create":
        return _container_create(rest)
    if verb == "system":
        return _container_system(rest)

    print(f"[jaeger container] unknown verb {verb!r}", file=sys.stderr)
    return 2


def _container_list(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(prog="jaeger container list")
    parser.add_argument("-a", "--all", action="store_true", default=True)
    args = parser.parse_args(argv)

    containers = cs.list_containers(all=args.all)
    if not containers:
        print("No containers configured or found.")
        return 0

    print(f"{'CONTAINER ID':<28} {'STATE':<10} {'IP ADDRESS':<16} {'IMAGE'}")
    print("-" * 75)
    for row in containers:
        cid = str(row.get("id") or "")
        state = cs.normalize_state(row.get("state") or row.get("status"))
        ip = str(row.get("ip") or "")
        if not ip and isinstance(row.get("networks"), list) and row.get("networks"):
            ip = str(row["networks"][0].get("ip") or "")
        image = str(row.get("image") or "")
        if len(image) > 30:
            image = image[:27] + "…"
        state_color = c.green(state) if state == "running" else c.dim(state)
        print(f"{cid:<28} {state_color:<19} {ip:<16} {image}")
    return 0


def _container_start(argv: Sequence[str]) -> int:
    if not argv:
        print("error: container name required (e.g. `jaeger container start ares-openclaw`)", file=sys.stderr)
        return 2
    name = argv[0]
    print(f"Starting container {name!r}...")
    res = cs.start_container(name)
    if res.get("ok"):
        print(c.green(f"✓ Container {name!r} is now running."))
        return 0
    print(c.red(f"✗ Failed to start {name!r}: {res.get('error')}"), file=sys.stderr)
    return 1


def _container_stop(argv: Sequence[str]) -> int:
    if not argv:
        print("error: container name required", file=sys.stderr)
        return 2
    name = argv[0]
    print(f"Stopping container {name!r}...")
    res = cs.stop_container(name)
    if res.get("ok"):
        print(c.green(f"✓ Container {name!r} stopped."))
        return 0
    print(c.red(f"✗ Failed to stop {name!r}: {res.get('error')}"), file=sys.stderr)
    return 1


def _container_delete(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(prog="jaeger container delete")
    parser.add_argument("name")
    parser.add_argument("-f", "--force", action="store_true")
    args = parser.parse_args(argv)

    print(f"Deleting container {args.name!r}...")
    res = cs.delete_container(args.name, force=args.force)
    if res.get("ok"):
        print(c.green(f"✓ Container {args.name!r} deleted."))
        return 0
    print(c.red(f"✗ Failed to delete {args.name!r}: {res.get('error')}"), file=sys.stderr)
    return 1


def _container_status(argv: Sequence[str]) -> int:
    if not argv:
        print("error: container name required", file=sys.stderr)
        return 2
    name = argv[0]
    info = cs.container_status(name)
    if not info.get("found"):
        print(c.red(f"Container {name!r} not found."), file=sys.stderr)
        return 1

    details = info.get("details", {})
    state = cs.normalize_state(details.get("state") or details.get("status"))
    print(f"Container: {name}")
    print(f"State:     {c.green(state) if state == 'running' else state}")
    print(f"Image:     {details.get('image', 'n/a')}")
    if details.get("ip"):
        print(f"IP:        {details.get('ip')}")
    if details.get("ports"):
        print(f"Ports:     {details.get('ports')}")
    
    logs = info.get("recent_logs")
    if logs:
        print("\nRecent output (last 20 lines):")
        print("-" * 50)
        print(logs)
    return 0


def _container_create(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(prog="jaeger container create")
    parser.add_argument("name")
    parser.add_argument("--image", required=True)
    parser.add_argument("-p", "--publish", action="append", dest="ports")
    parser.add_argument("-v", "--volume", action="append", dest="volumes")
    parser.add_argument("-e", "--env", action="append", dest="envs")
    parser.add_argument("--cpus", type=int)
    parser.add_argument("--memory")
    args = parser.parse_args(argv)

    print(f"Creating container {args.name!r} from {args.image!r}...")
    res = cs.create_container(
        name=args.name,
        image=args.image,
        ports=args.ports,
        volumes=args.volumes,
        envs=args.envs,
        cpus=args.cpus,
        memory=args.memory,
    )
    if res.get("ok"):
        print(c.green(f"✓ Created container {args.name!r}."))
        return 0
    print(c.red(f"✗ Failed to create {args.name!r}: {res.get('error')}"), file=sys.stderr)
    return 1


def _container_system(argv: Sequence[str]) -> int:
    sub = argv[0] if argv else "status"
    if sub == "start":
        ok = cs.ensure_system_started()
        print(c.green("✓ Container system service started.") if ok else c.red("✗ Failed to start container service."))
        return 0 if ok else 1
    if sub == "stop":
        ok = cs.stop_system()
        print(c.green("✓ Container system service stopped.") if ok else c.red("✗ Failed to stop container service."))
        return 0 if ok else 1
    if sub == "status":
        running = cs.is_system_running()
        print(f"Container apiserver: {c.green('running') if running else c.dim('stopped')}")
        return 0
    print(f"unknown system action: {sub!r}", file=sys.stderr)
    return 2
