"""Owned Gateway process harness shared by contract suites.

The child boots only this suite's runtime against a scratch state root with a
scripted provider boundary (see gateway_contract_worker.py). No operator
listener, model, or live database is ever used.
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path


# dev/tests/fixtures/owned_gateway.py → repo root
REPO = Path(__file__).resolve().parents[3]


def auth(caller="cli"):
    """The test drives the owned Gateway as the owner CLI caller by default."""
    from jaeger_ai.core.gateway.caller_auth import client_headers
    return client_headers(caller)


class OwnedGateway:
    def __init__(self, root, *, webui=False):
        self.root = root
        self.process = None
        self.log = None
        self.url = ""
        self.identity = None
        self.webui = webui
        self.webui_url = None

    def start(self):
        ready = self.root / "listener.json"
        ready.unlink(missing_ok=True)
        self.log = (self.root / "gateway.log").open("a", encoding="utf-8")
        # This harness is the approval contract: prompts, grants, denials.
        # Pin the saved autonomy to "ask" before the worker boots so no
        # test inherits the product-wide "auto" default.
        instance = self.root / "instances" / "contract"
        instance.mkdir(parents=True, exist_ok=True)
        from jaeger_ai.core.instance.schemas import (
            Config, ExternalModelConfig, ModelConfig, dump_yaml)
        # Same external_model surface the worker would write, so the
        # model-override contracts keep their scripted provider, plus the
        # pinned autonomy for the approval contracts.
        cfg = Config(instance_name="contract",
                     model=ModelConfig(model_path="/dev/null"),
                     external_model=ExternalModelConfig(
                         enabled=True, provider="openai", model="contract-model",
                         base_url="http://127.0.0.1:9/v1",
                         api_key_env="JAEGER_CONTRACT_API_KEY"),
                     automation={"autonomy": "ask"})
        dump_yaml(instance / "config.yaml", cfg)
        environment = {
            **os.environ, "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONPATH": os.pathsep.join([
                str(REPO),
                str(REPO / "packages/jaeger-agent"),
                str(REPO / "packages/jaeger-os"),
                str(REPO / "packages/jaeger-kokoro-tts"),
                str(REPO / "packages/jaeger-whisper-stt"),
            ]),
            "JAEGER_STATE_DIR": str(self.root),
            "JAEGER_HOME": str(self.root),
            "JAEGER_INSTANCE_DIR": str(self.root / "instances" / "contract"),
            "JAEGER_CRON_POLL_S": "0.2",
            "JAEGER_IDLE_POLL_S": "0.2",
            "JAEGER_BACKGROUND_PRODUCERS": "1",
            "JAEGER_WEBHOOK_PORT": "0",
        }
        command = [sys.executable, str(REPO / "dev/tests/fixtures/gateway_contract_worker.py"), str(self.root)]
        if self.webui:
            command.append("--webui")
        self.process = subprocess.Popen(
            command,
            cwd=self.root, env=environment, stdout=self.log, stderr=subprocess.STDOUT,
        )
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if ready.exists():
                listener = json.loads(ready.read_text(encoding="utf-8"))
                assert listener["pid"] == self.process.pid
                assert listener["mode"] == "owner"
                assert listener["resident"] is True
                self.identity = listener["entity_id"]
                self.url = f"http://127.0.0.1:{listener['port']}"
                if self.webui:
                    self.webui_url = f"http://127.0.0.1:{listener['webui_port']}"
                return
            if self.process.poll() is not None:
                break
            time.sleep(0.05)
        raise AssertionError((self.root / "gateway.log").read_text(encoding="utf-8"))

    def stop(self):
        if self.process is not None and self.process.poll() is None:
            self.process.kill()
            self.process.wait(timeout=5)
        if self.log is not None:
            self.log.close()

    def request(self, path, body=None, caller="cli"):
        from urllib.request import Request, urlopen
        request = Request(
            self.url + path, data=None if body is None else json.dumps(body).encode(),
            headers={"Content-Type": "application/json", **auth(caller)},
        )
        with urlopen(request, timeout=5) as response:
            return response.status, json.load(response)

    def wait_for_terminal(self, session, request_id):
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            _, row = self.request(f"/v1/sessions/{session}/requests/{request_id}")
            if row["status"] in {"completed", "failed", "execution_unknown", "cancelled"}:
                return row
            time.sleep(0.05)
        raise AssertionError((self.root / "gateway.log").read_text())