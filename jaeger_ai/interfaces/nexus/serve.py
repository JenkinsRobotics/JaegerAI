"""The NexusUI app's server: the screen (built from web/), its config, the agent routes and the shell routes.

Copied from Omni's UI server (jaeger-module-omni, jaeger_omni_v2/ui/serve.py) and made Jaeger AI's own: the agent is
the Gateway (gateway.Bridge), and /shell/* gives the screen what the Swift app's menus and bridge give the WebUI.

GET  /ui/config, /health, /agent/events (a stream), /shell/status, /shell/pending (a deep link waiting to be opened)
POST /agent/text, /agent/interrupt, /agent/new, /agent/audio ({pcm}: 16 kHz 16-bit mono, base64, one clip),
     /shell/action ({name, arg}), /shell/open ({link}: a jaeger:// deep link)

Every POST must carry X-Jaeger and come to a loopback Host: no other web page can drive the agent or the Mac.
"""
from __future__ import annotations

import base64
import io
import json
import os
import queue
import subprocess
import threading
import urllib.error
import urllib.request
import wave
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from . import shell

SCREEN = Path(os.environ.get('JAEGER_NEXUS_SCREEN') or Path.home() / '.cache/jaeger/nexus-ui/dist')   # outside the repo (Golden Rule 1)
KEEP = 15   # seconds between keep-alives on the event stream


def wav(pcm: bytes, rate: int = 16000) -> bytes:
    out = io.BytesIO()
    with wave.open(out, 'wb') as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate); w.writeframes(pcm)
    return out.getvalue()


class Screen:
    def __init__(self, bridge, actions: shell.Actions, config: dict, port: int = 0):
        self.bridge, self.actions, self.config = bridge, actions, config
        self.pending: dict | None = None   # NotificationDestination's one-slot mailbox
        self.http = ThreadingHTTPServer(('127.0.0.1', port), self._handler())
        self.http.daemon_threads = True

    @property
    def url(self):
        return f'http://127.0.0.1:{self.http.server_port}/'

    def start(self):
        threading.Thread(target=self.http.serve_forever, daemon=True).start()
        return self

    def stop(self):
        self.http.shutdown(); self.http.server_close()

    def open_link(self, link: str) -> dict:
        dest = shell.deep_link(link)
        if dest is None:
            raise ValueError('not a Jaeger link')
        self.pending = dest
        self.actions.run('window.show')
        return dest

    def health(self):
        b = self.bridge
        model = (b.report.get('agent') or {}).get('model')
        v = b.voice
        part = lambda k: (lambda r: f"{r.get('module')} {r.get('version')} · {r.get('model')} ({r.get('compute')})" if r else None)((v.report or {}).get(k) if v else None)
        return {'ready': bool(b.ready), 'brain': f"Jaeger Gateway{f' · {model}' if model else ''}" if b.ready else 'Connecting to the Gateway…',
                'voice': part('voice') or (v.why if v else None), 'hearing': part('hearing') or 'Gateway /v1/droid/transcribe',
                'why': b.why, 'session': b.session}

    def transcribe(self, pcm_b64: str) -> str:
        """Hearing is never rebuilt here: Jaeger Agent's Whisper (voice worker) when it is up, else the Gateway's
        /v1/droid/transcribe."""
        v = self.bridge.voice
        if v is not None and v.ready:
            return v.hear(pcm_b64).strip()
        gw = self.bridge.gw
        req = gw._req('POST', '/v1/droid/transcribe')
        req.data = wav(base64.b64decode(pcm_b64))
        req.add_header('Content-Type', 'audio/wav')
        try:
            with urllib.request.urlopen(req, timeout=60) as r:  # noqa: S310 (loopback)
                return str(json.loads(r.read()).get('transcript') or '').strip()
        except urllib.error.HTTPError as e:
            raise RuntimeError((json.loads(e.read() or b'{}') or {}).get('error') or f'hearing failed ({e.code})') from e

    def _handler(self):
        screen = self

        class Handler(SimpleHTTPRequestHandler):
            def __init__(self, *a, **k): super().__init__(*a, directory=str(SCREEN), **k)
            def log_message(self, *a): pass

            def end_headers(self):   # the page is always fetched fresh; its hashed assets may cache
                if self.path.split('?')[0] in ('/', '/index.html'): self.send_header('Cache-Control', 'no-cache')
                super().end_headers()

            def _json(self, data, code=200):
                body = json.dumps(data).encode()
                self.send_response(code); self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(body))); self.end_headers(); self.wfile.write(body)

            def do_GET(self):
                path = urlparse(self.path).path
                if path == '/ui/config': return self._json(screen.config)
                if path == '/health': return self._json(screen.health())
                if path == '/agent/events': return self._events()
                if path == '/shell/status': return self._json(screen.actions.status())
                if path == '/shell/pending':
                    p, screen.pending = screen.pending, None
                    return self._json({'destination': p})
                if not (SCREEN / 'index.html').is_file():
                    return self._json({'error': f'The screen is not built yet: {SCREEN}'}, 503)
                super().do_GET()

            def _events(self):
                b = screen.bridge
                q = b.listen()
                self.send_response(200); self.send_header('Content-Type', 'text/event-stream')
                self.send_header('Cache-Control', 'no-store'); self.end_headers()
                try:
                    while True:
                        try: e = q.get(timeout=KEEP)
                        except queue.Empty: self.wfile.write(b': keep\n\n'); self.wfile.flush(); continue
                        if e is None: break
                        self.wfile.write(b'data: ' + json.dumps(e).encode() + b'\n\n'); self.wfile.flush()
                except OSError:
                    pass
                finally:
                    b.unlisten(q)
                self.close_connection = True

            def do_POST(self):
                path = urlparse(self.path).path
                host = (self.headers.get('Host') or '').rsplit(':', 1)[0]
                if not self.headers.get('X-Jaeger') or host not in ('127.0.0.1', 'localhost'):
                    return self._json({'error': "Only this app's own screen can do that"}, 403)
                try: body = json.loads(self.rfile.read(int(self.headers.get('Content-Length') or 0)) or b'{}')
                except ValueError: return self._json({'error': 'Not JSON'}, 400)
                try:
                    if path == '/agent/text': screen.bridge.send({'op': 'text', 'text': str(body.get('text', ''))[:4000]})
                    elif path == '/agent/interrupt': screen.bridge.send({'op': 'interrupt'})
                    elif path == '/agent/new': screen.bridge.send({'op': 'new'})
                    elif path == '/agent/audio':
                        heard = screen.transcribe(str(body.get('pcm', '')))
                        if heard: screen.bridge.send({'op': 'text', 'text': heard})
                        return self._json({'heard': heard})
                    elif path == '/shell/action': return self._json({'result': screen.actions.run(str(body.get('name')), body.get('arg'))})
                    elif path == '/shell/open': return self._json({'destination': screen.open_link(str(body.get('link', '')))})
                    else: return self._json({'error': 'No such route'}, 404)
                except ValueError as e:
                    return self._json({'error': str(e)}, 400)
                except (RuntimeError, OSError, subprocess.SubprocessError) as e:
                    return self._json({'error': str(e)}, 503)
                self._json({})

        return Handler

