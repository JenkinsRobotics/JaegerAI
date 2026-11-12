"""Legacy fallbacks must not bypass native-route authentication or invent Stop."""
from contextlib import closing, contextmanager
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
import json
import threading
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from jaeger_ai.core.frameworks.ingress import ProfileHTTPServer












def test_connection_capacity_is_bounded_and_recovers_after_disconnect():
    import socket
    from http.server import BaseHTTPRequestHandler
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
    server = ProfileHTTPServer(('127.0.0.1', 0), Handler, max_connections=1)
    thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=.01), daemon=True)
    thread.start()
    # Hold the slot explicitly: verifies rejection without constructing a
    # request handler or parsing attacker-controlled input.
    assert server._connections.acquire(blocking=False)
    try:
        with socket.create_connection(server.server_address, timeout=2) as connection:
            response = connection.recv(4096)
            assert b'503 Service Unavailable' in response
            assert b'adapter_capacity' in response
        server._connections.release()
        with socket.create_connection(server.server_address, timeout=2) as connection:
            connection.sendall(b'GET / HTTP/1.0\r\nHost: localhost\r\n\r\n')
            assert b'501 Unsupported method' in connection.recv(4096)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(2)


