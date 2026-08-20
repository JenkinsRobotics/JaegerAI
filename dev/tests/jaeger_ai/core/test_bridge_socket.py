"""Attach-if-running socket path helpers."""

from __future__ import annotations

import types
from pathlib import Path

from jaeger_ai.core.runtime import bridge_socket as bs


def test_socket_path_is_under_the_instance_run_dir(tmp_path):
    layout = types.SimpleNamespace(root=tmp_path)
    path = bs.socket_path(layout)
    assert path == tmp_path / "run" / "bridge.sock"


def test_bind_creates_a_restricted_socket(tmp_path):
    import os
    import threading
    # AF_UNIX paths are short on macOS — don't use pytest's deep tmp_path.
    path = Path(f"/tmp/jbr{os.getpid()}.sock")
    sock = bs.bind(path)
    try:
        assert path.exists()
        threading.Thread(target=lambda: sock.accept(), daemon=True).start()
        live = bs.try_connect(path, timeout_s=1.0)
        assert live is not None
        bs.close_quietly(live)
    finally:
        bs.close_quietly(sock)
        path.unlink(missing_ok=True)


def test_find_live_socket_skips_dead_files(tmp_path, monkeypatch):
    dead = tmp_path / "run" / "bridge.sock"
    dead.parent.mkdir(parents=True)
    dead.write_text("not a socket", encoding="utf-8")
    monkeypatch.setenv("JAEGER_INSTANCE_DIR", str(tmp_path))
    assert bs.find_live_socket(home=tmp_path, instance="x") is None
