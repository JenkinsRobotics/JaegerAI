"""Cooperative model and external retrieval fixtures, NOT a research verifier.

Only activated by OwnedGateway(research=True). Reserved .invalid URLs and
invented prose are deliberately not represented as real-world evidence.
"""
import json
import os
import re
import shlex
import sys
from pathlib import Path

URL = 'https://research-fixture.invalid/observations'
QUOTE = 'The fixture measured seven blue samples.'
TITLE = 'Synthetic observations'
SCRIPT = Path(__file__).resolve().parents[3] / 'packages/jaeger-agent/jaeger_agent/skills/research/grounded-citations/scripts/sources.py'


def install_retrieval():
    import requests
    from jaeger_agent.tools import web

    def search(query, limit):
        if query == 'fixture unavailable':
            raise RuntimeError('synthetic retrieval outage')
        if query == 'fixture empty':
            raise web.NoSearchResults('synthetic zero matches')
        assert query == 'fixture observations'
        return [{'url': URL, 'title': TITLE, 'snippet': 'Read the synthetic observation page.'}]

    class Response:
        headers = {'Content-Type': 'text/html'}
        encoding = 'utf-8'
        def raise_for_status(self):
            pass
        def iter_content(self, chunk_size):
            yield ('<html><head><title>Do not cite this</title></head><body><p>' + QUOTE + '</p></body></html>').encode()
        def close(self):
            pass

    def get(url, **kwargs):
        assert url == URL, f'Unexpected retrieval target: {url}'
        return Response()

    web._BACKENDS = [('synthetic', search)]
    requests.get = get


def terminal_command(directory=''):
    base = Path('workspace') / directory
    prefix = shlex.join([sys.executable, str(SCRIPT), '--ledger', str(base/'sources.json')])
    return ' && '.join([
        prefix + ' ingest ' + shlex.quote(str(base/'retrieval.json')),
        prefix + ' quote 1 --text ' + shlex.quote(QUOTE) + ' --from ' + shlex.quote(str(base/'page.txt')),
        prefix + ' render --style evidence --replace-in ' + shlex.quote(str(base/'research-report.md')),
        prefix + ' verify ' + shlex.quote(str(base/'research-report.md')) + ' --evidence --strict --min-coverage 1',
    ])


def model_response(messages):
    # Explicit contracts receive server-designated task-local paths. Historical
    # prefix-only fixtures retain their existing workspace-root artifact layout.
    directory = ''
    for message in messages:
        content = message.get('content')
        if not isinstance(content, str):
            continue
        match = re.search(r'^Research artifact paths: (\{[^\n]+\})$', content, re.MULTILINE)
        if match:
            paths = json.loads(match[1])
            directory = str(Path(paths['report_path']).parent)
            assert paths == {'report_path': directory+'/research-report.md',
                             'ledger_path': directory+'/sources.json'}
            break
    base = Path('workspace') / directory
    report_path = str(base/'research-report.md')
    results = [m for m in messages if m.get('role') == 'tool' and str(m.get('tool_call_id', '')).startswith('research-')]
    def result(index):
        raw = next(m['content'] for m in results if m['tool_call_id'] == f'research-{index}')
        if raw.startswith('<untrusted_tool_result '):
            raw = raw.split('\n\n', 1)[1].rsplit('\n</untrusted_tool_result>', 1)[0]
        return json.loads(raw)
    # Source bytes are obtained from real native tool results, not seeded into
    # the ledger or copied directly from this fixture's retrieval definitions.
    steps = [
        ('work_ledger', {'action':'create', 'task_name':'Synthetic research', 'total_items':1,
                        'verify':{'kind':'paths_exist','paths':[report_path]}}),
        ('web_search', {'query':'fixture observations'}),
        ('web_extract', {'url':result(1)['results'][0]['url'] if len(results) > 1 else URL}),
        ('write_file', {'path':str(base/'retrieval.json'), 'content':json.dumps(result(1)) if len(results) > 1 else ''}),
        ('write_file', {'path':str(base/'page.txt'), 'content':result(2)['text'] if len(results) > 2 else ''}),
        ('write_file', {'path':report_path, 'content':'# Synthetic research fixture\n\n' + QUOTE + '[1]\n'}),
        ('terminal', {'command':terminal_command(directory), 'timeout_s':60.0}),
        ('read_file', {'path':report_path}),
        ('work_ledger', {'action':'update','completed_ids':['report'],'remaining_count':0}),
        ('complete_task', {'summary':'Synthetic citation ledger checked; not independent factual verification.',
                           'evidence':'Ran grounded-citations evidence verification and read back '+report_path}),
    ]
    step = len(results)
    # Test-only cooperative provider boundary. Native tool execution and its
    # durable receipts have already returned; only the owned process is killed.
    cut = Path(os.environ['JAEGER_STATE_DIR']) / 'research-cut.json'
    if cut.exists() and json.loads(cut.read_text())['after_tools'] == step:
        import threading
        (cut.parent / 'research-cut-ready.json').write_text(json.dumps({
            'pid': os.getpid(), 'after_tools': step, 'directory': directory,
            'tool_call_ids': [m['tool_call_id'] for m in results],
        }))
        threading.Event().wait()
    if step > 6:
        assert result(6)['exit_code'] == 0, result(6)
        assert 'citations OK' in result(6)['stdout'], result(6)
    if step < len(steps):
        name, args = steps[step]
        with (Path(os.environ['JAEGER_STATE_DIR'])/'research-provider-tools.jsonl').open('a') as stream:
            stream.write(json.dumps({'call_id':f'research-{step}', 'name':name, 'args':args})+'\n')
        message = {'role':'assistant','content':None,'tool_calls':[{'id':f'research-{step}', 'type':'function',
                   'function':{'name':name,'arguments':json.dumps(args)}}]}
        reason = 'tool_calls'
    else:
        message = {'role':'assistant','content':result(7)['content'], 'tool_calls':[]}
        reason = 'stop'
    return {'choices':[{'message':message,'finish_reason':reason}]}
