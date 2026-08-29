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
        accepted = threading.Event()

        def accept_once():
            conn, _ = sock.accept()
            bs.close_quietly(conn)
            accepted.set()

        worker = threading.Thread(target=accept_once)
        worker.start()
        live = bs.try_connect(path, timeout_s=1.0)
        assert live is not None
        bs.close_quietly(live)
        assert accepted.wait(1.0)
        worker.join(timeout=1.0)
        assert not worker.is_alive()
    finally:
        bs.close_quietly(sock)
        path.unlink(missing_ok=True)


def test_find_live_socket_skips_dead_files(tmp_path, monkeypatch):
    dead = tmp_path / "run" / "bridge.sock"
    dead.parent.mkdir(parents=True)
    dead.write_text("not a socket", encoding="utf-8")
    monkeypatch.setenv("JAEGER_INSTANCE_DIR", str(tmp_path))
    assert bs.find_live_socket(home=tmp_path, instance="x") is None


# ── Which instance a client with no explicit selector looks under ─────────
#
# candidate_paths() is the attach contract this module exists to serve: the
# process holding the 1:1 instance lock listens on the socket, and "every
# other client connects instead of spawning a second `jaeger bridge`". A
# client that looks under the wrong instance does not merely miss the attach
# — it falls through to spawning, and that spawn then collides with the very
# lock the socket was added to route around. ARES mirrors this function, so
# whatever it resolves here is what ARES resolves too.


def _home_with_sticky_default(tmp_path, name: str) -> Path:
    home = tmp_path / "install"
    (home / ".jaeger_ai").mkdir(parents=True)
    (home / ".jaeger_ai" / "active_instance").write_text(name + "\n", encoding="utf-8")
    return home


def test_candidate_paths_use_an_explicit_instance_verbatim(tmp_path):
    home = _home_with_sticky_default(tmp_path, "ares")

    paths = bs.candidate_paths(home=home, instance="jarvis")

    assert home / ".jaeger_ai" / "instances" / "jarvis" / "run" / bs.SOCKET_NAME in paths


def test_candidate_paths_fall_back_to_default_without_a_sticky_file(tmp_path):
    home = tmp_path / "install"
    (home / ".jaeger_ai").mkdir(parents=True)

    paths = bs.candidate_paths(home=home, instance=None)

    assert home / ".jaeger_ai" / "instances" / "default" / "run" / bs.SOCKET_NAME in paths


def test_candidate_paths_follow_the_sticky_default_instance(tmp_path):
    """An unset instance must resolve the way Jaeger itself resolves one.

    ``default_instance_name()`` documents the order as ``JAEGER_INSTANCE_NAME``
    → ``active_instance`` → literal ``"default"``. This function implements the
    first and last steps and omits the middle one, which is the only step that
    differs once an operator has picked an instance.
    """
    home = _home_with_sticky_default(tmp_path, "ares")

    paths = bs.candidate_paths(home=home, instance=None)

    assert home / ".jaeger_ai" / "instances" / "ares" / "run" / bs.SOCKET_NAME in paths
