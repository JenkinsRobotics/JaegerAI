"""Serve browser contract tests using the existing isolated Gateway fixture.

Only the provider boundary is scripted. This is not real-provider installation
acceptance. Credentials, databases, logs and build output stay outside source.
"""
from pathlib import Path
import os
import signal
import subprocess
import sys
import tempfile
import threading

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def main():
    state = Path(tempfile.mkdtemp(prefix="jaeger-browser-contract-"))
    os.environ.update(JAEGER_STATE_DIR=str(state), JAEGER_HOME=str(state),
                      JAEGER_CALLER_TOKEN_DIR=str(state / "tokens"),
                      PYTHONDONTWRITEBYTECODE="1", JAEGER_NO_ATTACH="1",
                      JAEGER_CONTRACT_WEBUI_PORT="5173",
                      JAEGER_WEBUI_UI_DIST=str(state / "ui/dist"))
    subprocess.run([sys.executable, str(ROOT / "jaeger_ai/interfaces/ui/scripts/build-external.py"),
                    "--output-root", str(state / "ui")], check=True)
    from jaeger_ai.core.gateway.caller_auth import ensure_tokens
    from dev.tests.fixtures.owned_gateway import OwnedGateway
    ensure_tokens()
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    owner = OwnedGateway(state, webui=True)
    try:
        owner.start()
        print(f"Browser contract state: {state}; scripted provider only", flush=True)
        while not stop.wait(0.2):
            if owner.process.poll() is not None:
                raise RuntimeError(f"Browser contract child exited; logs: {state}")
    finally:
        owner.stop()


if __name__ == "__main__":
    main()
