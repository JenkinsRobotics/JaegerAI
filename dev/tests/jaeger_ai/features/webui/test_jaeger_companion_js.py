"""Speak-first feed in the WebUI: a slow first poll never replays stale messages."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[5] / "jaeger_ai" / "features" / "webui" / "static"

HARNESS = r"""
const store={}; const shown=[];
const el=()=>({style:{},dataset:{},children:[],append(...c){this.children.push(...c)},appendChild(c){this.children.push(c)},
  addEventListener(){},setAttribute(){},remove(){},get isConnected(){return false},set textContent(v){this._t=v},get textContent(){return this._t}});
global.localStorage={getItem:k=>k in store?store[k]:null,setItem:(k,v)=>{store[k]=String(v)}};
global.document={readyState:'loading',createElement:el,body:el(),addEventListener(){},hidden:false};
global.window=global; global.setTimeout=(f,ms)=>ms>1000?0:globalThis.setImmediate(f);
const now=Date.now()/1000;
const items=[{event_id:1,body:'stale',created_at:now-2000},{event_id:2,body:'recent',created_at:now-30}];
let calls=0;
global.fetch=async(url)=>{ calls++; const since=+new URL('http://x/'+url).searchParams.get('since_event_id');
  if(calls===1) await new Promise(r=>setImmediate(()=>setImmediate(r)));      // slow cold first response
  const out=items.filter(i=>i.event_id>since);
  return {ok:true,json:async()=>({notifications:out,cursor:out.length?out[out.length-1].event_id:since})}; };
require(process.argv[2]);
const c=window.jaegerCompanion; const orig=c.show;
(async()=>{
  // Wrap show by observing the body texts appended to the bubble box.
  const p1=c.poll(), p2=c.poll();                    // the interval tick overlaps the first poll
  await Promise.all([p1,p2]); await c.poll();
  const box=document.body.children.find(x=>x.id==='jaegerCompanion');
  const bodies=(box?box.children:[]).map(m=>m.children[1]._t);
  console.log(JSON.stringify({bodies, cursor:store['jaeger-companion-cursor']}));
})();
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_overlapping_first_polls_show_only_the_recent_message_once(tmp_path):
    harness = tmp_path / "h.js"
    harness.write_text(HARNESS)
    out = subprocess.run(["node", str(harness), str(STATIC / "jaeger_companion.js")],
                         capture_output=True, text=True, timeout=20)
    assert out.returncode == 0, out.stderr
    got = json.loads(out.stdout.strip().splitlines()[-1])
    assert got == {"bodies": ["recent"], "cursor": "2"}
