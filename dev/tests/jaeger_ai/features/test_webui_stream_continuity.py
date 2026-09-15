from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[4]
ASSET = REPO / "jaeger_ai" / "assets" / "jaeger_stream_continuity.js"
MANIFEST = REPO / "jaeger_ai" / "assets" / "jaeger_webui_extensions.json"
NODE = shutil.which("node")


@pytest.mark.skipif(NODE is None, reason="node is required for the browser lifecycle test")
def test_live_turn_owns_the_browser_stream_budget_until_every_turn_is_terminal() -> None:
    """A chat stream must preempt background SSE connections in the active tab.

    The production server is HTTP/1.1. Browsers cap concurrent connections per
    origin, so a second PWA tab plus the session-list streams can leave a
    successful ``/api/chat/start`` response waiting forever for a free socket.
    This harness drives the real extension lifecycle and observes the browser
    functions that own those connections.
    """
    source = ASSET.read_text(encoding="utf-8")
    harness = f"""
const vm = require('node:vm');
const listeners = new Map();
const calls = [];
const context = {{
  console,
  setTimeout: (fn) => {{ fn(); return 1; }},
  clearTimeout: () => {{}},
  addEventListener: () => {{}},
  document: {{ hidden: false, addEventListener: () => {{}} }},
  stopGatewaySSE: () => calls.push('pause:gateway'),
  _closeSessionEventsSSE: () => calls.push('pause:sessions'),
  ensureSessionEventsSSE: () => calls.push('resume:sessions'),
  startGatewaySSE: () => calls.push('resume:gateway'),
}};
context.window = context;
context.hermesExt = {{
  register(id) {{
    if (id !== 'jaeger-stream-continuity') throw new Error('wrong extension id');
    return {{ events: {{ on(type, handler) {{ listeners.set(type, handler); }} }} }};
  }},
}};
vm.createContext(context);
vm.runInContext({json.dumps(source)}, context);

for (const type of ['turn:start', 'turn:complete', 'turn:error', 'turn:cancel']) {{
  if (!listeners.has(type)) throw new Error(`missing lifecycle handler: ${{type}}`);
}}

listeners.get('turn:start')({{sessionId:'s1', streamId:'r1'}});
listeners.get('turn:start')({{sessionId:'s2', streamId:'r2'}});
if (calls.join(',') !== 'pause:gateway,pause:sessions') {{
  throw new Error(`background streams were not paused exactly once: ${{calls}}`);
}}

listeners.get('turn:error')({{sessionId:'s1', streamId:'r1'}});
if (calls.some(value => value.startsWith('resume:'))) {{
  throw new Error('one terminal turn resumed streams while another was active');
}}
listeners.get('turn:cancel')({{sessionId:'s2', streamId:'r2'}});
if (calls.join(',') !== 'pause:gateway,pause:sessions,resume:sessions,resume:gateway') {{
  throw new Error(`background streams were not restored after the last turn: ${{calls}}`);
}}
"""
    result = subprocess.run(
        [NODE, "-e", harness],
        cwd=REPO,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_stream_continuity_extension_is_packaged_before_optional_console() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    ids = [extension["id"] for extension in manifest["extensions"]]
    assert "jaeger-stream-continuity" in ids
    assert ids.index("jaeger-stream-continuity") < ids.index("jaeger-gateway-console")
