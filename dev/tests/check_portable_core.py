"""Smoke-test the shipped Core archive, not imports from the source checkout."""

from __future__ import annotations

import argparse
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import uuid
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from zipfile import ZipFile


def request(url: str, payload: dict | None = None) -> bytes:
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode() if payload is not None else None,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=12) as response:
        return response.read()


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def check(bundle: Path, python: Path | None = None) -> None:
    marker = f"core-proof-{uuid.uuid4().hex}"
    tool_verified = threading.Event()

    class ModelFixture(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args: object) -> None:
            pass

        def send_payload(self, payload: dict, *, streaming: bool = False) -> None:
            data = (json.dumps(payload) + "\n").encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson" if streaming else "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self) -> None:
            self.send_payload({"models": [{"name": "portable-test", "context_length": 32768}]})

        def do_POST(self) -> None:
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            if self.path == "/api/show":
                self.send_payload({"model_info": {"test.context_length": 32768}})
                return
            message: dict = {"role": "assistant", "content": ""}
            if any(m["role"] == "tool" and marker in str(m.get("content"))
                   for m in body.get("messages", [])):
                tool_verified.set()
                message["content"] = marker
            else:
                assert "read_file" in {t["function"]["name"] for t in body.get("tools", [])}
                message["tool_calls"] = [{
                    "function": {"name": "read_file", "arguments": {"path": "portable-proof.txt"}},
                }]
            self.send_payload({"message": message, "done": True}, streaming=bool(body.get("stream")))

    with tempfile.TemporaryDirectory(prefix="jaeger-core-smoke-") as temp:
        work = Path(temp)
        if python is None:
            with ZipFile(bundle) as archive:
                archive.extractall(work)
            subprocess.run(
                [sys.executable, "-B", str(work / "install-core.py"), "--venv", str(work / "venv")],
                cwd=work, check=True,
            )
            python = work / "venv" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
        workspace = work / "workspace"
        workspace.mkdir()
        (workspace / "portable-proof.txt").write_text(marker, encoding="utf-8")
        with ThreadingHTTPServer(("127.0.0.1", 0), ModelFixture) as fixture:
            thread = threading.Thread(target=fixture.serve_forever, daemon=True)
            thread.start()
            env = {**os.environ}
            env.pop("JAEGER_GATEWAY_TOKEN", None)
            env.update({
                "JAEGER_STATE_DIR": str(work / "state"),
                "JAEGER_WORKSPACE": str(workspace),
                "JAEGER_GATEWAY_HOST": "127.0.0.1",
                "JAEGER_WEBUI_HOST": "127.0.0.1",
                "JAEGER_GATEWAY_OLLAMA_MODEL": "portable-test",
                "OLLAMA_HOST": f"http://127.0.0.1:{fixture.server_port}",
                "JAEGER_ELEVATED": "1",  # Core must not inherit the full profile's authority.
                "JAEGER_NO_ATTACH": "1",
                "JAEGER_TEST_HEADLESS": "1",
            })

            @contextmanager
            def boot():
                api_port, ui_port = free_port(), free_port()
                while ui_port == api_port:
                    ui_port = free_port()
                url = f"http://127.0.0.1:{ui_port}"
                env["JAEGER_GATEWAY_PORT"] = str(api_port)
                env["JAEGER_WEBUI_PORT"] = str(ui_port)
                log_path = work / "gateway.log"
                with log_path.open("w", encoding="utf-8") as log:
                    proc = subprocess.Popen(
                        [str(python), "-I", "-B", "-m", "jaeger_ai", "core"],
                        cwd=work, env=env, stdout=log, stderr=subprocess.STDOUT,
                    )
                    try:
                        for _ in range(80):
                            if proc.poll() is not None:
                                raise RuntimeError("Core terminated during startup.")
                            try:
                                health = json.loads(request(url + "/health"))
                            except (OSError, ValueError):
                                time.sleep(0.1)
                                continue
                            # Windows venv launchers can run the interpreter in a child.
                            assert Path(health["state_dir"]).resolve() == (work / "state").resolve()
                            if sys.platform != "win32":
                                assert health["pid"] == proc.pid
                            assert health["profile"] == "core" and not health["elevated"]
                            assert health["sandbox"] == "host_processes_disabled"
                            break
                        else:
                            raise TimeoutError("Core did not start on its disposable port.")
                        yield url
                    except Exception:
                        print(log_path.read_text(encoding="utf-8", errors="replace"), file=sys.stderr)
                        raise
                    finally:
                        if proc.poll() is None:
                            proc.terminate()
                            try:
                                proc.wait(timeout=8)
                            except subprocess.TimeoutExpired:
                                proc.kill()
                                proc.wait(timeout=4)

            try:
                with boot() as url:
                    index = request(url + "/").decode()
                    script = re.search(r'src="(/assets/[^"]+\.js)"', index)
                    assert script and len(request(url + script[1])) > 1024
                    profile = json.loads(request(url + "/v1/identity"))["identity"]
                    assert profile["owner_name"] == "Owner"
                    assert profile["channels"] == profile["objectives"] == []
                    assert json.loads(request(url + "/v1/sessions"))["sessions"] == []
                    sid = json.loads(request(url + "/v1/sessions", {"title": "Core smoke"}))["session"]["session_id"]
                    run = json.loads(request(f"{url}/v1/sessions/{sid}/runs", {
                        "prompt": "Report the portability marker from the supplied workspace sample.",
                        "wait": True,
                    }))
                    assert run["result"]["content"] == marker, run
                    assert tool_verified.is_set(), "Model fixture never saw the real tool output."
                with boot() as url:
                    messages = json.loads(request(f"{url}/v1/sessions/{sid}/messages"))["messages"]
                    assert any(m["role"] == "assistant" and m["content"] == marker for m in messages)
            finally:
                fixture.shutdown()
                thread.join(timeout=2)
    print("Core installed and served its WebUI, ran a workspace tool, and replayed chat after restart.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("bundle", type=Path)
    ap.add_argument("--python", type=Path, help="Use an already installed disposable interpreter.")
    args = ap.parse_args()
    bundle = args.bundle
    if bundle.is_dir():
        bundle, = bundle.glob("jaeger-core-*.zip")
    check(bundle.resolve(), args.python.resolve() if args.python else None)
