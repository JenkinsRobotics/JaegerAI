"""Unit tests for host_capabilities feature tools and grants."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from jaeger_ai.features.host_capabilities import (
    camera_tools,
    grants,
    mac_tools,
    memory_tools,
    server,
    system_tools,
    workspace_tools,
)


def test_grants_resolve_valid_path(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    test_file = workspace / "test.txt"
    test_file.write_text("hello")

    monkeypatch.setattr(grants, "_roots", lambda *a: [workspace])
    monkeypatch.setattr(grants, "_grant", lambda: {"capabilities": ["workspace.read"]})

    # Relative to root
    resolved = grants._resolve("test.txt")
    assert resolved == test_file

    # Absolute inside root
    resolved = grants._resolve(str(test_file))
    assert resolved == test_file


def test_grants_resolve_rejects_outside_path(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "secret.txt"
    outside.write_text("secret")

    monkeypatch.setattr(grants, "_roots", lambda *a: [workspace])
    monkeypatch.setattr(grants, "_grant", lambda: {"capabilities": ["workspace.read"]})

    with pytest.raises(PermissionError, match="outside approved workspace roots"):
        grants._resolve(str(outside))


def test_workspace_tools_read_write(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    monkeypatch.setattr(grants, "_roots", lambda *a: [workspace])
    monkeypatch.setattr(grants, "_grant", lambda: {"capabilities": ["workspace.read", "workspace.write"]})
    monkeypatch.setattr(grants, "_audit", lambda *a, **kw: None)

    write_res = workspace_tools.workspace_write("hello.txt", "world")
    assert write_res["bytes_written"] == 5

    read_res = workspace_tools.workspace_read("hello.txt")
    assert read_res["content"] == "world"


def test_system_tools_capabilities_inspect(monkeypatch):
    monkeypatch.setattr(system_tools, "_roots", lambda *a: [Path("/fake/workspace")])
    monkeypatch.setattr(system_tools, "_grant", lambda: {
        "capabilities": ["workspace.read", "service.status"],
    })
    monkeypatch.setattr(system_tools, "_audit", lambda *a, **kw: None)
    monkeypatch.setattr(system_tools, "get_current_identity", lambda: "jaeger")

    res = system_tools.capabilities_inspect()
    assert res["identity"] == "jaeger"
    assert "workspace.read" in res["capabilities"]
    assert res["count"] == 2


def test_server_tools_registered():
    # Verify FastMCP server has registered all tools
    tool_names = set()
    if hasattr(server.mcp, "_tool_manager"):
        tm = server.mcp._tool_manager
        if hasattr(tm, "_tools"):
            tool_names = set(tm._tools.keys())
    assert "capabilities_inspect" in tool_names
    assert "workspace_read" in tool_names
    assert "workspace_write" in tool_names
    assert "service_status" in tool_names
    assert "calendar_list" in tool_names
    assert "notes_list" in tool_names
    assert "reminders_list" in tool_names
    assert "memory_query" in tool_names
