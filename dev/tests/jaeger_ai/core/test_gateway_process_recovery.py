"""Actual process death at the Gateway store boundary, not a simulated PID.

This proves durable admissions and ownership recovery, not provider-side
exactly-once effects or end-to-end Gateway/WebUI restart acceptance.
"""

import json
import os
import select
import subprocess
import sys
from pathlib import Path

import pytest

from jaeger_ai.core.gateway.session_store import GatewaySessionStore

pytestmark = [pytest.mark.integration, pytest.mark.subprocess]
REPO = Path(__file__).resolve().parents[4]

OWNER = """
import json, sys
from pathlib import Path
from jaeger_ai.core.gateway.session_store import GatewaySessionStore
store = GatewaySessionStore(Path(sys.argv[1]))
assert store.claim_process()['ok']
request = store.admit_request('s', 'durable work', request_id='crash-request')
store.bind_native('crash-request', native_run_id='native-receipt', native_session='s')
print(json.dumps(request), flush=True)
sys.stdin.read()
"""

SUCCESSOR = """
import json, sys
from pathlib import Path
from jaeger_ai.core.gateway.session_store import GatewaySessionStore
store = GatewaySessionStore(Path(sys.argv[1]))
assert store.claim_process()['ok']
store.recover_interrupted_sessions()
print(json.dumps({'request': store.get_request('crash-request'),
                  'session': store.get_session('s'),
                  'second_recovery': store.recover_interrupted_sessions()}))
assert store.release_process()
"""


def test_crashed_owner_preserves_admission_without_claiming_completion(tmp_path):
    database = tmp_path / "gateway.sqlite3"
    environment = {
        **os.environ,
        "JAEGER_STATE_DIR": str(tmp_path / "state"),
        "JAEGER_HOME": str(tmp_path / "home"),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONPATH": os.pathsep.join([
            str(REPO), str(REPO / "packages/jaeger-agent"), str(REPO / "packages/jaeger-os"),
        ]),
    }
    process = subprocess.Popen(
        [sys.executable, "-c", OWNER, str(database)],
        cwd=tmp_path, env=environment,
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        ready, _, _ = select.select([process.stdout], [], [], 10)
        assert ready, "isolated store owner did not publish its committed admission"
        admitted = json.loads(process.stdout.readline())
        assert admitted["accepted"] is True
        store = GatewaySessionStore(database)
        assert store.claim_process()["ok"] is False
        # Kill only the child created above. No cleanup runs in the dead owner.
        process.kill()
        process.wait(timeout=5)
    finally:
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=5)

    successor = subprocess.run(
        [sys.executable, "-c", SUCCESSOR, str(database)],
        cwd=tmp_path, env=environment, capture_output=True, text=True, timeout=10, check=True,
    )
    recovered = json.loads(successor.stdout)
    assert recovered["request"]["status"] == "execution_unknown"
    assert recovered["request"]["turn_id"] == admitted["turn_id"]
    assert recovered["request"]["native_run_id"] == "native-receipt"
    assert recovered["session"]["status"] == "execution_unknown"
    assert [(m["role"], m["content"]) for m in recovered["session"]["messages"]] == [
        ("user", "durable work"),
    ]
    assert recovered["second_recovery"] == 0
    assert database.is_file()
    assert store.process_lease() is None
