"""Qualification of cooperative grounding, not automatic source enforcement.

No browser or live source/model is exercised. Documents is reopened through
its authenticated production HTTP API, preserving the task result text while
checking original artifact bytes separately.
"""
import base64
import hashlib
import html
import json
import re
import sqlite3
import subprocess
import sys
import time
from http.cookiejar import CookieJar
from urllib.request import HTTPCookieProcessor, Request, build_opener

import pytest

from dev.tests.fixtures.owned_gateway import OwnedGateway
from dev.tests.fixtures.research_contract import QUOTE, SCRIPT, TITLE, URL, terminal_command

pytestmark = [pytest.mark.integration, pytest.mark.subprocess]


def test_research_report_source_chain_and_documents_reopen(tmp_path):
    gateway = OwnedGateway(tmp_path, webui=True, research=True)
    sid = 'research-parent'
    body = {'session_id':sid, 'goal':'Deep research: CONTRACT-RESEARCH synthetic observations',
            'request_id':'research-proposal-once', 'proposal':True}
    approved = []
    try:
        gateway.start()
        gateway.request('/v1/sessions', {'session_id':sid,'profile':'jaeger'})
        admitted = gateway.request('/v1/tasks', body, caller='webui')[1]
        tid = admitted['task_id']
        assert admitted['status'] == 'paused'
        proposed = gateway.request('/v1/tasks/'+tid)[1]
        assert proposed['provenance']['authorized'] is False
        assert not proposed['run_history']
        gateway.request('/v1/tasks/'+tid+'/approve',
                        {'expected_updated_at':proposed['updated_at']}, caller='webui')
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            for a in gateway.request('/v1/approvals')[1]['approvals']:
                assert a['session_id'] == 'task:' + tid and a['request_id'] == tid + ':0'
                assert a['metadata']['tool'] in {'files.write_file','shell.run_shell'}, a
                # Independently decode all displayed supplied arguments and
                # compare them to the exact scripted call before authorizing it.
                # These fixtures contain no credentials requiring redaction.
                issued = [json.loads(line) for line in (tmp_path/'research-provider-tools.jsonl').read_text().splitlines()]
                call = issued[-1]
                pairs = [line.split('=', 1) for line in a['metadata']['target'].splitlines()]
                shown = {key: json.loads(value) for key, value in pairs}
                assert len(shown) == len(pairs), a  # Do not silently drop duplicate keys.
                assert shown == call['args'], (a, call)
                if a['metadata']['tool'] == 'files.write_file':
                    expected = {'research-3': 'retrieval.json', 'research-4': 'page.txt',
                                'research-5': 'research-report.md'}
                    assert call['name'] == 'write_file' and call['call_id'] in expected, call
                    assert shown['path'] == 'workspace/' + expected[call['call_id']]
                    assert set(shown) == {'path', 'content'} and isinstance(shown['content'], str)
                else:
                    assert call == {'call_id':'research-6','name':'terminal','args':{'command':terminal_command(), 'timeout_s':60.0}}
                assert a['approval_id'] not in {row['approval_id'] for row in approved}, a
                gateway.request('/v1/approvals/' + a['approval_id'], {'approved':True,'decision':'once'})
                approved.append(a)
            response = gateway.request('/v1/tasks/' + tid)[1]
            task = response.get('task', response)
            if task['state'] in {'completed_verified','failed','cancelled','needs_owner','blocked'}:
                break
            time.sleep(.05)
        assert task['state'] == 'completed_verified', (task, (tmp_path/'gateway.log').read_text()[-10000:])
        assert len(approved) == 4
        root = tmp_path/'instances/contract/workspace'
        sources = json.loads((root/'sources.json').read_text())['sources']
        assert len(sources) == 1
        assert {k:sources[0][k] for k in ['id','url','title']} == {'id':1,'url':URL,'title':TITLE}
        assert sources[0]['quotes'][0]['text'] == QUOTE
        assert (root/'page.txt').read_text() == QUOTE
        assert json.loads((root/'retrieval.json').read_text())['results'][0]['url'] == URL
        report = (root/'research-report.md').read_bytes()
        assert QUOTE.encode() in report and URL.encode() in report and b'[1]' in report
        digest = hashlib.sha256(report).hexdigest()
        catalog = gateway.request('/v1/library/artifacts?task_id='+tid)[1]
        refs = [r for r in catalog['artifacts'] if r['sha256'] == digest]
        assert len(refs) == 1, catalog
        artifact_url = '/v1/library/artifacts/'+tid+'/'+refs[0]['attachment_id']
        downloaded = gateway.request(artifact_url)[1]
        assert base64.b64decode(downloaded['data_base64']) == report
        with sqlite3.connect(f'file:{tmp_path / "gateway_sessions.sqlite3"}?mode=ro',uri=True) as db:
            events = [(e,json.loads(d)) for e,d in db.execute("SELECT event,data_json FROM events WHERE event LIKE 'tool.%' ORDER BY rowid")]
        done = [d for e,d in events if e == 'tool.completed']
        assert len(done) == 10 and all(d['success'] for d in done), events
        assert [d['tool'] for d in done] == ['work_ledger','web_search','web_extract','write_file','write_file','write_file','terminal','read_file','work_ledger','complete_task']
        assert all(d['request_id'] == tid+':0' for _,d in events)
        # ResearchPage's Save to Documents posts resultText(task.result).
        # Final answer normalization strips trailing whitespace; preserve that
        # explicit distinction from artifact bytes, then replay
        # that exact save/reopen HTTP workflow (no rendered browser claimed).
        result = task['result']
        result_text = result if isinstance(result,str) else result['text']
        assert result_text == report.decode().strip()
        browser = build_opener(HTTPCookieProcessor(CookieJar()))
        def request(path, payload=None):
            headers = {'Content-Type':'application/json'}
            if payload is not None and path != '/api/auth/login':
                headers['X-Hermes-CSRF-Token'] = csrf
            with browser.open(Request(gateway.webui_url+path, data=None if payload is None else json.dumps(payload).encode(), headers=headers), timeout=5) as r:
                return json.load(r)
        assert request('/api/auth/login', {'password':'synthetic-contract-password'}) == {'ok':True}
        with browser.open(gateway.webui_url+'/', timeout=5) as r:
            csrf = html.unescape(re.search(r'<meta name="jaeger-csrf" content="([^"]*)">',r.read().decode()).group(1))
        doc = request('/v1/documents', {'title':'Synthetic research report','body':result_text})
        assert request('/v1/documents/'+doc['id'])['body'] == result_text
        before = (tmp_path/'provider-calls.jsonl').read_bytes()
        gateway.stop()
        gateway.start()
        assert request('/v1/documents/'+doc['id']) == doc
        assert len(request('/v1/documents')['documents']) == 1
        assert base64.b64decode(gateway.request(artifact_url)[1]['data_base64']) == report
        assert gateway.request('/v1/tasks',body,caller='webui')[1]['replayed']
        assert (tmp_path/'provider-calls.jsonl').read_bytes() == before
        assert json.loads((root/'sources.json').read_text())['sources'] == sources
        assert gateway.request('/v1/approvals')[1]['approvals'] == []
    finally:
        gateway.stop()


