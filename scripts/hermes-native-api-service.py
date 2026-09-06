#!/usr/bin/env python3
"""Host lifecycle shim for the native API in the active Hermes container."""
import os
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


if __name__ == "__main__":
    os.execv(ENGINE, command())
