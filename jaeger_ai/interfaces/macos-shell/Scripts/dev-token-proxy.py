#!/usr/bin/env python3
"""Dev-only loopback proxy for the isolated test stack.

It plays the role the WebUI plays in production: the page talks to its own origin, and this proxy
adds the dev stack's OWN `webui` caller token (created in the isolated JAEGER_CALLER_TOKEN_DIR,
never the real Keychain tokens) before forwarding /v1, /api, /health and /version to the test gateway.
Loopback only. Refuses token dirs under ~/.jaeger. Never prints the token value. Streams SSE through.
"""
import argparse
import http.client
import http.server
import os
import secrets
import sys
import urllib.parse
from pathlib import Path

HOP = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailers",
       "transfer-encoding", "upgrade", "host", "authorization", "content-length"}


def ensure_token(directory: str) -> str:
    home = Path.home().resolve()
    d = Path(directory).expanduser().resolve()
    if d == home / ".jaeger" or (home / ".jaeger") in d.parents:
        sys.exit("[dev-token-proxy] refusing a token dir under ~/.jaeger")
    d.mkdir(parents=True, exist_ok=True)
    os.chmod(d, 0o700)
    path = d / "webui.token"
    if not path.exists():
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.write(fd, secrets.token_urlsafe(32).encode())
        os.close(fd)
        print("[dev-token-proxy] created an isolated webui token (value not shown)", flush=True)
    os.chmod(path, 0o600)
    return path.read_text(encoding="utf-8").strip()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--target", required=True, help="http://127.0.0.1:<port> (loopback only)")
    ap.add_argument("--token-dir", required=True)
    args = ap.parse_args()
    target = urllib.parse.urlsplit(args.target)
    if target.scheme != "http" or target.hostname != "127.0.0.1" or not target.port:
        sys.exit("[dev-token-proxy] target must be http://127.0.0.1:<port>")
    token = ensure_token(args.token_dir)

    class Handler(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def _proxy(self) -> None:
            path = self.path
            if not (path.startswith("/v1/") or path.startswith("/api/") or path.split("?")[0] in ("/health", "/version", "/v1")):
                self.send_error(404)
                return
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length) if length else None
            headers = {k: v for k, v in self.headers.items() if k.lower() not in HOP}
            headers["Authorization"] = "Bearer " + token
            conn = http.client.HTTPConnection(target.hostname, target.port, timeout=900)
            try:
                conn.request(self.command, path, body=body, headers=headers)
                resp = conn.getresponse()
            except OSError:
                self.send_error(502, "test gateway unreachable")
                return
            self.send_response(resp.status, resp.reason)
            for k, v in resp.getheaders():
                if k.lower() not in HOP:
                    self.send_header(k, v)
            self.send_header("Transfer-Encoding", "chunked")
            self.send_header("Connection", "close")
            self.end_headers()
            try:
                while True:
                    chunk = resp.read1(65536)
                    if not chunk:
                        break
                    self.wfile.write(b"%x\r\n%s\r\n" % (len(chunk), chunk))
                    self.wfile.flush()
                self.wfile.write(b"0\r\n\r\n")
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass
            finally:
                conn.close()
                self.close_connection = True

        do_GET = do_POST = do_PATCH = do_PUT = do_DELETE = _proxy

        def log_message(self, fmt: str, *a: object) -> None:
            sys.stderr.write(f"[dev-token-proxy] {self.command} {self.path.split('?')[0]}\n")

    server = http.server.ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    server.daemon_threads = True
    print(f"[dev-token-proxy] 127.0.0.1:{args.port} -> {args.target}", flush=True)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
