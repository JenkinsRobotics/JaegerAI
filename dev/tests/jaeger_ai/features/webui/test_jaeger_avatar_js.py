"""The WebUI avatar maps presence to expressions and the mouth to a speech level."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[5] / "jaeger_ai" / "features" / "webui" / "static"

HARNESS = r"""
const store={}; const listeners={};
const el=()=>({style:{},dataset:{},appendChild(){},append(){},addEventListener(){},setAttribute(){},
  getContext:()=>new Proxy({},{get:(t,k)=>k==='createRadialGradient'?()=>({addColorStop(){}}):()=>{}})});
global.localStorage={getItem:k=>k in store?store[k]:null,setItem:(k,v)=>{store[k]=String(v)}};
global.document={readyState:'complete',createElement:el,body:el(),addEventListener(){}};
global.window=global; global.location={href:'http://127.0.0.1:8790/'}; global.CustomEvent=class{constructor(t,o){this.type=t;this.detail=o&&o.detail}};
global.dispatchEvent=e=>{(listeners[e.type]||[]).forEach(f=>f(e))};
global.addEventListener=(t,f)=>{(listeners[t]=listeners[t]||[]).push(f)};
global.requestAnimationFrame=()=>0; global.performance={now:()=>0};
global.fetch=async()=>({ok:true,json:async()=>({display:'thinking'})});
global.setInterval=()=>0;
require(process.argv[2]);
setTimeout(()=>{
  const a=window.jaegerAvatar, out={};
  out.polled=a.state.display;
  a.setState('ask_owner'); out.ask=a.state.display;
  a.setState('nonsense'); out.unknown=a.state.display;
  a.setSpeaking(true); a.setLevel(3); out.speaking=a.state.speaking;
  a.setSpeaking(false); out.after=a.state.speaking;
  let seen=null; addEventListener('jaeger-avatar-mode',e=>{seen=e.detail});
  a.setMode('vrm'); out.mode=[a.mode(),seen];
  console.log(JSON.stringify(out));
},20);
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_avatar_expressions_follow_presence_and_mode_toggles(tmp_path):
    harness = tmp_path / "h.js"
    harness.write_text(HARNESS)
    out = subprocess.run(["node", str(harness), str(STATIC / "jaeger_avatar.js")],
                         capture_output=True, text=True, timeout=20)
    assert out.returncode == 0, out.stderr
    got = json.loads(out.stdout.strip().splitlines()[-1])
    assert got == {"polled": "thinking", "ask": "ask_owner", "unknown": "idle",
                   "speaking": True, "after": False, "mode": ["vrm", "vrm"]}


def test_index_loads_the_avatar_before_the_companion():
    html = (STATIC / "index.html").read_text()
    assert html.index("jaeger_avatar.js") < html.index("jaeger_companion.js")


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_vrm_avatar_module_loads_its_vendored_libraries_and_maps_every_presence_label():
    """The 3D module resolves three.js and three-vrm locally (no CDN, no bare
    imports) and has an expression for every DISPLAY label."""
    from jaeger_ai.contract.presence import DISPLAY

    url = (STATIC / "jaeger_avatar_vrm.js").as_uri()
    script = f"import({json.dumps(url)}).then(m=>console.log(JSON.stringify(Object.keys(m.EXPRESSIONS))))"
    out = subprocess.run(["node", "--input-type=module", "-e", script],
                         capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    assert set(DISPLAY.values()) <= set(json.loads(out.stdout.strip().splitlines()[-1]))
    for path in (STATIC / "vendor" / "three-vrm").rglob("*.js"):
        assert 'from"three"' not in path.read_text() and "from 'three'" not in path.read_text()
    assert (STATIC / "vendor" / "VENDOR-avatar.md").read_text().count("MIT") >= 2


def test_avatar_model_route_serves_only_the_configured_local_vrm(tmp_path, monkeypatch):
    import importlib
    import sys

    sys.path.insert(0, str(STATIC.parent))
    agents = importlib.import_module("api.jaeger_agents")
    model = tmp_path / "jaeger.vrm"
    model.write_bytes(b"glTF-model")
    monkeypatch.setenv("JAEGER_AVATAR_VRM", str(model))
    assert agents.avatar_model_path() == model
    monkeypatch.setenv("JAEGER_AVATAR_VRM", str(tmp_path / "secrets.txt"))
    (tmp_path / "secrets.txt").write_text("x")
    assert agents.avatar_model_path() is None
