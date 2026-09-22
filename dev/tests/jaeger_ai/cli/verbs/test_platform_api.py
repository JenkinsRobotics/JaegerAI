"""Workstream 23 — public platform API verbs.

A contributor can validate a capability, doctor providers, and inspect
devices using public contracts only.
"""
from __future__ import annotations

import json
from pathlib import Path

from jaeger_ai.cli.verbs import dispatch as cli
from jaeger_ai.cli.verbs import platform_api
from jaeger_ai.core.capabilities.manifest import CapabilityManifest


def test_platform_verbs_are_dispatched():
    for verb in ("capability", "provider", "device"):
        assert verb in cli.SUBCOMMANDS
        assert cli.is_daemon_subcommand([verb]) is True


def test_capability_validate_accepts_a_manifest(tmp_path: Path, capsys):
    pkg = tmp_path / "cap.example.upper"
    pkg.mkdir()
    (pkg / "executor.py").write_text(
        "def run(arguments, context=None):\n    return {'ok': True}\n",
        encoding="utf-8",
    )
    CapabilityManifest(
        capability_id="cap.example.upper",
        name="Upper",
        version="1.0.0",
        category="tool_adapter",
        execution_entrypoint="executor.py:run",
        is_executable=True,
    ).save(pkg)

    rc = platform_api._cmd_capability_argv(["validate", str(pkg), "--json"])
    assert rc == 0
    report = json.loads(capsys.readouterr().out)
    assert report["ok"] is True
    assert report["capability_id"] == "cap.example.upper"


def test_capability_validate_fails_closed_on_missing_entrypoint(tmp_path: Path, capsys):
    pkg = tmp_path / "cap.example.broken"
    pkg.mkdir()
    CapabilityManifest(
        capability_id="cap.example.broken",
        name="Broken",
        execution_entrypoint="missing.py:run",
        is_executable=True,
    ).save(pkg)
    rc = platform_api._cmd_capability_argv(["validate", str(pkg), "--json"])
    assert rc == 1
    report = json.loads(capsys.readouterr().out)
    assert report["ok"] is False
    assert any("missing" in e for e in report["errors"])


def test_provider_doctor_does_not_crash_without_credentials(capsys, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    rc = platform_api._cmd_provider_argv(["doctor", "--json", "--cached-only"])
    assert rc == 0
    report = json.loads(capsys.readouterr().out)
    assert report["source"] == "jaeger.runtime.truth"
    assert "groups" in report
    assert "supported_not_live" in report


def test_device_inspect_reports_clients_and_experimental_registry(capsys):
    rc = platform_api._cmd_device_argv(["inspect", "--json"])
    assert rc == 0
    report = json.loads(capsys.readouterr().out)
    names = {row["name"] for row in report["client_surfaces"]}
    assert "WebUI" in names
    assert "Mac SwiftUI" in names
    assert "Phone PWA" in names
    assert "EXPERIMENTAL" in report["registry_status"]
    assert report["registered"] == []


def test_unknown_device_id_fails_closed(capsys):
    rc = platform_api._cmd_device_argv(["inspect", "dev_does_not_exist", "--json"])
    assert rc == 1
    report = json.loads(capsys.readouterr().out)
    assert report["ok"] is False
