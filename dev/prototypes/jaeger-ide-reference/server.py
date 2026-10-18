"""Serve the real Jaeger IDE webview with a local, in-memory host mock."""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import re
import mimetypes


ROOT = Path(__file__).resolve().parents[3]
MEDIA = ROOT / "jaeger_ai/interfaces/ide/media"
HERE = Path(__file__).resolve().parent


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path in ("/", "/index.html"):
            html = (MEDIA / "index.html").read_text()
            html = re.sub(r'<meta http-equiv="Content-Security-Policy"[^>]*>', "", html)
            names = {
                "CSS": "view.css", "MOTION": "motion.css", "SLASH": "slash-commands.js",
                "LOGO": "jaeger.svg", "FRAME_QUEUE": "frame-queue.js", "TIMELINE": "timeline.js",
                "KEYED_RENDERER": "keyed-renderer.js", "PRESENTATION": "presentation.js",
                "DURATION": "turn-duration.js", "MARKDOWN": "markdown.js", "JS": "view.js",
                "SMD": "vendor/smd.min.js", "CSP": "", "NONCE": "jaeger-preview",
            }
            for key, value in names.items():
                html = html.replace("{{" + key + "}}", "/media/" + value if value and key not in ("CSP", "NONCE") else value)
            html = re.sub(
                r'<script type="module" nonce="jaeger-preview">.*?</script>',
                '<script>window.smd = null;</script>', html, flags=re.S,
            )
            html = html.replace(
                '<script nonce="jaeger-preview" src="/media/view.js"></script>',
                '<script src="/harness.js"></script><script src="/media/view.js"></script>',
            )
            return self.respond(html.encode(), "text/html; charset=utf-8")
        if self.path == "/harness.js":
            return self.respond((HERE / "harness.js").read_bytes(), "text/javascript; charset=utf-8")
        if self.path.startswith("/media/"):
            target = (MEDIA / self.path.removeprefix("/media/")).resolve()
            if target.is_relative_to(MEDIA.resolve()) and target.is_file():
                return self.respond(target.read_bytes(), mimetypes.guess_type(target.name)[0] or "application/octet-stream")
        self.send_error(404)

    def respond(self, body: bytes, content_type: str):
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format, *_args):
        pass


if __name__ == "__main__":
    server = ThreadingHTTPServer(("127.0.0.1", 18731), Handler)
    print("Jaeger IDE reference: http://127.0.0.1:18731", flush=True)
    server.serve_forever()
