"""Sensitive-path guard for file reads (audit A5).

`core/file_safety.py` refuses a `read_file` that resolves into a known
credential store. Reads are otherwise unconfined, so this is the only
thing between a tier-0 read and `~/.ssh/id_rsa`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from jaeger_os.core.safety.file_safety import is_sensitive_path


# ── blocked: credential locations ───────────────────────────────────


@pytest.mark.parametrize("path", [
    "/Users/me/.ssh/id_rsa",
    "/Users/me/.ssh/config",
    "/home/me/.aws/credentials",
    "/home/me/.kube/config",
    "/home/me/.gnupg/secring.gpg",
    "/Users/me/.docker/config.json",
    "/Users/me/.netrc",
    "/home/me/project/.env",
    "/home/me/project/.env.production",
    "/home/me/.git-credentials",
    "/Users/me/.zsh_history",
    "/Users/me/proj/id_ed25519",
    "/Users/me/Library/Keychains/login.keychain-db",
])
def test_blocks_credential_locations(path):
    assert is_sensitive_path(path) is not None, path


# ── allowed: ordinary files ─────────────────────────────────────────


@pytest.mark.parametrize("path", [
    "/Users/me/project/README.md",
    "/Users/me/project/src/main.py",
    "/home/me/project/.env.example",      # committed template
    "/home/me/project/.env.sample",
    "/Users/me/project/sshconfig.md",     # mentions ssh, not a .ssh dir
    "/Users/me/project/.ssh-notes/todo",  # .ssh-notes != .ssh
    "/Users/me/project/config.json",
])
def test_allows_ordinary_files(path):
    assert is_sensitive_path(path) is None, path


# ── _resolve_read integration ───────────────────────────────────────




