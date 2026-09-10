#!/usr/bin/env python3
"""Opt-in native Roundtable streaming/resumption probe; no live profile changes.

Creates isolated labelled native sessions and uses provider tokens. Does not
approve tools or mutate agent settings. Run separately from root regression:
native agents will persist their verification conversations.
"""
import json
from pathlib import Path
import sys
import tempfile
import time
import uuid

repo_root = Path(__file__).resolve().parents[3]
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))
from jaeger_ai.features.roundtable.service import TableService
from jaeger_ai.interfaces.hermes_profile_adapters.native_runs import TERMINAL


def verify():
    root = Path(tempfile.mkdtemp(prefix='jaeger-roundtable-native-'))
    service = TableService(root)
    session = 'verification-roundtable-native-' + uuid.uuid4().hex
    code = 'RT-' + uuid.uuid4().hex[:10]
    print(json.dumps({'session': session, 'receipts': str(root)}), flush=True)
    prompts = [
        f'Remember the check word {code} in this conversation only. Begin with READY and the check word, '
        'then give roughly 100 words about how you can contribute to this group chat. '
        'Do not use tools, modify files, or save long-term memory.',
        'What check word did I ask you to remember in our preceding turn? Reply with that exact word only. '
        'Do not use tools or save long-term memory.',
    ]
    previous = {}
    for index, prompt in enumerate(prompts, 1):
        if index == 2:
            # Prove native context, not an orchestrator-injected answer. The
            # second turn's first-stage prompts contain no shared summary/code.
            service.store.summary = lambda *args, **kwargs: 'No summary supplied for this native recall verification.'
        started = time.monotonic()
        parent = service.get(service.start(session, prompt, options={'mode': 'ask'})['run_id'])
        cursor = 0
        live = set()
        approvals = 0
        while parent.status not in TERMINAL or parent.worker_active:
            if time.monotonic() - started > 180:
                parent.cancel()
                raise RuntimeError(f'Explicit verification deadline reached; Stop requested, no automatic replay. Receipts: {root}')
            with parent.condition:
                rows = list(parent.events[cursor:])
                cursor = len(parent.events)
            for row in rows:
                if row['event'] == 'approval.request':
                    parent.approve(row['approval_id'], 'deny')
                    approvals += 1
                elif row['event'] == 'member.message.delta' and row.get('phase') == 'answer':
                    child = service.members[row['member']].get(row['member_run_id'])
                    if child.worker_active and child.status not in TERMINAL:
                        live.add(row['member'])
                elif row['event'] in {'member.finished', 'member.stalled', 'table.decision'}:
                    result = row.get('result') or {}
                    print(json.dumps({'turn': index, 'event': row['event'], 'member': row.get('member'),
                        'phase': row.get('phase'), 'status': result.get('status'),
                        'seconds': round(time.monotonic() - started, 2)}), flush=True)
            time.sleep(.01)
        attempts = service.store.attempts(parent.id)
        answers = [a for a in attempts if a['phase'] == 'answer']
        assert len(answers) == 3, 'Every selected member must receive the first stage'
        for attempt in answers:
            result = attempt['result'] or {}
            assert result.get('status') == 'completed', f'{attempt["member"]}: {result.get("error_category")}; inspect receipts'
            assert code in result.get('output', ''), f'{attempt["member"]} lost the check word on turn {index}'
            if index == 2:
                assert code not in attempt['prompt'], 'Recall answer leaked through orchestration context'
                assert previous[attempt['member']] == attempt['session']
            previous[attempt['member']] = attempt['session']
        assert parent.status == 'completed', f'Table ended {parent.status}; inspect receipts'
        assert len([a for a in attempts if a['phase'] == 'discussion']) == 3
        synthesis = [a for a in attempts if a['phase'] == 'synthesis']
        assert len(synthesis) == 1 and synthesis[0]['result']['status'] == 'completed', 'Chair synthesis did not complete'
        assert approvals == 0, 'Unexpected tool approval was denied; inspect the native trace'
        if index == 1:
            assert live == {'jaeger', 'hermes', 'openclaw'}, f'No proven live partial from: {set(service.members) - live}'
        print(json.dumps({'turn': index, 'status': parent.status, 'native_recall': True,
            'live_partial_members': sorted(live), 'seconds': round(time.monotonic() - started, 2),
            'consensus': service.store.ledger(parent.id)['decision']['consensus']}), flush=True)


if __name__ == '__main__':
    verify()
