"""Exercise the desktop relay with real pipes and a real Unix socket."""
import io
import json
import os
import socket
import threading
import tempfile
from pathlib import Path

import pytest
from types import SimpleNamespace

from jaeger_ai.core.runtime import bridge_socket
from jaeger_ai.interfaces.bridge_attach import relay


@pytest.fixture
def short_root():
    with tempfile.TemporaryDirectory(prefix="ja-", dir="/tmp") as directory:
        yield Path(directory)


def test_relay_preserves_frames_and_quit_does_not_stop_owner(short_root):
    layout = SimpleNamespace(root=short_root)
    server = bridge_socket.bind(bridge_socket.socket_path(layout))
    reader, writer = os.pipe()
    output = io.StringIO()
    received = []
    ready = threading.Event()

    def owner():
        conn, _ = server.accept()
        with conn:
            conn.sendall(b'{"type":"ready","instance":"selected"}\n')
            received.append(conn.recv(4096))
            conn.sendall('{"type":"result","text":"café"}\n'.encode())
            ready.set()
            received.append(conn.recv(4096))

    owner_thread = threading.Thread(target=owner)
    owner_thread.start()
    result = []
    with os.fdopen(reader, 'rb', buffering=0) as source:
        client = threading.Thread(target=lambda: result.append(relay(layout, source, output)))
        client.start()
        os.write(writer, b'{"op":"query","id":"q1"}\n')
        assert ready.wait(5)
        # Let the response pass through before requesting a local disconnect.
        import time
        deadline = time.monotonic() + 5
        while 'café' not in output.getvalue() and time.monotonic() < deadline:
            time.sleep(.01)
        os.write(writer, b'{"op":"quit"}\n')
        client.join(5)
        assert not client.is_alive()
    os.close(writer)
    owner_thread.join(5)
    assert not owner_thread.is_alive()
    assert result == [0]
    assert received == [b'{"op":"query","id":"q1"}\n', b'']
    assert [json.loads(line)['type'] for line in output.getvalue().splitlines()] == ['ready', 'result', 'bye']
    # The listening owner remains alive after the desktop disconnects.
    probe = socket.socket(socket.AF_UNIX)
    probe.connect(str(bridge_socket.socket_path(layout)))
    probe.close()
    server.close()


def test_registered_owner_without_socket_reports_error(tmp_path):
    output = io.StringIO()
    assert relay(SimpleNamespace(root=tmp_path), None, output, timeout_s=0) == 1
    assert json.loads(output.getvalue())['kind'] == 'locked'
