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
    {"id": "native:research", "name": "research", "display_name": "Research", "role": "specialist", "kind": "jaeger_native"},
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
    # Lead first, then user-facing specialists. Runtime rows, the internal
    # 'gateway'/'surfaces' components and third-party framework adapters are
    # hidden (jaeger_agents_panel.js:3-4, :10-26 since 25aed5c1).
    assert json.loads(out.stdout) == [
        ["Jaeger", "agent-jaeger"], ["Everyday", "agent-everyday"],
        ["Research", "agent-research"],
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


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_chat_chip_names_the_owner_and_puts_the_suggestion_first():
    harness = (
        "global.window={};global.document={readyState:'loading',addEventListener(){}};"
        f"require({json.dumps(str(STATIC / 'jaeger_agents_panel.js'))});"
        "const J=window.jaegerAgents;"
        f"J.setRoster(J.sortAgents({json.dumps(AGENTS)}));"
        "const s={agent_id:'native:jaeger',metadata:{suggested_agent_id:'native:research'}};"
        "console.log(JSON.stringify([J.chipText(s),J.menuItems(s).map(i=>i.text),J.chipText({})]));"
    )
    out = subprocess.run(["node", "-e", harness], capture_output=True, text=True, timeout=30, check=True)
    chip, items, default = json.loads(out.stdout)
    assert chip == "with Jaeger" and default == "with Jaeger"
    assert items[0] == "★ Suggested: Research"
    assert "Hand off to Everyday" in items and not any("Jaeger" in i for i in items)


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_auto_route_notice_offers_one_click_undo_back_to_jaeger():
    harness = (
        "global.window={};global.document={readyState:'loading',addEventListener(){}};"
        f"require({json.dumps(str(STATIC / 'jaeger_agents_panel.js'))});"
        "const J=window.jaegerAgents;"
        f"J.setRoster(J.sortAgents({json.dumps(AGENTS)}));"
        "const auto={agent_id:'native:everyday',metadata:{routed_by:'auto',previous_agent_id:'native:jaeger'}};"
        "const owner={agent_id:'native:everyday',metadata:{routed_by:'owner',previous_agent_id:'native:jaeger'}};"
        "console.log(JSON.stringify([J.routedNotice(auto),J.routedNotice(owner)]));"
    )
    out = subprocess.run(["node", "-e", harness], capture_output=True, text=True, timeout=30, check=True)
    auto, owner = json.loads(out.stdout)
    assert auto == {"text": "Jaeger handed this to Everyday", "undoTo": "native:jaeger"}
    assert owner is None
