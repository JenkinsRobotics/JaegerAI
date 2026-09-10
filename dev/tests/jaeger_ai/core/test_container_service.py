"""Tests for Apple native container tool lifecycle service."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from jaeger_ai.core.runtime import container_service as cs


def test_resolve_container_cli(monkeypatch):
    monkeypatch.setenv("CONTAINER_CLI", "/custom/bin/container")
    assert cs.resolve_container_cli() == "/custom/bin/container"


def test_is_system_running_true():
    with patch("subprocess.run") as mock_run, patch("pathlib.Path.exists", return_value=True):
        mock_run.return_value = MagicMock(returncode=0, stdout="apiserver is running")
        assert cs.is_system_running() is True


def test_is_system_running_false():
    with patch("subprocess.run") as mock_run, patch("pathlib.Path.exists", return_value=True):
        mock_run.return_value = MagicMock(returncode=1, stdout="apiserver is not running")
        assert cs.is_system_running() is False


def test_list_containers_from_cli_when_running():
    mock_payload = [
        {"id": "ares-openclaw", "state": "running", "ip": "192.168.65.2", "image": "openclaw:latest"}
    ]
    with patch("jaeger_ai.core.runtime.container_service.is_system_running", return_value=True), \
         patch("pathlib.Path.exists", return_value=True), \
         patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=json.dumps(mock_payload))
        res = cs.list_containers(all=True)
        assert len(res) == 1
        assert res[0]["id"] == "ares-openclaw"
        assert res[0]["state"] == "running"


def test_start_container_success():
    with patch("jaeger_ai.core.runtime.container_service.ensure_system_started", return_value=True), \
         patch("pathlib.Path.exists", return_value=True), \
         patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        res = cs.start_container("ares-openclaw")
        assert res["ok"] is True
        assert res["id"] == "ares-openclaw"
        assert res["state"] == "running"


def test_stop_container_success():
    with patch("pathlib.Path.exists", return_value=True), \
         patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        res = cs.stop_container("ares-openclaw")
        assert res["ok"] is True
        assert res["id"] == "ares-openclaw"
        assert res["state"] == "stopped"


def test_delete_container_success():
    with patch("jaeger_ai.core.runtime.container_service.ensure_system_started", return_value=True), \
         patch("pathlib.Path.exists", return_value=True), \
         patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        res = cs.delete_container("ares-openclaw", force=True)
        assert res["ok"] is True
        assert res["id"] == "ares-openclaw"
        assert res["deleted"] is True
