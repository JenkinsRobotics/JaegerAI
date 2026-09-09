#!/usr/bin/env python3
"""Host lifecycle shim for the native API in the active Hermes container."""
import os
import json
import signal
import socket
import subprocess
import threading
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from jaeger_ai.core.runtime.agent_workspaces import container_name

ENGINE = "/opt/homebrew/bin/container"


def command():
    return [ENGINE, "exec", "--user", "hermeswebui", container_name("hermes"),
            "/app/venv/bin/python", "/mnt/host/GitHub/JaegerAI/scripts/run-hermes-native-api.py",
            "--key-file", "/home/hermeswebui/.hermes/jaeger-native-api.key",
            "--host", "0.0.0.0", "--port", "8645"]


def ready() -> bool:
    try:
        result = subprocess.run([ENGINE, "inspect", container_name("hermes")],
                                capture_output=True, text=True, timeout=5)
        if result.returncode:
            return False
        status = json.loads(result.stdout)[0]["status"]
        address = status["networks"][0]["ipv4Address"].split("/")[0]
        with socket.create_connection((address, 8645), timeout=1):
            return True
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, IndexError, TypeError):
        return False


def main() -> int:
    stopped = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stopped.set())
    child = None
    try:
        while not stopped.is_set():
            # Adopt a healthy listener left by a previous exec connection.
            # Never launch a competing server on the same port.
            if not ready() and (child is None or child.poll() is not None):
                child = subprocess.Popen(command())
            stopped.wait(2)
    finally:
        try:
            subprocess.run([*command(), "--stop"], timeout=10, check=False)
        except (OSError, subprocess.SubprocessError) as exc:
            print(f"Native API stop failed: {exc}", file=sys.stderr)
        if child is not None:
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.terminate()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
