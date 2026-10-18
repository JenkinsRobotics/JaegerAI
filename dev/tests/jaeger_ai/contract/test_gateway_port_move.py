"""The Gateway lives on ``GATEWAY_PORT``; the pre-2026-10-17 port is retired.

One constant decides the default (``jaeger_ai/contract/ports.py``). There is no
fallback port anywhere: ``JAEGER_GATEWAY_URL`` and ``JAEGER_GATEWAY_PORT`` are
the only overrides.
"""
from __future__ import annotations

import importlib
import json
import pathlib
import re
import subprocess
import sys

from jaeger_ai.contract import ports

REPO = pathlib.Path(__file__).resolve().parents[4]
RETIRED_PORT = str(8800 + 10)  # spelled out so this file is not a grep hit


def test_gateway_url_is_loopback_on_the_contract_port():
    assert ports.GATEWAY_URL == f"http://{ports.LOOPBACK}:{ports.GATEWAY_PORT}"
    assert ports.LOOPBACK == "127.0.0.1"
    assert not hasattr(ports, "LEGACY_GATEWAY_PORT")
    assert not hasattr(ports, "gateway_candidate_urls")


def test_port_env_override_still_works():
    code = "from jaeger_ai.contract import ports; print(ports.GATEWAY_PORT, ports.GATEWAY_URL)"
    env = {"JAEGER_GATEWAY_PORT": "40001", "PATH": "/usr/bin:/bin"}
    out = subprocess.run([sys.executable, "-c", code], cwd=REPO, env=env,
                         capture_output=True, text=True, check=True).stdout.split()
    assert out == ["40001", "http://127.0.0.1:40001"]


def test_resolve_is_explicit_url_else_contract_port_without_probing():
    assert ports.resolve_gateway_url({}) == ports.GATEWAY_URL
    assert ports.resolve_gateway_url({"JAEGER_GATEWAY_URL": "http://h:1/"}) == "http://h:1"
    assert ports.resolve_gateway_url({"JAEGER_GATEWAY_PORT": "40002"}) == "http://127.0.0.1:40002"
    assert ports.resolve_gateway_url({"JAEGER_GATEWAY_LEGACY_FALLBACK": "1"}) == ports.GATEWAY_URL
    assert ports.is_gateway_port(ports.GATEWAY_PORT) and not ports.is_gateway_port(int(RETIRED_PORT))


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
    assert RETIRED_PORT not in gateway["keywords"]


def test_retired_port_appears_nowhere_in_code():
    pattern = re.compile(rf"(?<![0-9]){RETIRED_PORT}(?![0-9])")
    files = subprocess.run(["git", "ls-files", "*.py", "*.js", "*.swift", "*.sh", "*.json", "*.ts"],
                           cwd=REPO, capture_output=True, text=True, check=True).stdout.split()
    offenders = []
    for rel in files:
        if "vendor" in rel or rel.startswith("docs/archive"):
            continue
        path = REPO / rel
        if not path.is_file():
            continue
        for no, line in enumerate(path.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
            if pattern.search(line):
                offenders.append(f"{rel}:{no}: {line.strip()[:120]}")
    assert not offenders, "retired Gateway port still in code:\n" + "\n".join(offenders)


def test_gateway_port_mirrors_agree_with_the_contract():
    swift = (REPO / "jaeger_ai/interfaces/swift/Sources/JaegerAI/Bridge/GatewayClient.swift").read_text()
    assert re.search(rf"static let currentPort = {ports.GATEWAY_PORT}\b", swift)
    assert "legacyPort" not in swift and "LEGACY_FALLBACK" not in swift
    extension = (REPO / "jaeger_ai/interfaces/ide/extension.js").read_text()
    assert f"gatewayUrl: '{ports.GATEWAY_URL}'" in extension
    assert "legacyGatewayUrl" not in extension


def test_ide_packager_reads_only_the_current_port():
    sys.path.insert(0, str(REPO / "jaeger_ai/interfaces/ide"))
    try:
        packager = importlib.import_module("package_extension")
        constants = packager.gateway_contract(REPO)
    finally:
        sys.path.pop(0)
    assert constants == {"LOOPBACK": ports.LOOPBACK, "GATEWAY_PORT": ports.GATEWAY_PORT}
    json.dumps(constants)
