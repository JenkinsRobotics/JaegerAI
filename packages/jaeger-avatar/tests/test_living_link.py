"""Unit tests for jaeger_avatar.living_link (AvatarLink, probe_avatar_link, CLI main)."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

import pytest
from jaeger_avatar import AvatarLink, probe_avatar_link
from jaeger_avatar import living_link as ll


def _start_stub_avatar_server(mode: str = "accepted", expected_token: str = "tok-secret") -> tuple[HTTPServer, int, list[dict[str, Any]]]:
    received: list[dict[str, Any]] = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            return

        def do_GET(self) -> None:
            if self.path == "/health":
                body = json.dumps({"ok": True}).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            self.send_response(404)
            self.end_headers()

        def do_POST(self) -> None:
            if self.path != "/control":
                self.send_response(404)
                self.end_headers()
                return
            token = self.headers.get("X-Avatar-Token", "")
            length = int(self.headers.get("Content-Length") or "0")
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            received.append({"token": token, "payload": payload})
            if token != expected_token:
                body = json.dumps({"error": "Unauthorized"}).encode("utf-8")
                self.send_response(401)
            elif mode == "no_stage":
                body = json.dumps({"error": "No avatar attached"}).encode("utf-8")
                self.send_response(409)
            else:
                body = json.dumps({"ok": True, "op": payload.get("op"), "value": payload.get("value")}).encode("utf-8")
                self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = HTTPServer(("127.0.0.1", 0), Handler)
    port = int(server.server_address[1])
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, port, received


def test_probe_avatar_link_control_accepted(tmp_path: Path) -> None:
    server, port, received = _start_stub_avatar_server(mode="accepted", expected_token="tok-ok")
    try:
        (tmp_path / "avatar_link.json").write_text(
            json.dumps({"url": f"http://127.0.0.1:{port}", "token": "tok-ok"}),
            encoding="utf-8",
        )
        res = probe_avatar_link(face="vita", port=port, launch_if_needed=False, state_dir=tmp_path)
        assert res["serving"] is True
        assert res["status"] == "control_accepted"
        assert res["control_token_configured"] is True
        assert res["response"]["value"] == "joy"
        assert received and received[0]["payload"]["op"] == "emotion"
    finally:
        server.shutdown()
        server.server_close()


def test_probe_avatar_link_stage_not_attached(tmp_path: Path) -> None:
    server, port, _ = _start_stub_avatar_server(mode="no_stage", expected_token="tok-ok")
    try:
        (tmp_path / "avatar_link.json").write_text(
            json.dumps({"url": f"http://127.0.0.1:{port}", "token": "tok-ok"}),
            encoding="utf-8",
        )
        res = probe_avatar_link(face="vita", port=port, launch_if_needed=False, state_dir=tmp_path)
        assert res["serving"] is True
        assert res["status"] == "stage_not_attached"
        assert "no stage is showing" in res["note"]
    finally:
        server.shutdown()
        server.server_close()


def test_probe_avatar_link_propagates_auth_error(tmp_path: Path) -> None:
    server, port, _ = _start_stub_avatar_server(mode="accepted", expected_token="tok-expected")
    try:
        (tmp_path / "avatar_link.json").write_text(
            json.dumps({"url": f"http://127.0.0.1:{port}", "token": "tok-wrong"}),
            encoding="utf-8",
        )
        with pytest.raises(RuntimeError, match="Unauthorized"):
            probe_avatar_link(face="vita", port=port, launch_if_needed=False, state_dir=tmp_path)
    finally:
        server.shutdown()
        server.server_close()


def test_living_link_main_check_cli(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    server, port, _ = _start_stub_avatar_server(mode="accepted", expected_token="tok-cli")
    try:
        monkeypatch.setenv("JAEGER_STATE_DIR", str(tmp_path))
        (tmp_path / "avatar_link.json").write_text(
            json.dumps({"url": f"http://127.0.0.1:{port}", "token": "tok-cli"}),
            encoding="utf-8",
        )
        rc = ll.main(["--check", "--no-launch", "--port", str(port), "--face", "vita"])
        assert rc == 0
        out = capsys.readouterr().out
        assert f"http://127.0.0.1:{port}/?face=vita" in out
        assert "control accepted:" in out
        assert AvatarLink(url=f"http://127.0.0.1:{port}", state_dir=tmp_path).is_alive() is True
    finally:
        server.shutdown()
        server.server_close()
