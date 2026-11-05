#!/usr/bin/env python3
"""Own an isolated foreground test stack. Stop via its private control socket only."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import secrets
import signal
import socket
import subprocess
import sys
import tempfile
import time
from urllib.request import Request, urlopen

REPO = Path(__file__).resolve().parents[1]


def state_path(value: str | None) -> Path:
    path = Path(value).expanduser().resolve() if value else Path(tempfile.mkdtemp(prefix='jaeger-stack-'))
    for protected in (REPO, Path.home() / '.jaeger', Path.home()):
        protected = protected.resolve()
        if path == protected or protected in path.parents:
            raise ValueError(f'Refusing protected test state: {path}')
    return path


def free_port(excluded: set[int]) -> int:
    while True:
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', 0))
            port = probe.getsockname()[1]
        if port not in excluded:
            return port


def run(state: Path, ui_dist: Path) -> None:
    if state.exists() and any(state.iterdir()):
        raise ValueError('Test state must be new and empty; existing state is never removed')
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not (ui_dist / 'index.html').is_file():
        raise ValueError('--ui-dist must contain a production UI build')
    nonce = secrets.token_urlsafe(32)
    token_dir = state / 'tokens'; token_dir.mkdir(mode=0o700)
    sys.path[:0] = [str(REPO), str(REPO / 'packages/jaeger-os'), str(REPO / 'packages/jaeger-agent')]
    from jaeger_ai.core.gateway.caller_auth import CALLERS
    from jaeger_ai.contract.ports import GATEWAY_PORT, WEBUI_PORT
    for caller in CALLERS:
        token = token_dir / f'{caller}.token'
        token.write_text(secrets.token_urlsafe(32)); token.chmod(0o600)
    gateway_port = free_port({GATEWAY_PORT, WEBUI_PORT})
    webui_port = free_port({GATEWAY_PORT, WEBUI_PORT, gateway_port})
    gateway_url, webui_url = f'http://127.0.0.1:{gateway_port}', f'http://127.0.0.1:{webui_port}'
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(('JAEGER_', 'HERMES_')) and not k.endswith(('_TOKEN', '_API_KEY', '_SECRET', '_PASSWORD'))}
    env.update(PYTHONDONTWRITEBYTECODE='1', PYTHONPYCACHEPREFIX=str(state / 'pycache'),
               PYTHONPATH=os.pathsep.join([str(REPO)] + [str(REPO / 'packages' / p)
                   for p in ('jaeger-agent', 'jaeger-os', 'jaeger-kokoro-tts', 'jaeger-whisper-stt')]),
               JAEGER_STATE_DIR=str(state), JAEGER_HOME=str(state),
               JAEGER_CALLER_TOKEN_DIR=str(token_dir), JAEGER_NO_ATTACH='1', JAEGER_TEST_HEADLESS='1',
               JAEGER_BACKGROUND_PRODUCERS='0', JAEGER_GATEWAY_HOST='127.0.0.1',
               JAEGER_GATEWAY_PORT=str(gateway_port), JAEGER_GATEWAY_URL=gateway_url,
               JAEGER_WEBUI_UI_DIST=str(ui_dist), JAEGER_OLLAMA_URL='http://127.0.0.1:9',
               HERMES_HOME=str(state / 'webui-agent'), HERMES_WEBUI_STATE_DIR=str(state / 'webui'),
               HERMES_WEBUI_DEFAULT_WORKSPACE=str(state / 'workspace'),
               HERMES_WEBUI_HOST='127.0.0.1', HERMES_WEBUI_PORT=str(webui_port),
               HERMES_WEBUI_PASSWORD=secrets.token_urlsafe(32), HERMES_WEBUI_TEST_NETWORK_BLOCK='1')
    children = []
    logs = []
    stopping = False
    def stop(*_):
        nonlocal stopping
        stopping = True
    signal.signal(signal.SIGTERM, stop); signal.signal(signal.SIGINT, stop)
    with socket.socket(socket.AF_UNIX) as control:
        control.bind(str(state / 'control.sock')); control.listen(1); control.settimeout(0.2)
        owner = state / 'owner.json'
        owner.write_text(json.dumps({'nonce': nonce, 'supervisor_pid': os.getpid()})); owner.chmod(0o600)
        try:
            for name, command, cwd in (
                ('gateway', [sys.executable, '-B', '-m', 'jaeger_ai.core.gateway.server', '--host', '127.0.0.1', '--port', str(gateway_port)], state),
                ('webui', [sys.executable, '-B', str(REPO / 'jaeger_ai/features/webui/server.py')], REPO / 'jaeger_ai/features/webui')):
                log = (state / f'{name}.log').open('w'); logs.append(log)
                children.append(subprocess.Popen(command, cwd=cwd, env=env, stdout=log, stderr=subprocess.STDOUT))
            deadline = time.monotonic() + 60
            ready = False
            while not stopping:
                if any(child.poll() is not None for child in children):
                    raise RuntimeError(f'Test child exited; inspect {state}/*.log')
                if not ready:
                    try:
                        headers = {'Authorization': 'Bearer ' + (token_dir / 'cli.token').read_text()}
                        with urlopen(Request(gateway_url + '/v1/runtime/diagnostics', headers=headers), timeout=1) as response:
                            identity = json.load(response)
                        if identity.get('process_id') != children[0].pid:
                            raise RuntimeError('Gateway endpoint is not owned by this test child')
                        with urlopen(webui_url + '/', timeout=1) as response:
                            if response.status != 200:
                                raise RuntimeError('WebUI did not return HTTP 200')
                        ready = True
                        result = {'state': str(state), 'gateway_url': gateway_url, 'webui_url': webui_url,
                                  'gateway_pid': children[0].pid, 'webui_pid': children[1].pid}
                        (state / 'ready.json').write_text(json.dumps(result))
                        print(json.dumps(result), flush=True)
                        print(f'Stop: JAEGER_STATE_DIR={state} ./scripts/stop-test-env.sh', flush=True)
                    except (OSError, ValueError):
                        if time.monotonic() > deadline:
                            raise TimeoutError(f'Stack readiness timed out; inspect {state}')
                try:
                    connection, _ = control.accept()
                except socket.timeout:
                    continue
                with connection:
                    connection.settimeout(1)
                    if secrets.compare_digest(connection.recv(4096).decode().strip(), nonce):
                        connection.sendall(b'stopping\n'); stopping = True
        finally:
            for child in reversed(children):
                if child.poll() is None:
                    child.terminate()
                    try: child.wait(timeout=5)
                    except subprocess.TimeoutExpired: child.kill(); child.wait(timeout=5)
            for log in logs: log.close()
            (state / 'control.sock').unlink(missing_ok=True)
            (state / 'ready.json').unlink(missing_ok=True)
            # Preserve all state and logs for diagnosis. Never remove caller paths.


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['start', 'stop'])
    parser.add_argument('--state-dir', default=os.environ.get('JAEGER_STATE_DIR'))
    parser.add_argument('--ui-dist', default=os.environ.get('JAEGER_WEBUI_UI_DIST'))
    args = parser.parse_args()
    if args.action == 'stop':
        if not args.state_dir:
            parser.error('stop requires --state-dir or JAEGER_STATE_DIR from the started stack')
        state = state_path(args.state_dir)
        owner = json.loads((state / 'owner.json').read_text())
        with socket.socket(socket.AF_UNIX) as connection:
            connection.settimeout(5); connection.connect(str(state / 'control.sock'))
            connection.sendall(owner['nonce'].encode())
            if connection.recv(100) != b'stopping\n':
                raise RuntimeError('Test supervisor did not confirm shutdown')
    else:
        if not args.ui_dist:
            parser.error('start requires --ui-dist or JAEGER_WEBUI_UI_DIST; build UI externally first')
        run(state_path(args.state_dir), Path(args.ui_dist).expanduser().resolve())


if __name__ == '__main__':
    main()
