#!/usr/bin/env python3
"""Opt-in live Mac Dispatcher continuity/Focus probe; uses model tokens.

Creates a labeled Focus session, adds verification messages to the Dispatcher,
reads README, and retains its native turn report. No automatic tool approvals.
"""
import json,time,uuid,urllib.request,urllib.error
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from jaeger_ai.interfaces.hermes_profile_adapters.native_runs import profile_key
base='http://192.168.64.1:8642'
REPO_ROOT = Path(__file__).resolve().parents[1]

def workspace():
    for folder in ('GitHub', 'Desktop', 'Documents', 'workspace'):
        home = Path.home() / folder
        if REPO_ROOT.is_relative_to(home):
            mount = Path('/workspace') if folder == 'workspace' else Path('/mnt/host') / folder
            return str(mount / REPO_ROOT.relative_to(home))
    raise ValueError('The verification checkout must be in a published Mac workspace')

def request(path,body=None):
 req=urllib.request.Request(base+path,data=None if body is None else json.dumps(body).encode(),headers={'Authorization':'Bearer '+profile_key('jaeger'),'Content-Type':'application/json'})
 with urllib.request.urlopen(req,timeout=20) as r: return json.load(r)
def turn(session,message):
 run=request('/v1/runs',{'session_id':session,'input':message,'workspace':workspace()})
 rid=run['run_id'];started=time.monotonic()
 while time.monotonic()-started<120:
  value=request('/v1/runs/'+rid)
  for aid in value.get('pending_approval_ids',[]):
   request('/v1/runs/'+rid+'/approval',{'approval_id':aid,'choice':'deny'})
  if value['status'] in {'completed','failed','cancelled'}:
   print(json.dumps({'session':session,'run_id':rid,'status':value['status'],'seconds':round(time.monotonic()-started,2),'output':value.get('output','')[:1200]}),flush=True)
   assert value['status']=='completed',value
   return value
  time.sleep(.15)
 request('/v1/runs/'+rid+'/cancel',{})
 raise RuntimeError('Own verification run exceeded observation deadline; cancellation requested')
def main():
    word='DISPATCH-'+uuid.uuid4().hex[:8]
    one=turn('dispatcher','Verification only. The fresh verification identifier for THIS conversation is '+word+'. Reply exactly '+word+'. Ignore any older codeword in stored facts. No tools or long-term memory writes.')
    assert word in one['output']
    focus='verification-focus-'+uuid.uuid4().hex
    worker=turn(focus, f'Use the native read_file tool to read the first line of {REPO_ROOT / "README.md"} and quote it. Do not write files, browse, or use memory tools.')
    assert 'JaegerAI' in worker['output']
    receipt = json.loads((Path(__file__).resolve().parents[1] / '.jaeger_ai/shared/webui-runs/jaeger' / (worker['run_id'] + '.json')).read_text())
    assert any(e['event'] == 'tool.completed' and e.get('tool') == 'read_file' for e in receipt['events'])
    state=request('/v1/dispatcher')
    report=next(r for r in state['reports'] if r['run_id']==worker['run_id'])
    assert report['board_card'] and report['session']=='focus:'+focus
    last=turn('dispatcher','What verification word did I ask you to hold, and what did the latest Focus worker report? Answer briefly without tools.')
    assert word in last['output'] and 'JaegerAI' in last['output']
    skills=request('/v1/dispatcher/skills')['skills'];print('Native skill count:',len(skills));assert len(skills)>0
    print('PASS: Dispatcher continuity, isolated Focus read, durable report and board projection',flush=True)


if __name__ == '__main__':
    main()
