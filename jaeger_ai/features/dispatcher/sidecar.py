"""Hermes token-v1 extension sidecar for Jaeger's native Dispatcher panels."""
import hmac
import json
import os
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

EXTENSION_ID = 'jaeger-dispatcher'
ROUTES = {'/', '/skills', '/memory', '/models', '/bind'}


def token_file():
    override = os.environ.get('HERMES_EXT_SIDECAR_TOKEN_FILE')
    if override:
        return Path(override)
    home = Path(os.environ.get('HERMES_HOME', str(Path.home() / '.hermes')))
    state = Path(os.environ.get('HERMES_WEBUI_STATE_DIR', str(home / 'webui')))
    return state / 'sidecar-auth' / (EXTENSION_ID + '.token')


def backend():
    import yaml
    home = Path(os.environ.get('HERMES_HOME', str(Path.home() / '.hermes')))
    config = yaml.safe_load((home / 'profiles/jaeger/config.yaml').read_text()) or {}
    url = str(config.get('webui_gateway_base_url') or '').rstrip('/')
    key = str(config.get('webui_gateway_api_key') or '')
    if not url or not key:
        raise ValueError('Jaeger profile gateway is not configured')
    return url, key


class Handler(BaseHTTPRequestHandler):
    def reply(self, status, value):
        payload = json.dumps(value).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(payload)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(payload)

    def handle_request(self, method):
        if method == 'GET' and self.path == '/health':
            return self.reply(200, {'ok': True, 'owner': 'jaeger'})
        try:
            expected = token_file().read_text().strip()
        except OSError:
            return self.reply(503, {'error': 'Enable authenticated extension proxy consent in Hermes WebUI settings'})
        if not expected or not hmac.compare_digest(self.headers.get('X-Hermes-Sidecar-Token', ''), expected):
            return self.reply(401, {'error': 'Extension authentication required'})
        if self.path not in ROUTES or (method == 'POST') != (self.path == '/bind'):
            return self.reply(404, {'error': 'Route not available'})
        try:
            body = None
            if method == 'POST':
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 4096 or self.headers.get('Transfer-Encoding'):
                    raise ValueError('Invalid request body size')
                body = self.rfile.read(length)
                value = json.loads(body)
                if not isinstance(value, dict) or set(value) != {'session_id'}:
                    raise ValueError('Expected a session identity')
            base, key = backend()
            path = '/v1/dispatcher' + (self.path if self.path != '/' else '')
            request = Request(base + path, data=body, method=method,
                              headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'})
            with urlopen(request, timeout=15) as response:
                return self.reply(response.status, json.load(response))
        except HTTPError as exc:
            return self.reply(exc.code, {'error': 'Native Jaeger request failed', 'status': exc.code})
        except ValueError as exc:
            return self.reply(400, {'error': str(exc)})
        except (OSError, URLError):
            return self.reply(503, {'error': 'Jaeger adapter is unavailable'})

    def do_GET(self):
        self.handle_request('GET')

    def do_POST(self):
        self.handle_request('POST')

    def setup(self):
        super().setup()
        self.connection.settimeout(15)


def main():
    ThreadingHTTPServer(('127.0.0.1', 8646), Handler).serve_forever()


run_server = main


if __name__ == '__main__':
    main()
