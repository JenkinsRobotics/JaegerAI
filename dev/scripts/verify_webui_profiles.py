"""Opt-in live two-turn checks. Creates labeled chats; never edits existing chats.

Run with the external Jaeger Python. Native services and the Web UI must run.
Each second prompt omits its random marker, proving native conversation recall.
"""
import argparse
import json
import time
import uuid
from pathlib import Path
from urllib.request import Request, urlopen


def request(base, path, profile, body=None):
    req = Request(base.rstrip('/') + path,
        data=None if body is None else json.dumps(body).encode(),
        headers={'Content-Type': 'application/json', 'Cookie': 'hermes_profile=' + profile})
    with urlopen(req, timeout=60) as response:
        return json.load(response)


def verify(args, profile):
    marker = 'CHECK-' + uuid.uuid4().hex[:12].upper()
    body = {'profile': profile, 'worktree': False,
            'model': args.model, 'model_provider': args.provider}
    if args.workspace:
        body['workspace'] = args.workspace
    session = request(args.webui, '/api/session/new', profile, body)['session']
    sid = session['session_id']
    report = {'profile': profile, 'session_id': sid, 'marker': marker, 'turns': []}
    for number, prompt in enumerate((
        f'Chat continuity verification. Remember the code {marker} in this conversation. '
        'Reply with that exact code. Do not use tools or write files.',
        'What exact code did I give you in my previous message? Reply with the code. '
        'Use only this conversation; do not use tools or write files.'), 1):
        accepted = request(args.webui, '/api/chat/start', profile,
            {'session_id': sid, 'message': prompt, 'model': args.model,
             'model_provider': args.provider})
        rid = accepted.get('run_id') or accepted['stream_id']
        print(json.dumps({'profile': profile, 'turn': number, 'run_id': rid, 'status': 'started'}), flush=True)
        deadline = time.monotonic() + args.timeout
        while time.monotonic() < deadline:
            state = request(args.runner, '/v1/runs/' + rid, profile)
            if state.get('terminal_state'):
                break
            time.sleep(1)
        else:
            raise RuntimeError(f'{profile} turn {number} still active: {rid}; not resent')
        events = request(args.runner, '/v1/runs/' + rid + '/events', profile)['events']
        if state['status'] != 'completed':
            raise RuntimeError(f'{profile} turn {number}: {events[-1]}')
        expected_owner = 'hermes' if profile == 'default' else profile
        assert state['profile'] == expected_owner, state
        done = next(e['payload'] for e in reversed(events) if e['event'] == 'done')
        answer = done['session']['messages'][-1]['content']
        assert marker in answer, f'{profile} turn {number} did not recall {marker}: {answer}'
        # Verify browser-facing durable writeback, not just the native receipt.
        for _ in range(30):
            saved = request(args.webui, '/api/session?session_id=' + sid, profile)['session']
            if len(saved.get('messages', [])) == number * 2 and not saved.get('active_stream_id'):
                break
            time.sleep(1)
        assert saved['profile'] == profile, saved['profile']
        assert len(saved['messages']) == number * 2, len(saved['messages'])
        assert marker in saved['messages'][-1]['content']
        report['turns'].append({'run_id': rid, 'status': state['status'],
            'native': state.get('native'), 'messages': len(saved['messages']), 'recall': True})
        print(json.dumps({'profile': profile, 'turn': number, 'status': 'passed', 'messages': len(saved['messages'])}), flush=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--webui', default='http://127.0.0.1:8790')
    parser.add_argument('--runner', default='http://127.0.0.1:8791')
    parser.add_argument('--profiles', nargs='+', default=['default', 'jaeger', 'openclaw', 'roundtable'],
                        choices=['default', 'jaeger', 'openclaw', 'roundtable'])
    parser.add_argument('--model', default='glm-5.3-flash:cloud')
    parser.add_argument('--provider', default='ollama')
    parser.add_argument('--workspace')
    parser.add_argument('--timeout', type=float, default=600)
    parser.add_argument('--report', type=Path, required=True, help='Report path outside the source tree')
    args = parser.parse_args()
    reports = []
    for profile in args.profiles:
        reports.append(verify(args, profile))
        args.report.write_text(json.dumps(reports, indent=2) + '\n')


if __name__ == '__main__':
    main()
