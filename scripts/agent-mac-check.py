#!/usr/bin/env python3
"""Bounded in-container connection check, read-only unless --write-probe.

Uses only the standard library, and never prints or forwards credentials to a
caller-selected URL. Run as the actual agent user, not container root.
"""
import argparse
import errno
import hashlib
import json
import os
from pathlib import Path
import platform
import tempfile
import time
import urllib.request

REPO = Path("/mnt/host/GitHub/JaegerAI")


def request(url, payload=None, headers=None):
    body = None if payload is None else json.dumps(payload).encode()
    with urllib.request.urlopen(urllib.request.Request(url, data=body, headers=headers or {}), timeout=5) as response:
        raw = response.read(2_000_000)
        session = response.headers.get("Mcp-Session-Id")
    if raw.lstrip().startswith(b"{"):
        return json.loads(raw), session
    for line in reversed(raw.decode().splitlines()):
        if line.startswith("data:"):
            data = json.loads(line[5:].strip())
            if "result" in data or "error" in data:
                return data, session
    raise RuntimeError("No JSON-RPC response")


def host_tools(role):
    if role == "openclaw":
        document = json.loads(Path("/home/node/.openclaw/openclaw.json").read_text())
        key = document["mcp"]["servers"]["ares-system"]["headers"]["Authorization"]
    else:
        key = ""
        for line in Path("/home/hermeswebui/.hermes/.env").read_text().splitlines():
            name, separator, value = line.partition("=")
            if separator and name.strip() == "MCP_ARES_HOST_API_KEY":
                key = "Bearer " + value.strip().strip("\"'")
                break
    if not key:
        raise RuntimeError("Existing host MCP credential is missing")
    headers = {"Authorization": key, "Host": "127.0.0.1:8813",
               "Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
    url = "http://192.168.64.1:8813/mcp"
    init, sid = request(url, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
        "protocolVersion": "2024-11-05", "capabilities": {},
        "clientInfo": {"name": "jaeger-mac-check", "version": "1"}}}, headers)
    if "error" in init:
        raise RuntimeError("Host MCP initialization rejected")
    if sid:
        headers["Mcp-Session-Id"] = sid
    inventory, _ = request(url, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, headers)
    names = [tool["name"] for tool in inventory.get("result", {}).get("tools", [])]
    match = next((name for name in names if name.endswith("host_environment")), None)
    if not match:
        raise RuntimeError("host_environment tool not present in authenticated inventory")
    result, _ = request(url, {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                              "params": {"name": match, "arguments": {}}}, headers)
    if result.get("error") or result.get("result", {}).get("isError"):
        raise RuntimeError("Host environment tool failed")
    return {"tool_names": names, "result": result["result"]}


def write_probe(root=REPO):
    """Only touches an exclusively created temporary directory; no git changes."""
    started = time.monotonic()
    directory = Path(tempfile.mkdtemp(prefix=".agent-write-probe-", dir=root))
    path = directory / "probe.txt"
    renamed = directory / "renamed.txt"
    failure = None
    stage = "create"
    try:
        with path.open("x") as handle:
            handle.write("created\n")
        stage = "edit"
        with path.open("a") as handle:
            handle.write("edited\n")
        stage = "rename"
        path.rename(renamed)
        stage = "read_after_rename"
        assert renamed.read_text() == "created\nedited\n"
        digest = hashlib.sha256(renamed.read_bytes()).hexdigest()
    except Exception as exc:
        failure = exc
        failure.probe_stage = stage
    finally:
        # Never recursively remove contents: only our two known probe files.
        # SMB may defer an unlink briefly, reporting ENOTEMPTY for an empty dir.
        try:
            path.unlink(missing_ok=True)
            renamed.unlink(missing_ok=True)
            for attempt in range(11):
                try:
                    directory.rmdir()
                    break
                except OSError as exc:
                    if exc.errno not in (errno.ENOTEMPTY, errno.EBUSY) or attempt == 10:
                        raise
                    time.sleep(.1)
        except Exception as exc:
            if failure is None:
                failure = exc
                failure.probe_stage = "cleanup"
            else:
                failure.cleanup_error = type(exc).__name__
    if failure is not None:
        raise failure
    return {"ok": True, "seconds": round(time.monotonic()-started, 4), "sha256": digest,
            "operations": ["create", "edit", "read", "rename", "remove own probe"]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--role", choices=("hermes", "openclaw"), required=True)
    parser.add_argument("--write-probe", action="store_true")
    parser.add_argument("--all-workspaces", action="store_true", help="With --write-probe, test the explicit authorized personal/NAS mounts too")
    args = parser.parse_args()
    if args.all_workspaces and not args.write_probe:
        parser.error("--all-workspaces requires explicit --write-probe")
    output = {"role": args.role, "container_os": platform.system(), "uid": os.getuid(), "checks": {}}
    checks = {
        "canonical_source": lambda: {"path": str(REPO), "sha256": hashlib.sha256((REPO / "jaeger_ai/interfaces/hermes_profile_adapters/roundtable.py").read_bytes()).hexdigest()},
        "host_mcp": lambda: host_tools(args.role),
        "jaeger": lambda: request("http://192.168.64.1:8642/health")[0],
        "roundtable": lambda: request("http://192.168.64.1:8643/health")[0],
        "a2a": lambda: {"name": request("http://192.168.64.1:8812/.well-known/agent-card.json")[0].get("name")},
    }
    if args.write_probe:
        checks["write"] = write_probe
        if args.all_workspaces:
            for root in ("/mnt/host/Desktop", "/mnt/host/Documents", "/mnt/nas/Jenkins_Robotics", "/mnt/nas/Personal-Drive"):
                checks[f"write:{root}"] = lambda root=root: write_probe(Path(root))
    for name, fn in checks.items():
        start = time.monotonic()
        try:
            output["checks"][name] = {"ok": True, "result": fn(), "seconds": round(time.monotonic()-start, 4)}
        except Exception as exc:
            output["checks"][name] = {"ok": False, "error": type(exc).__name__, "seconds": round(time.monotonic()-start, 4)}
            if isinstance(exc, OSError):
                output["checks"][name]["errno"] = exc.errno
            for attribute in ("probe_stage", "cleanup_error"):
                if hasattr(exc, attribute):
                    output["checks"][name][attribute] = getattr(exc, attribute)
    print(json.dumps(output, indent=2))
    return 0 if all(v["ok"] for v in output["checks"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
