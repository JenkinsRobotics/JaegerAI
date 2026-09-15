"""Keep the Jaeger Dispatcher extension sidecar healthy inside WebUI."""
from __future__ import annotations

import signal
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import urlopen

HEALTH_URL = "http://127.0.0.1:8646/health"
PROBE_INTERVAL_SECONDS = 2.0
FAILURE_LIMIT = 3
RESTART_BACKOFF_SECONDS = 1.0


def healthy() -> bool:
    try:
        with urlopen(HEALTH_URL, timeout=1.0) as response:
            return response.status == 200
    except (OSError, URLError):
        return False


def run(
    *,
    stop_requested=lambda: False,
    health_check=healthy,
    spawn=None,
    sleep=time.sleep,
) -> int:
    if spawn is None:
        spawn = lambda: subprocess.Popen(
            [sys.executable, "/apptoo/jaeger_dispatcher_sidecar.py"], close_fds=True
        )
    child = None
    failures = 0
    try:
        while not stop_requested():
            if child is None or child.poll() is not None:
                if child is not None:
                    sleep(RESTART_BACKOFF_SECONDS)
                child = spawn()
                failures = 0
            sleep(PROBE_INTERVAL_SECONDS)
            failures = 0 if health_check() else failures + 1
            if failures >= FAILURE_LIMIT and child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait(timeout=5)
                child = None
    finally:
        if child is not None and child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
    return 0


def main() -> int:
    stopping = False

    def request_stop(_signum, _frame):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    return run(stop_requested=lambda: stopping)


if __name__ == "__main__":
    raise SystemExit(main())
