"""Cooperative model and external retrieval fixtures, NOT a research verifier.

Only activated by OwnedGateway(research=True). Reserved .invalid URLs and
invented prose are deliberately not represented as real-world evidence.
"""
import json
import os
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


def terminal_command():
    prefix = shlex.join([sys.executable, str(SCRIPT), '--ledger', 'workspace/sources.json'])
    return ' && '.join([
        prefix + ' ingest workspace/retrieval.json',
        prefix + ' quote 1 --text ' + shlex.quote(QUOTE) + ' --from workspace/page.txt',
        prefix + ' render --style evidence --replace-in workspace/research-report.md',
        prefix + ' verify workspace/research-report.md --evidence --strict --min-coverage 1',
    ])


def model_response(messages):
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
                        'verify':{'kind':'paths_exist','paths':['workspace/research-report.md']}}),
        ('web_search', {'query':'fixture observations'}),
        ('web_extract', {'url':result(1)['results'][0]['url'] if len(results) > 1 else URL}),
        ('write_file', {'path':'workspace/retrieval.json', 'content':json.dumps(result(1)) if len(results) > 1 else ''}),
        ('write_file', {'path':'workspace/page.txt', 'content':result(2)['text'] if len(results) > 2 else ''}),
        ('write_file', {'path':'workspace/research-report.md', 'content':'# Synthetic research fixture\n\n' + QUOTE + '[1]\n'}),
        ('terminal', {'command':terminal_command()}),
        ('read_file', {'path':'workspace/research-report.md'}),
        ('work_ledger', {'action':'update','completed_ids':['report'],'remaining_count':0}),
        ('complete_task', {'summary':'Synthetic citation ledger checked; not independent factual verification.',
                           'evidence':'Ran grounded-citations evidence verification and read back workspace/research-report.md'}),
    ]
    step = len(results)
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
