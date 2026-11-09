"""Same-origin browser transport, behind the WebUI's existing sign-in gate."""
import http.client
import re
import select
from urllib.parse import urlparse

PATH = re.compile(r"^/v1/sessions/[^/]+/browser/(action|viewer|cast)$")


def route(handler, parsed, method):
    match = PATH.fullmatch(parsed.path)
    if not match:
        return False
    from api.helpers import j, mark_request_body_consumed
    kind = match[1]
    if method != ("POST" if kind == "action" else "GET"):
        j(handler, {"error": "Method not allowed"}, status=405)
        return True
    origin = handler.headers.get("Origin")
    if origin and urlparse(origin).netloc != handler.headers.get("Host"):
        j(handler, {"error": "Same-origin browser access required"}, status=403)
        return True
    if kind == "cast" and not origin:
        j(handler, {"error": "Browser origin required"}, status=403)
        return True
    from api.routes import _jaeger_gateway_bases
    from jaeger_ai.core.gateway.caller_auth import client_headers
    base = urlparse(_jaeger_gateway_bases()[0])
    conn = http.client.HTTPConnection(base.hostname, base.port, timeout=75)
    headers = client_headers("webui")
    body = None
    if method == "POST":
        length = int(handler.headers.get("Content-Length", "0"))
        if not 0 < length <= 262144:
            j(handler, {"error": "Browser request too large or empty"}, status=413)
            return True
        body = handler.rfile.read(length)
        mark_request_body_consumed(handler)
        headers["Content-Type"] = "application/json"
    if kind == "cast":
        for key in ("Upgrade", "Connection", "Sec-WebSocket-Key", "Sec-WebSocket-Version", "Sec-WebSocket-Protocol"):
            if handler.headers.get(key):
                headers[key] = handler.headers[key]
    try:
        conn.request(method, parsed.path + ("?" + parsed.query if parsed.query else ""), body, headers)
        if kind == "cast":
            # Read the handshake without a buffered file: otherwise a first frame
            # can be swallowed into HTTPResponse's buffer before select sees it.
            raw = bytearray()
            while not raw.endswith(b"\r\n\r\n"):
                chunk = conn.sock.recv(1)
                if not chunk or len(raw) >= 32768:
                    raise OSError("Invalid browser upgrade handshake")
                raw.extend(chunk)
            lines = bytes(raw).decode("iso-8859-1").split("\r\n")
            status = int(lines[0].split(" ")[1])
            if status != 101:
                j(handler, {"error": "Browser stream unavailable"}, status=status)
                return True
            handler.send_response(101)
            for line in lines[1:]:
                key, separator, value = line.partition(":")
                if separator and key.lower() in {"upgrade", "connection", "sec-websocket-accept", "sec-websocket-protocol"}:
                    handler.send_header(key, value.strip())
            handler.end_headers()
            handler.wfile.flush()
            handler.close_connection = True
            conn.sock.settimeout(None)
            handler.connection.settimeout(None)
            while True:
                readable, _, _ = select.select([handler.connection, conn.sock], [], [], 30)
                for source in readable:
                    data = source.recv(65536)
                    if not data:
                        return True
                    (handler.connection if source is conn.sock else conn.sock).sendall(data)
        response = conn.getresponse()
        handler.send_response(response.status)
        payload = response.read()
        handler.send_header("Content-Type", response.getheader("Content-Type", "application/json"))
        handler.send_header("Content-Length", str(len(payload)))
        handler.send_header("Cache-Control", "no-store")
        handler.end_headers()
        handler.wfile.write(payload)
    finally:
        conn.close()
    return True
