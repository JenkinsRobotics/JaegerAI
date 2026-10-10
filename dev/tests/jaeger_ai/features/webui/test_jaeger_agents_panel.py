"""The sidebar roster: Jaeger first, specialists next, runtime leftovers hidden;
each agent opens one stable home session the gateway routes by agent_id."""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

WEBUI = Path(__file__).resolve().parents[5] / "jaeger_ai" / "features" / "webui"
STATIC = WEBUI / "static"
AGENTS = [
    {"id": "native:health", "name": "health", "role": "runtime", "kind": "jaeger_native"},
    {"id": "tp:hermes", "name": "hermes", "display_name": "Hermes Agent", "role": "specialist", "kind": "third_party"},
    {"id": "native:gateway", "name": "gateway", "display_name": "Gateway", "role": "specialist", "kind": "jaeger_native"},
    {"id": "native:jaeger", "name": "jaeger", "display_name": "Assistant", "role": "lead", "kind": "jaeger_native"},
    {"id": "native:everyday", "name": "everyday", "display_name": "Everyday", "role": "specialist", "kind": "jaeger_native"},
]


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_roster_order_labels_and_home_ids():
    harness = (
        "global.window={};global.document={readyState:'loading',addEventListener(){}};"
        f"require({json.dumps(str(STATIC / 'jaeger_agents_panel.js'))});"
        f"const A=window.jaegerAgents.sortAgents({json.dumps(AGENTS)});"
        "console.log(JSON.stringify(A.map(a=>[window.jaegerAgents.label(a),window.jaegerAgents.homeId(a)])));"
    )
    out = subprocess.run(["node", "-e", harness], capture_output=True, text=True, timeout=30, check=True)
    assert json.loads(out.stdout) == [
        ["Jaeger", "agent-jaeger"], ["Everyday", "agent-everyday"],
        ["Gateway", "agent-gateway"], ["Hermes Agent", "agent-hermes"],
    ]


def test_home_session_request_is_stable_and_tagged_with_the_agent():
    sys.path.insert(0, str(WEBUI))
    from api.jaeger_agents import agent_home_request

    body = agent_home_request(AGENTS[3])
    assert body["session_id"] == "agent-jaeger" and body["title"] == "Jaeger"
    assert body["metadata"] == {"agent_id": "native:jaeger", "home": True, "source": "webui"}
    weird = agent_home_request({"id": "tp:x", "name": "../Evil Name", "role": "specialist"})
    assert weird["session_id"] == "agent----evil-name"
    from jaeger_ai.core.gateway.session_hygiene import classify
    assert classify({**body, "message_count": 0})[0] == "agent"


def test_index_loads_the_roster():
    assert "static/jaeger_agents_panel.js" in (STATIC / "index.html").read_text()
