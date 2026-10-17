"""The Gateway moved to ``GATEWAY_PORT``; ``LEGACY_GATEWAY_PORT`` is a fallback.

One constant decides the default (``jaeger_ai/contract/ports.py``). Clients try
the current URL first and fall back to the legacy URL only when the current one
does not answer, so installed services still on the old port keep working
until the switch is approved. ``JAEGER_GATEWAY_PORT`` and
``JAEGER_GATEWAY_URL`` stay as overrides.
"""
from __future__ import annotations

import importlib
import json
import pathlib
import re
import socket
import subprocess
import sys

import pytest

from jaeger_ai.contract import ports

REPO = pathlib.Path(__file__).resolve().parents[4]


def test_gateway_url_is_loopback_on_the_contract_port():
    assert ports.GATEWAY_URL == f"http://{ports.LOOPBACK}:{ports.GATEWAY_PORT}"
    assert ports.LEGACY_GATEWAY_URL == f"http://{ports.LOOPBACK}:{ports.LEGACY_GATEWAY_PORT}"
    assert ports.LOOPBACK == "127.0.0.1"


def test_port_env_override_still_works_including_the_legacy_port():
    code = "from jaeger_ai.contract import ports; print(ports.GATEWAY_PORT, ports.GATEWAY_URL)"
    env = {"JAEGER_GATEWAY_PORT": str(ports.LEGACY_GATEWAY_PORT), "PATH": "/usr/bin:/bin"}
    out = subprocess.run([sys.executable, "-c", code], cwd=REPO, env=env,
                         capture_output=True, text=True, check=True).stdout.split()
    assert out == [str(ports.LEGACY_GATEWAY_PORT), ports.LEGACY_GATEWAY_URL]


def test_candidates_current_first_then_legacy():
    assert ports.gateway_candidate_urls({}) == [ports.GATEWAY_URL, ports.LEGACY_GATEWAY_URL]


def test_explicit_url_is_the_only_candidate():
    assert ports.gateway_candidate_urls({"JAEGER_GATEWAY_URL": "http://h:1/"}) == ["http://h:1"]


def test_fallback_can_be_turned_off():
    env = {"JAEGER_GATEWAY_LEGACY_FALLBACK": "0"}
    assert ports.gateway_candidate_urls(env) == [ports.GATEWAY_URL]
    assert ports.gateway_legacy_fallback_enabled(env) is False


def test_port_override_to_legacy_does_not_duplicate():
    env = {"JAEGER_GATEWAY_PORT": str(ports.LEGACY_GATEWAY_PORT)}
    assert ports.gateway_candidate_urls(env) == [ports.LEGACY_GATEWAY_URL]


@pytest.mark.parametrize(("up", "expected"), [
    ({"current", "legacy"}, "current"),
    ({"legacy"}, "legacy"),
    (set(), "current"),
])
def test_resolve_prefers_current_and_falls_back(up, expected):
    names = {ports.GATEWAY_URL: "current", ports.LEGACY_GATEWAY_URL: "legacy"}
    seen: list[str] = []

    def reachable(url: str, timeout: float) -> bool:
        seen.append(names[url])
        return names[url] in up

    got = ports.resolve_gateway_url({}, reachable=reachable)
    assert names[got] == expected
    assert seen[0] == "current"


def test_resolve_probes_real_sockets():
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    open_port = listener.getsockname()[1]
    closed = socket.socket()
    closed.bind(("127.0.0.1", 0))
    closed_port = closed.getsockname()[1]
    closed.close()
    try:
        assert ports._tcp_reachable(f"http://127.0.0.1:{open_port}", 0.5) is True
        assert ports._tcp_reachable(f"http://127.0.0.1:{closed_port}", 0.5) is False
    finally:
        listener.close()


def test_server_binds_loopback_by_default():
    code = ("from jaeger_ai.core.gateway import server; "
            "print(server.DEFAULT_GATEWAY_HOST, server.DEFAULT_GATEWAY_PORT)")
    env = {"PATH": "/usr/bin:/bin", "JAEGER_NO_GUI": "1"}
    out = subprocess.run([sys.executable, "-c", code], cwd=REPO, env=env,
                         capture_output=True, text=True, check=True).stdout.split()
    assert out[-2:] == [ports.LOOPBACK, str(ports.GATEWAY_PORT)]


def test_registry_and_specialists_use_the_contract_port(tmp_path):
    from jaeger_ai.core.agent_registry import specialists
    from jaeger_ai.core.agent_registry.registry import AgentRegistry

    assert AgentRegistry(tmp_path).to_catalog()["gateway_port"] == ports.GATEWAY_PORT
    gateway = next(s for s in specialists.STANDING_SPECIALISTS if s["name"] == "gateway")
    assert gateway["summary"].endswith(f":{ports.GATEWAY_PORT}.")
    assert str(ports.GATEWAY_PORT) in gateway["keywords"]


def test_no_bare_legacy_port_outside_the_contract():
    """Code may name the legacy port only through ports.py (Swift mirrors it once)."""
    legacy = str(ports.LEGACY_GATEWAY_PORT)
    pattern = re.compile(rf"(?<![0-9]){legacy}(?![0-9])")
    allowed = {
        "jaeger_ai/contract/ports.py",
        # Swift cannot import Python; it mirrors the constant once and
        # test_gateway_port_mirrors_agree_with_the_contract joins the two.
        "jaeger_ai/interfaces/swift/Sources/JaegerAI/Bridge/GatewayClient.swift",
    }
    files = subprocess.run(["git", "ls-files", "*.py", "*.js", "*.swift", "*.sh", "*.json"],
                           cwd=REPO, capture_output=True, text=True, check=True).stdout.split()
    offenders = []
    for rel in files:
        if rel in allowed or "vendor" in rel or rel.startswith(("docs/archive", "dev/tests")):
            continue
        if rel.endswith("/tests") or "/tests/" in rel:
            continue
        path = REPO / rel
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for no, line in enumerate(text.splitlines(), 1):
            if pattern.search(line):
                offenders.append(f"{rel}:{no}: {line.strip()[:120]}")
    assert not offenders, "bare legacy Gateway port outside ports.py:\n" + "\n".join(offenders)


def test_gateway_port_mirrors_agree_with_the_contract():
    swift = (REPO / "jaeger_ai/interfaces/swift/Sources/JaegerAI/Bridge/GatewayClient.swift").read_text()
    assert re.search(rf"static let currentPort = {ports.GATEWAY_PORT}\b", swift)
    assert re.search(rf"static let legacyPort = {ports.LEGACY_GATEWAY_PORT}\b", swift)
    extension = (REPO / "jaeger_ai/interfaces/ide/extension.js").read_text()
    assert f"gatewayUrl: '{ports.GATEWAY_URL}'" in extension


def test_ide_packager_generates_current_and_legacy_urls():
    sys.path.insert(0, str(REPO / "jaeger_ai/interfaces/ide"))
    try:
        packager = importlib.import_module("package_extension")
        constants = packager.gateway_contract(REPO)
    finally:
        sys.path.pop(0)
    assert constants == {
        "LOOPBACK": ports.LOOPBACK,
        "GATEWAY_PORT": ports.GATEWAY_PORT,
        "LEGACY_GATEWAY_PORT": ports.LEGACY_GATEWAY_PORT,
    }
    json.dumps(constants)
