"""Local server lifecycle for the menu bar. No running gateway required."""
from __future__ import annotations

import concurrent.futures
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import time
from urllib.error import HTTPError
from urllib.request import urlopen

# Fixed service identities: never accept an arbitrary launchctl label or command.
SERVICES = {
    'container': ('Container Daemon', None, None, None),
    'ollama': ('Ollama', 'com.jenkinsrobotics.ares-ollama', 11434, '/api/tags'),
    'gateway': ('Gateway', 'com.jenkinsrobotics.jaeger-gateway', 8810, '/health'),
    'agent': ('Jaeger Agent', 'com.jenkinsrobotics.jaeger-bridge', None, None),
    'hermes': ('Hermes', 'com.jenkinsrobotics.hermes-native-api', None, None),
    'openclaw': ('OpenClaw', None, 18789, None),
    'runner': ('Chat Runner', 'com.jenkinsrobotics.jaeger-hermes-webui-adapter', 8791, '/health'),
    'webui': ('Web UI', 'com.jenkinsrobotics.jaeger-webui', 8790, '/health'),
}


class ServerControls:
    def __init__(self, home=None, execute=None):
        self.home = Path(home or Path.home())
        self.execute = execute or self._execute
        self.domain = f'gui/{os.getuid()}'

    @staticmethod
    def _execute(args):
        return subprocess.run(args, capture_output=True, text=True, timeout=25, check=False)

    @staticmethod
    def container_cli():
        return shutil.which('container') or '/opt/homebrew/bin/container'

    def plist(self, service):
        from jaeger_ai.core.instance.instance import operator_state_root
        label = SERVICES[service][1]
        managed = operator_state_root() / 'launchd' / f'{label}.plist'
        if managed.is_file():
            return managed
        return self.home / 'Library/LaunchAgents' / (SERVICES[service][1] + '.plist')

    def loaded(self, label):
        return self.execute(['/bin/launchctl', 'print', f'{self.domain}/{label}']).returncode == 0

    def container(self, service):
        from jaeger_ai.core.runtime.agent_workspaces import container_name
        return container_name(service)

    def ready(self, service):
        _, _, port, path = SERVICES[service]
        try:
            if service == 'container':
                cli = self.container_cli()
                res = self.execute([cli, 'system', 'status'])
                return res.returncode == 0 and 'running' in str(res.stdout).lower()
            if service == 'agent':
                from jaeger_ai.features.webui.adapter.bridge_client import jaeger_bridge
                return bool(jaeger_bridge().health().get('ok'))
            if service == 'hermes':
                from jaeger_ai.core.frameworks.hermes_native import connection
                base, _ = connection()
                from urllib.parse import urlsplit
                url = urlsplit(base)
                with socket.create_connection((url.hostname, url.port), timeout=1):
                    return True
            if path:
                try:
                    with urlopen(f'http://127.0.0.1:{port}{path}', timeout=2) as response:
                        return 200 <= int(response.status) < 500
                except HTTPError as exc:
                    # Auth-gated routes still prove the process is serving.
                    return 400 <= int(getattr(exc, "code", 0) or 0) < 500
            with socket.create_connection(('127.0.0.1', port), timeout=1):
                return True
        except Exception:
            return False

    def status_one(self, service):
        name, label, _, _ = SERVICES[service]
        ready = self.ready(service)
        if service == 'container':
            cli = self.container_cli()
            configured = Path(cli).is_file() or bool(shutil.which('container'))
            return {'id': service, 'name': name, 'ready': ready, 'configured': configured,
                    'state': 'Ready' if ready else 'Stopped'}
        configured = label is None or self.plist(service).is_file()
        running = ready or (label is not None and self.loaded(label))
        return {'id': service, 'name': name, 'ready': ready, 'configured': configured,
                'state': 'Ready' if ready else ('Not ready' if running else 'Stopped')}

    def status(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            return list(pool.map(self.status_one, SERVICES))

    def checked(self, args):
        result = self.execute(args)
        if result.returncode:
            raise RuntimeError((result.stderr or result.stdout or 'Service command failed').strip()[-1200:])

    def launch(self, service, action):
        label = SERVICES[service][1]
        if action == 'stop':
            if self.loaded(label):
                self.checked(['/bin/launchctl', 'bootout', f'{self.domain}/{label}'])
            return
        path = self.plist(service)
        if not path.is_file():
            raise RuntimeError(f'{SERVICES[service][0]} is not installed: {path.name}')
        if not self.loaded(label):
            self.checked(['/bin/launchctl', 'bootstrap', self.domain, str(path)])
        else:
            self.checked(['/bin/launchctl', 'kickstart', *(['-k'] if action == 'restart' else []), f'{self.domain}/{label}'])

    def change_one(self, service, action):
        if service == 'container':
            cli = self.container_cli()
            if action == 'stop':
                self.checked([cli, 'system', 'stop'])
            elif action == 'start':
                self.checked([cli, 'system', 'start', '--disable-kernel-install'])
            elif action == 'restart':
                self.execute([cli, 'system', 'stop'])
                self.checked([cli, 'system', 'start', '--disable-kernel-install'])
            return
        if service == 'openclaw':
            cli = self.container_cli()
            name = self.container(service)
            if action in {'stop', 'restart'}:
                # Stopping an already stopped container is a successful no-op.
                result = self.execute([cli, 'inspect', name])
                if result.returncode:
                    raise RuntimeError('Configured container could not be inspected')
                state = json.loads(result.stdout)[0]['status']['state']
                if state == 'running':
                    self.checked([cli, 'stop', name])
            if action in {'start', 'restart'}:
                if not self.ready('container'):
                    self.change_one('container', 'start')
                result = self.execute([cli, 'inspect', name])
                if result.returncode:
                    raise RuntimeError('Configured container is not installed')
                if json.loads(result.stdout)[0]['status']['state'] != 'running':
                    self.checked([cli, 'start', name])
        else:
            self.launch(service, action)

    def change(self, service, action):
        if action == 'reset':
            from jaeger_ai.core.runtime.stack import stack_reset
            res = stack_reset(timeout_s=60.0)
            return {'ok': res.get('ok', False), 'error': res.get('error'), 'services': self.status(), 'details': res}
        if service not in {*SERVICES, 'all'} or action not in {'start', 'stop', 'restart'}:
            raise ValueError('Unknown server or action')
        targets = list(SERVICES) if service == 'all' else [service]
        if action == 'stop':
            targets.reverse()
        errors = []
        for target in targets:
            try:
                self.change_one(target, action)
            except Exception as exc:
                errors.append(f'{SERVICES[target][0]}: {exc}')
        return {'ok': not errors, 'error': '\n'.join(errors) or None, 'services': self.status()}


def main(argv):
    import argparse
    parser = argparse.ArgumentParser(prog='jaeger webui servers')
    parser.add_argument('action', choices=['status', 'start', 'stop', 'restart', 'reset'], nargs='?', default='status')
    parser.add_argument('service', choices=[*SERVICES, 'all'], nargs='?', default='all')
    args = parser.parse_args(argv)
    controls = ServerControls()
    try:
        result = {'ok': True, 'services': controls.status()} if args.action == 'status' else controls.change(args.service, args.action)
    except Exception as exc:
        result = {'ok': False, 'error': str(exc), 'services': []}
    print(json.dumps(result))
    return 0 if result['ok'] else 1