def test_grounded_citations_negative_controls_and_semantic_limit(tmp_path):
    ledger = tmp_path/'ledger.json'
    draft = tmp_path/'draft.md'
    page = tmp_path/'page.txt'
    page.write_text(QUOTE)
    def cli(*args):
        p = subprocess.run([sys.executable,str(SCRIPT),'--ledger',str(ledger),*map(str,args)],capture_output=True,text=True)
        print(args, p.returncode, p.stdout, p.stderr)
        return p
    assert cli('add',URL).returncode == 0
    draft.write_text(QUOTE+'[1]\n\n## Sources\n[1] '+URL+'\n')
    assert cli('verify',draft,'--evidence').returncode == 1
    assert cli('quote','1','--text','The fixture measured ninety samples.','--from',page).returncode != 0
    assert cli('quote','1','--text',QUOTE,'--from',page).returncode == 0
    assert cli('verify',draft,'--evidence').returncode == 0
    for content in [QUOTE+'[99]\n\n## Sources\n[99] '+URL, QUOTE+'[1]\n\n## Sources\n[1] https://fabricated.invalid/page']:
        draft.write_text(content)
        assert cli('verify',draft,'--evidence').returncode == 1
    # Explicit limitation: an unrelated claim with a known quoted source passes.
    # The existing checker checks citation consistency, not entailment/truth.
    draft.write_text('The fixture proves the moon is cheese.[1]\n\n## Sources\n[1] '+URL)
    assert cli('verify',draft,'--evidence','--strict','--min-coverage','1').returncode == 0
    ledger.write_text('invalid json')
    assert cli('verify',draft,'--evidence').returncode != 0


def test_search_unavailable_is_not_empty(monkeypatch):
    from jaeger_agent.tools import web
    def unavailable(query, count):
        raise RuntimeError('synthetic outage')
    monkeypatch.setattr(web,'_BACKENDS',[('fixture',unavailable)])
    unavailable_result = web.web_search('fixture')
    assert unavailable_result['ok'] is False and unavailable_result['status'] == 'unavailable'
    monkeypatch.setattr(web,'_BACKENDS',[('fixture',lambda q,n: [])])
    empty_result = web.web_search('fixture')
    assert empty_result['ok'] is True and empty_result['status'] == 'no_results' and empty_result['results'] == []
