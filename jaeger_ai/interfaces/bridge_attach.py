"""Relay a desktop's stdio to the resident bridge without owning its lifetime."""

from __future__ import annotations

import json
import os
import selectors
import time

from jaeger_ai.core.runtime import bridge_socket


def relay(layout, source, output, *, timeout_s: float = 15.0) -> int:
    """Wait for the registered owner to publish its socket, then attach.

    A desktop quit closes only this client. The managed bridge and other
    attached interfaces keep running. No second agent is booted.
    """
    path = bridge_socket.socket_path(layout)
    deadline = time.monotonic() + timeout_s
    conn = None
    while path is not None:
        conn = bridge_socket.try_connect(path, timeout_s=0.4)
        if conn is not None or time.monotonic() >= deadline:
            break
        time.sleep(0.1)
    if conn is None:
        output.write(json.dumps({"type": "fatal", "kind": "locked",
                                 "error": "The running bridge did not publish its connection socket."}) + "\n")
        output.flush()
        return 1
    pending = b""
    # Socket chunks can split UTF-8 code points; forward complete JSON lines.
    received = b""
    with conn, selectors.DefaultSelector() as selector:
        selector.register(source, selectors.EVENT_READ, "input")
        selector.register(conn, selectors.EVENT_READ, "bridge")
        while True:
            for key, _ in selector.select():
                data = os.read(key.fd, 65536)
                if not data:
                    return 0 if key.data == "input" else 1
                if key.data == "bridge":
                    received += data
                    while b"\n" in received:
                        line, received = received.split(b"\n", 1)
                        output.write(line.decode("utf-8") + "\n")
                        output.flush()
                    continue
                pending += data
                while b"\n" in pending:
                    line, pending = pending.split(b"\n", 1)
                    try:
                        request = json.loads(line)
                    except (ValueError, UnicodeDecodeError):
                        continue
                    if isinstance(request, dict) and request.get("op") == "quit":
                        output.write('{"type":"bye"}\n')
                        output.flush()
                        return 0
                    conn.sendall(line + b"\n")
