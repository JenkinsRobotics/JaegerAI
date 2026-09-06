#!/usr/bin/env python3
"""In-container, opt-in NAS probe through existing authenticated host MCP grants.

Targets must be unique probe directories created by the Mac-side operator.
Only two probe text files are written/read. The Mac-side caller cleans them up.
No credentials leave the container; no model or permission changes are made.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import runpy
import time


def validate_path(value):
    if not re.fullmatch(r'/Volumes/(?:Jenkins_Robotics|Personal-Drive)/\.jaeger-mcp-probe-[0-9a-f]{32}', value):
        raise ValueError('Only exact operator-created NAS probe directories are allowed')
    return value


def check(role, directory):
    if role not in {'hermes', 'openclaw'}:
        raise ValueError('Unknown agent role')
    validate_path(directory)
    helper = runpy.run_path(str(Path(__file__).with_name('agent-mac-check.py')))
    request = helper['request']
    if role == 'openclaw':
        config = json.loads(Path('/home/node/.openclaw/openclaw.json').read_text())
        auth = config['mcp']['servers']['ares-system']['headers']['Authorization']
    else:
        auth = ''
        for line in Path('/home/hermeswebui/.hermes/.env').read_text().splitlines():
            name, separator, value = line.partition('=')
            if separator and name.strip() == 'MCP_ARES_HOST_API_KEY':
                auth = 'Bearer ' + value.strip().strip("\"'")
    if not auth:
        raise RuntimeError('Existing host credential is missing')
    url = 'http://192.168.64.1:8813/mcp'
    headers = {'Authorization': auth, 'Host': '127.0.0.1:8813',
               'Content-Type': 'application/json', 'Accept': 'application/json, text/event-stream'}
    _, session = request(url, {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {
        'protocolVersion': '2024-11-05', 'capabilities': {}, 'clientInfo': {'name': 'jaeger-nas-verification', 'version': '1'}}}, headers)
    if session: headers['Mcp-Session-Id'] = session
    inventory, _ = request(url, {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'}, headers)
    tools = inventory.get('result', {}).get('tools', [])
    def call(suffix, arguments):
        names = [tool['name'] for tool in tools if tool['name'].endswith('_' + suffix)]
        if len(names) != 1:
            raise RuntimeError('Host tool identity is missing or ambiguous')
        result, _ = request(url, {'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call',
                                  'params': {'name': names[0], 'arguments': arguments}}, headers)
        if result.get('error') or result.get('result', {}).get('isError'):
            raise RuntimeError('Host tool rejected the probe')
        payload = result['result']
        if payload.get('structuredContent'):
            return payload['structuredContent']
        return json.loads(next(item['text'] for item in payload['content'] if item.get('type') == 'text'))
    identity = call('capabilities_inspect', {})['identity']
    path = directory + '/' + role + '-probe.txt'
    start = time.monotonic()
    first = 'Jaeger isolated NAS verification\n'
    call('workspace_write', {'path': path, 'content': first})
    read = call('workspace_read', {'path': path})
    assert read['content'] == first
    second = first + 'Edited through authenticated host tool\n'
    call('workspace_write', {'path': path, 'content': second, 'expected_sha256': read['sha256']})
    final = call('workspace_read', {'path': path})
    assert final['content'] == second
    assert final['sha256'] == hashlib.sha256(second.encode()).hexdigest()
    return {'role': role, 'effective_host_identity': identity, 'directory': directory,
            'identity_isolated': identity == role,
            'operations': ['create', 'read', 'compare-and-swap edit', 'read'],
            'seconds': round(time.monotonic() - start, 4), 'ok': True}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--role', choices=('hermes', 'openclaw'), required=True)
    parser.add_argument('--directory', type=validate_path, required=True)
    args = parser.parse_args()
    print(json.dumps(check(args.role, args.directory)))
