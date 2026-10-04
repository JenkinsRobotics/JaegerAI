"""Phase 1 / workstream 3 (contained subset): helpers cannot elevate themselves.

- Host capability grants: the identity is self-declared through the
  ARES_CAPABILITY_IDENTITY env var, so "admin" can no longer be a wildcard.
- OpenClaw adapter: Jaeger's OpenClaw connection never requests
  ``operator.admin`` (it used to reopen the connection with admin scope to
  patch the session model).
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from jaeger_ai.features.host_capabilities import grants

REPO = Path(__file__).resolve().parents[4]


def test_self_declared_admin_gets_no_wildcard(monkeypatch):
    monkeypatch.setenv("ARES_CAPABILITY_IDENTITY", "admin")
    monkeypatch.setattr(grants, "_grant", lambda: {"capabilities": ["git.status"]})
    assert grants._require("git.status")
    with pytest.raises(PermissionError):
        grants._require("terminal.execute")


@pytest.mark.parametrize("identity", ["hermes", "openclaw", "jaeger"])
def test_helpers_need_explicit_grant(monkeypatch, identity):
    monkeypatch.setenv("ARES_CAPABILITY_IDENTITY", identity)
    monkeypatch.setattr(grants, "_grant", lambda: {"capabilities": []})
    with pytest.raises(PermissionError):
        grants._require("applescript.execute")


def test_openclaw_adapter_never_requests_operator_admin():
    from jaeger_ai.core.frameworks import openclaw_native

    assert "operator.admin" not in openclaw_native.SCOPES
    tree = ast.parse((REPO / "jaeger_ai/core/frameworks/openclaw_native.py").read_text())
    for node in ast.walk(tree):
        if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
            values = [e.value for e in node.elts if isinstance(e, ast.Constant)]
            assert "operator.admin" not in values, "OpenClaw adapter must not request operator.admin"
        if isinstance(node, ast.keyword) and node.arg == "scopes":
            src = ast.unparse(node.value)
            assert "admin" not in src, src
