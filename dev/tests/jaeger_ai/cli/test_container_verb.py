"""Tests for jaeger container CLI verb."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from jaeger_ai.cli.verbs.container_verb import _cmd_container_argv


def test_cmd_container_help(capsys):
    assert _cmd_container_argv(["--help"]) == 0
    captured = capsys.readouterr()
    assert "usage: jaeger container" in captured.err


def test_cmd_container_list(capsys):
    mock_containers = [
        {"id": "ares-openclaw", "state": "running", "ip": "192.168.65.2", "image": "openclaw:latest"}
    ]
    with patch("jaeger_ai.core.runtime.container_service.list_containers", return_value=mock_containers):
        res = _cmd_container_argv(["list"])
        assert res == 0
        captured = capsys.readouterr()
        assert "ares-openclaw" in captured.out
        assert "192.168.65.2" in captured.out


def test_cmd_container_start_success(capsys):
    with patch("jaeger_ai.core.runtime.container_service.start_container", return_value={"ok": True}):
        res = _cmd_container_argv(["start", "ares-openclaw"])
        assert res == 0
        captured = capsys.readouterr()
        assert "is now running" in captured.out


def test_cmd_container_stop_success(capsys):
    with patch("jaeger_ai.core.runtime.container_service.stop_container", return_value={"ok": True}):
        res = _cmd_container_argv(["stop", "ares-openclaw"])
        assert res == 0
        captured = capsys.readouterr()
        assert "stopped" in captured.out


def test_cmd_container_delete_success(capsys):
    with patch("jaeger_ai.core.runtime.container_service.delete_container", return_value={"ok": True}):
        res = _cmd_container_argv(["delete", "ares-openclaw"])
        assert res == 0
        captured = capsys.readouterr()
        assert "deleted" in captured.out
