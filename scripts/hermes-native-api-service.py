#!/usr/bin/env python3
"""Host lifecycle supervisor for Hermes Agent's loopback native Runs API."""
import signal
import socket
import subprocess
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYTHON = Path.home() / ".jaeger/venv/bin/python"
KEY_FILE = Path.home() / ".hermes/jaeger-native-api.key"


def command():
    return [str(PYTHON), "-B", str(ROOT / "scripts/run-hermes-native-api.py"),
            "--key-file", str(KEY_FILE), "--host", "127.0.0.1", "--port", "8645"]


def ready() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", 8645), timeout=1):
            return True
    except OSError:
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
        if child is not None:
            child.terminate()
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=5)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
