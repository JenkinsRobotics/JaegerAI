#!/usr/bin/env python3
"""Opt-in native OpenClaw lifecycle probes; only harmless/read-only test work.

Uses model tokens. Approval probe denies the requested harmless printf command;
no permanent grant or general automatic approval is enabled. Private receipts
are retained in a newly created temporary directory for diagnosis.
"""
import argparse
import json
from pathlib import Path
import sys
import tempfile
import time
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from jaeger_ai.interfaces.hermes_profile_adapters.native_runs import Runs, TERMINAL
from jaeger_ai.interfaces.hermes_profile_adapters.openclaw_native import openclaw_turn, NativeGateway, native_session_key

PROMPTS = {
    'chat': 'Reply exactly OPENCLAW-NATIVE-READY. No tools or memory writes.',
    'read': 'Use a file-reading tool to read only the first line of /mnt/host/GitHub/JaegerAI/README.md and quote it. Do not modify files or use network or memory tools.',
    'approval-deny': '''This is an approval-denial test. Request exec for the exact harmless command python3 -c "print('JAEGER-APPROVAL-PROBE')". If denied, report denial and do not retry or use another tool. Do not change configuration or files.''',
    'cancel': 'Write a numbered list of 1000 unique flower descriptions. No tools, files, network, or memory writes.',
}


def check(scenario):
    root = Path(tempfile.mkdtemp(prefix='jaeger-openclaw-native-'))
    def backend(run, workspace):
        if scenario == 'approval-deny':
            from jaeger_ai.interfaces.hermes_profile_adapters.openclaw import OPENCLAW_BASE_URL, OPENCLAW_TOKEN_FILE
            # Tighten only this brand-new verification session. Never change
            # default policy or an existing user session to force a test prompt.
            with NativeGateway(OPENCLAW_BASE_URL, OPENCLAW_TOKEN_FILE) as gateway:
                gateway.request('sessions.patch', {'key':native_session_key(run.session), 'permissionMode':'guarded'})
        return openclaw_turn(run, workspace)
    runs = Runs(root, backend)
    started = time.monotonic()
    snapshot = runs.start('verification-native-'+uuid.uuid4().hex, PROMPTS[scenario])
    run = runs.get(snapshot['run_id'])
    approvals, cursor, cancelled = 0, 0, False
    while run.status not in TERMINAL and time.monotonic()-started < 75:
        with run.condition:
            pending = list(run.pending)
            events = list(run.events[cursor:])
            cursor = len(run.events)
        for aid in pending:
            run.approve(aid, 'deny')
            approvals += 1
        for event in events:
            if event['event'].startswith('tool.'):
                print(json.dumps({'event':event['event'], 'tool':event.get('tool'), 'status':event.get('status')}), flush=True)
        if scenario == 'cancel' and run.cancel_native and not cancelled:
            run.cancel()
            cancelled = True
        time.sleep(.05)
    if run.status not in TERMINAL:
        run.cancel()
        raise RuntimeError(f'Probe deadline reached; cancellation requested, native outcome unknown. Receipt: {root}')
    result = {'scenario':scenario, 'run':run.id, 'session':run.session, 'status':run.status,
              'cancellation_confirmed':run.cancel_confirmed,
              'seconds':round(time.monotonic()-started,2), 'approvals_denied':approvals,
              'answer':run.output[:1500], 'receipts':str(root)}
    print(json.dumps(result), flush=True)
    if scenario == 'cancel':
        assert run.status == 'cancelled', 'Native abort was not confirmed'
        assert run.cancel_confirmed, 'A local cancellation flag is not a native acknowledgement'
    else:
        assert run.status == 'completed', 'Native probe did not complete'
    if scenario == 'chat':
        assert 'OPENCLAW-NATIVE-READY' in run.output
    elif scenario == 'read':
        assert 'JaegerAI</h1>' in run.output
        assert any(e['event']=='tool.completed' for e in run.events)
    elif scenario == 'approval-deny':
        assert approvals > 0, 'No approval received: do not claim native approval relay was tested'
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scenario', choices=tuple(PROMPTS), default='chat')
    check(parser.parse_args().scenario)
