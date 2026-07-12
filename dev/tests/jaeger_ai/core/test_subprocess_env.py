"""INST-4 — per-instance subprocess HOME jail."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from jaeger_ai.core.instance.instance import InstanceLayout
from jaeger_ai.core.instance.subprocess_env import (
    has_instance_home, populate_instance_home, subprocess_env_for_instance,
)


@pytest.fixture
def layout(tmp_path):
    """A fake instance layout for tests — bypasses the resolver."""
    return InstanceLayout(root=tmp_path / "inst")


# ── has_instance_home ──────────────────────────────────────────────


def test_has_instance_home_false_when_dir_missing(layout):
    assert has_instance_home(layout) is False


def test_has_instance_home_false_when_dir_empty(layout):
    layout.home_dir.mkdir(parents=True)
    assert has_instance_home(layout) is False


def test_has_instance_home_true_with_gitconfig(layout):
    layout.home_dir.mkdir(parents=True)
    (layout.home_dir / ".gitconfig").write_text("[user]\n  name = x")
    assert has_instance_home(layout) is True


def test_has_instance_home_true_with_marker_file(layout):
    """The bare marker file flips the switch even without
    .gitconfig / .ssh — useful for users who just want subproc
    isolation without setting up identity."""
    layout.home_dir.mkdir(parents=True)
    (layout.home_dir / ".jaeger-home-marker").touch()
    assert has_instance_home(layout) is True


# ── subprocess_env_for_instance ────────────────────────────────────


def test_env_unchanged_when_no_home(layout, monkeypatch):
    monkeypatch.setenv("HOME", "/Users/somebody")
    monkeypatch.setenv("PATH", "/usr/bin")
    env = subprocess_env_for_instance(layout)
    assert env["HOME"] == "/Users/somebody"
    assert env["PATH"] == "/usr/bin"
    # No XDG vars get injected when we're not in jail mode.
    assert "XDG_CONFIG_HOME" not in env or env.get("XDG_CONFIG_HOME") != str(layout.home_dir / ".config")


def test_env_swaps_home_when_jail_populated(layout, monkeypatch):
    monkeypatch.setenv("HOME", "/Users/somebody")
    layout.home_dir.mkdir(parents=True)
    (layout.home_dir / ".gitconfig").write_text("[user]")
    env = subprocess_env_for_instance(layout)
    assert env["HOME"] == str(layout.home_dir)
    assert env["USERPROFILE"] == str(layout.home_dir)
    assert env["XDG_CONFIG_HOME"] == str(layout.home_dir / ".config")
    assert env["XDG_CACHE_HOME"] == str(layout.home_dir / ".cache")


def test_base_env_passthrough(layout):
    """Custom base_env is honoured (so callers who already have a
    minimal env can compose with the per-instance HOME swap)."""
    base = {"PATH": "/sbin", "CUSTOM": "yes"}
    env = subprocess_env_for_instance(layout, base_env=base)
    assert env["PATH"] == "/sbin"
    assert env["CUSTOM"] == "yes"


# ── populate_instance_home ─────────────────────────────────────────


def test_populate_writes_gitconfig(layout):
    populate_instance_home(layout, git_name="Test Bot",
                           git_email="bot@example.com")
    body = (layout.home_dir / ".gitconfig").read_text(encoding="utf-8")
    assert "name = Test Bot" in body
    assert "email = bot@example.com" in body
    # And the marker file lands.
    assert (layout.home_dir / ".jaeger-home-marker").exists()


def test_populate_handles_partial_inputs(layout):
    """Only one of name/email — the other line is omitted, not blank."""
    populate_instance_home(layout, git_name="Bot", git_email=None)
    body = (layout.home_dir / ".gitconfig").read_text(encoding="utf-8")
    assert "name = Bot" in body
    assert "email" not in body


def test_populate_copies_ssh_key(layout, tmp_path):
    src = tmp_path / "id_test"
    src.write_text("PRIVATE-KEY-BODY", encoding="utf-8")
    pub = tmp_path / "id_test.pub"
    pub.write_text("ssh-rsa AAAA", encoding="utf-8")

    populate_instance_home(layout, ssh_key_source=str(src))

    dst = layout.home_dir / ".ssh" / "id_jaeger"
    pub_dst = layout.home_dir / ".ssh" / "id_jaeger.pub"
    assert dst.read_text() == "PRIVATE-KEY-BODY"
    assert pub_dst.read_text() == "ssh-rsa AAAA"
    # 0600 on the private key — anything else is a security bug.
    mode = dst.stat().st_mode & 0o777
    assert mode == 0o600


def test_populate_skips_missing_ssh_source(layout):
    """A non-existent ssh source is silently skipped; nothing else
    breaks (the marker still lands)."""
    populate_instance_home(layout, ssh_key_source="/nonexistent/path")
    assert (layout.home_dir / ".jaeger-home-marker").exists()
    assert not (layout.home_dir / ".ssh").exists()


def test_populate_is_idempotent(layout):
    populate_instance_home(layout, git_name="A")
    populate_instance_home(layout, git_name="B")
    body = (layout.home_dir / ".gitconfig").read_text()
    assert "name = B" in body
    assert "name = A" not in body


def test_populate_marker_only_flips_has_home(layout):
    """Even with no git/ssh inputs, populate writes the marker so
    has_instance_home returns True."""
    populate_instance_home(layout)
    assert has_instance_home(layout) is True
