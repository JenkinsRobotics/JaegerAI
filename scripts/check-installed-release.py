#!/usr/bin/env python3
"""Check installed wheel origins, packaged UI HTTP bytes and Gateway restart persistence.

Run with the candidate environment's Python from outside its source checkout.
Uses temporary state, per-caller credentials and owned ephemeral listeners.
No model request is made; this does not certify a cloud provider or native UI.
"""
from __future__ import annotations
import argparse
import hashlib
import importlib
import importlib.metadata
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse
from urllib.request import Request, urlopen


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--version', required=True)
    args = parser.parse_args()
    origins = {}
    for name in ('jaeger_ai', 'jaeger_agent', 'jaeger_os', 'jaeger_kokoro_tts', 'jaeger_whisper_stt'):
        spec = importlib.util.find_spec(name)
        if spec is None or spec.origin is None:
            raise RuntimeError(f'Missing installed package {name}')
        path = Path(spec.origin).resolve()
        if Path(sys.prefix).resolve() not in path.parents:
            raise RuntimeError(f'{name} imported from {path}, outside candidate environment')
        origins[name] = str(path)
    actual = importlib.metadata.version('jaeger-ai')
    if actual != args.version:
        raise RuntimeError(f'Installed version {actual} differs from candidate {args.version}')
    with tempfile.TemporaryDirectory(prefix='jaeger-installed-smoke-') as temporary:
        state = Path(temporary)
        env = {k: v for k, v in os.environ.items()
               if not k.startswith(('JAEGER_', 'HERMES_', 'PYTHONPATH'))
               and not k.endswith(('_API_KEY', '_TOKEN', '_SECRET', '_PASSWORD'))}
        env.update(JAEGER_HOME=str(state), JAEGER_STATE_DIR=str(state),
                   JAEGER_CALLER_TOKEN_DIR=str(state / 'tokens'), JAEGER_NO_ATTACH='1',
                   JAEGER_TEST_HEADLESS='1', JAEGER_BACKGROUND_PRODUCERS='0',
                   PYTHONDONTWRITEBYTECODE='1', PYTHONPYCACHEPREFIX=str(state / 'pycache'))
        for key in list(os.environ):
            if key.startswith(('JAEGER_', 'HERMES_')): os.environ.pop(key)
        os.environ.update({k: v for k, v in env.items() if k.startswith(('JAEGER_', 'HERMES_'))})
        from jaeger_ai.core.gateway.caller_auth import CALLERS
        from jaeger_ai.features.webui.api import ui_shell
        tokens = state / 'tokens'; tokens.mkdir(mode=0o700)
        for caller in CALLERS:
            p = tokens / f'{caller}.token'; p.write_text(secrets.token_urlsafe(32)); p.chmod(0o600)
        ui = ui_shell.dist_root()
        if ui is None or ui.parent.name != 'assets' or ui.name != 'shared-ui':
            raise RuntimeError('The installed package did not resolve its bundled production UI')
        build = json.loads((ui / 'build.json').read_text())
        if build.get('mock') is not False:
            raise RuntimeError('Mock UI in release')
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                if not ui_shell.serve(self, urlparse(self.path)):
                    self.send_error(404)
            def log_message(self, *_): pass
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        try:
            with urlopen(f'http://127.0.0.1:{server.server_port}/', timeout=3) as response:
                assert response.status == 200 and b'<html' in response.read().lower()
            js = next((ui / 'assets').glob('*.js'))
            with urlopen(f'http://127.0.0.1:{server.server_port}/assets/{js.name}', timeout=3) as response:
                assert hashlib.sha256(response.read()).digest() == hashlib.sha256(js.read_bytes()).digest()
        finally:
            server.shutdown(); server.server_close(); thread.join(timeout=5)
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', 0)); port = probe.getsockname()[1]
        env['JAEGER_GATEWAY_PORT'] = str(port)
        base = f'http://127.0.0.1:{port}'
        headers = {'Content-Type': 'application/json', 'Authorization': 'Bearer ' + (tokens / 'cli.token').read_text()}
        def request(path, body=None):
            req = Request(base + path, data=None if body is None else json.dumps(body).encode(), headers=headers)
            with urlopen(req, timeout=3) as response: return json.load(response)
        for iteration in range(2):
            with (state / f'gateway-{iteration}.log').open('w') as log:
                child = subprocess.Popen([sys.executable, '-B', '-m', 'jaeger_ai.core.gateway.server', '--host', '127.0.0.1', '--port', str(port)],
                                         cwd=state, env=env, stdout=log, stderr=subprocess.STDOUT)
                try:
                    deadline = time.monotonic() + 30
                    while True:
                        if child.poll() is not None:
                            raise RuntimeError((state / f'gateway-{iteration}.log').read_text())
                        try:
                            diagnostics = request('/v1/runtime/diagnostics')
                            if diagnostics['process_id'] != child.pid:
                                raise RuntimeError('Listener does not belong to the started candidate process')
                            break
                        except OSError:
                            if time.monotonic() >= deadline: raise
                            time.sleep(0.1)
                    assert request('/version')['version'] == args.version
                    if iteration == 0:
                        request('/v1/sessions', {'session_id': 'installed-release-smoke', 'title': 'Installed release smoke'})
                    session = request('/v1/sessions/installed-release-smoke')
                    assert session['session_id'] == 'installed-release-smoke'
                finally:
                    if child.poll() is None:
                        child.terminate()
                        try: child.wait(timeout=5)
                        except subprocess.TimeoutExpired: child.kill(); child.wait(timeout=5)
    print(json.dumps({'version': actual, 'origins': origins, 'packaged_ui_http': 'passed',
                      'gateway_restart_persistence': 'passed', 'provider': 'not exercised'}, indent=2))


if __name__ == '__main__': main()
