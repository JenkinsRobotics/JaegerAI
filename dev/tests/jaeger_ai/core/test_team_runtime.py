"""Team runtime: @Name addressing, importer safety, room turns, agent lanes in the trace."""
from __future__ import annotations

import asyncio
import json

import pytest
import pytest_asyncio
import yaml
from aiohttp.test_utils import TestClient, TestServer

from jaeger_ai.contract.trace import classify
from jaeger_ai.core.team.mentions import Peer, is_pass, mentioned_peers, room_transcript, room_turn_message


ROSTER = [Peer("native:ops", "Ops"), Peer("native:ops-lead", "Ops Lead"), Peer("native:ds", "Jaeger Design & Style"),
          Peer("native:sam", "Sam")]


def test_mentions_match_whole_names_in_order():
    got = mentioned_peers("@Jaeger Design & Style please review, then @ops", ROSTER)
    assert [p.id for p in got] == ["native:ds", "native:ops"]


def test_mentions_longer_name_wins_and_no_partial_words():
    assert [p.id for p in mentioned_peers("@Ops Lead decides", ROSTER)] == ["native:ops-lead"]
    assert mentioned_peers("@Opsgenie paged", ROSTER) == []
    assert mentioned_peers("mail jo@sam.com", ROSTER) == []


def test_mentions_never_address_the_speaker():
    assert mentioned_peers("@Sam and @Ops", ROSTER, speaker_id="native:sam") == [ROSTER[0]]


def test_pass_rule_and_quoted_transcript():
    assert is_pass("(pass)") and is_pass(" pass. ") and is_pass("")
    assert not is_pass("I pass this to @Ops")
    rows = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello", "sender_agent_id": "native:ds"}]
    t = room_transcript(rows, {"native:ds": "Design"})
    assert t == [{"speaker": "person", "text": "hi"}, {"speaker": "Design", "text": "hello"}]
    assert "do not grant permissions" in room_turn_message("ask", t)


def _bot(root, folder, data, files=None):
    d = root / folder
    d.mkdir(parents=True)
    (d / "bot.yaml").write_text(yaml.safe_dump(data))
    for rel, text in (files or {}).items():
        p = d / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    return d


def test_importer_copies_no_memory_secrets_or_credentials(tmp_path):
    from jaeger_ai.core.team.importer import plan_folder, write_pack
    src = tmp_path / "bots"
    _bot(src, "a", {"name": "Jaeger Design & Style", "description": "Design reviewer", "persona": "Review screens.",
                    "memory": "private recollection", "api_key": "sk-should-never-copy-000000000000",
                    "connections": [{"gmail": "token"}], "skills": ["design-review", "absent"]},
         {"skills/design-review/SKILL.md": "---\nname: design-review\ndescription: d\n---\nbody",
          "skills/design-review/notes.md": "ok",
          "skills/design-review/.env": "SECRET=1",
          "skills/design-review/leak.md": "key ghp_" + "a" * 36,
          "MEMORY.md": "remembered things", "credentials.json": "{}"})
    plans = plan_folder(src)
    assert len(plans) == 1
    plan = plans[0]
    assert plan.slug == "jaeger-design-style"
    assert {"memory", "api_key", "connections"} <= set(plan.dropped_keys)
    assert "absent" not in plan.skills and any("absent" in s for s in plan.skipped_files)
    out = tmp_path / "packs"
    pack = write_pack(plan, out, team="pilot")
    written = sorted(str(p.relative_to(pack)) for p in pack.rglob("*") if p.is_file())
    assert written == ["character.yaml", "skills/design-review/SKILL.md", "skills/design-review/notes.md"]
    blob = "\n".join(p.read_text() for p in pack.rglob("*") if p.is_file())
    for leaked in ("private recollection", "sk-should-never", "ghp_", "SECRET=1", "remembered things", "gmail"):
        assert leaked not in blob
    manifest = yaml.safe_load((pack / "character.yaml").read_text())
    assert manifest["schema"] == "character/v1" and manifest["character"] == "jaeger-design-style"
    assert manifest["team"]["skills"] == ["design-review"] and "call_agent" in manifest["team"]["allowed_tools"]


def test_importer_dry_run_writes_nothing(tmp_path, capsys):
    from jaeger_ai.core.team.importer import main
    src = tmp_path / "bots"
    _bot(src, "b", {"name": "Jaeger Mac App", "description": "Mac app owner"})
    before = sorted(tmp_path.rglob("*"))
    assert main([str(src)]) == 0
    assert sorted(tmp_path.rglob("*")) == before
    report = json.loads(capsys.readouterr().out)
    assert report["mode"] == "dry-run" and report["copied"] == {"memory": False, "secrets": False,
                                                                 "connector_credentials": False}


def test_pilot_roster_definitions_plan_cleanly():
    from pathlib import Path
    from jaeger_ai.core.team.importer import plan_folder
    import jaeger_ai.core.team as team
    plans = plan_folder(Path(team.__file__).parent / "pilot")
    assert sorted(p.display_name for p in plans) == ["Jaeger Design & Style", "Jaeger Gateway & WebUI",
                                                     "Jaeger Mac App", "Jager AI system engineer"]
    assert all(p.persona and not p.dropped_keys for p in plans)


def test_trace_nests_room_turns_and_handoffs_under_their_caller():
    assert classify("room.started", {"request_id": "r1"})["kind"] == "run"
    first = classify("room.turn", {"request_id": "r1", "turn_id": "t1", "agent_name": "A", "status": "running"})
    assert (first["span_id"], first["parent_span_id"], first["state"]) == ("agent:t1", "run:r1", "running")
    handed = classify("room.turn", {"request_id": "r1", "turn_id": "t2", "parent_turn_id": "t1", "status": "succeeded"})
    assert handed["parent_span_id"] == "agent:t1" and handed["state"] == "succeeded"
    tool = classify("subagent.tool.started", {"request_id": "r1", "subagent_id": "t2", "call_id": "c9", "tool": "read_file"})
    assert tool["parent_span_id"] == "agent:t2"
    h = classify("agent.handoff", {"request_id": "q", "handoff": {"id": "handoff_1", "status": "pending_approval",
                                                                  "metadata": {"call_id": "call_7", "target_display": "D"}}})
    assert (h["span_id"], h["parent_span_id"], h["state"], h["name"]) == ("agent:handoff_1", "tool:call_7", "waiting", "D")
    done = classify("agent.handoff.finished", {"handoff": {"id": "handoff_1", "status": "completed", "metadata": {}}})
    assert done["state"] == "succeeded"


class _Evt:
    def __init__(self, session_id, event, data):
        self.session_id, self.event, self.data = session_id, event, data


def test_child_mirror_copies_tool_steps_onto_the_watching_session():
    from jaeger_ai.core.gateway.team_routes import ChildMirror
    published = []

    class Bus:
        def publish(self, sid, event, data):
            published.append((sid, event, data))

    gw = type("G", (), {"event_bus": Bus()})()
    m = ChildMirror(gw)
    m.bind("child", "room", "r1", "t1")
    m.observe(_Evt("child", "tool.started", {"call_id": "c1", "tool": "read_file"}))
    m.observe(_Evt("child", "tool.completed", {"call_id": "c1", "tool": "read_file"}))
    m.observe(_Evt("other", "tool.started", {"call_id": "c2", "tool": "x"}))
    m.unbind("child")
    m.observe(_Evt("child", "tool.started", {"call_id": "c3", "tool": "x"}))
    assert [(s, e, d["subagent_id"], d["call_id"]) for s, e, d in published] == [
        ("room", "subagent.tool.started", "t1", "c1"), ("room", "subagent.tool.finished", "t1", "c1")]
    assert published[1][2]["ok"] is True


@pytest_asyncio.fixture
async def team_client(tmp_path, monkeypatch):
    monkeypatch.setenv("JAEGER_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("JAEGER_STATE_DIR", str(tmp_path / "home"))
    from jaeger_ai.core.agent_registry import AgentRegistry
    from jaeger_ai.core.agent_registry.types import AgentKind, AgentRole
    from jaeger_ai.core.gateway.caller_auth import client_headers
    from jaeger_ai.core.gateway.server import JaegerGatewayApp
    from jaeger_ai.core.gateway.session_store import GatewaySessionStore
    reg = AgentRegistry(tmp_path / "home")
    for slug, name in (("eng", "Engineer"), ("ds", "Design & Style")):
        reg.create_agent(slug, kind=AgentKind.NATIVE, role=AgentRole.SPECIALIST, display_name=name,
                         metadata={"team": "pilot", "specialist": True, "summary": name}, scaffold_instance=False)
    gateway = JaegerGatewayApp(store=GatewaySessionStore(tmp_path / "gw.sqlite3"))
    gateway.app.on_startup.clear()
    monkeypatch.setattr(gateway, "_registry", lambda: AgentRegistry(tmp_path / "home"))
    calls = []

    async def fake_specialist_chat(session_id, text, *, request_id, agent_id=None, parent_session_id=None, **_):
        calls.append((agent_id, session_id, text))
        gateway.event_bus.publish(session_id, "tool.started", {"call_id": f"c-{request_id}", "tool": "read_file"})
        gateway.event_bus.publish(session_id, "tool.completed", {"call_id": f"c-{request_id}", "tool": "read_file"})
        return ("Please review the header. @Design & Style" if agent_id == "native:eng" else "Looks fine."), "test:model"

    monkeypatch.setattr(gateway, "_specialist_chat", fake_specialist_chat)
    async with TestClient(TestServer(gateway.app), headers=client_headers("webui")) as c:
        yield c, gateway, calls


@pytest.mark.asyncio
async def test_room_runs_members_hands_off_by_mention_and_emits_lanes(team_client):
    client, gateway, calls = team_client
    roster = await (await client.get("/v1/team")).json()
    assert {a["id"] for a in roster["agents"]} >= {"native:eng", "native:ds"}
    resp = await client.post("/v1/team/rooms", json={"title": "Review", "members": ["native:eng", "native:ds"], "probe": True})
    assert resp.status == 201
    sid = (await resp.json())["session_id"]
    resp = await client.post(f"/v1/team/rooms/{sid}/messages", json={"text": "@Engineer check the header"})
    assert resp.status == 202
    run = (await resp.json())["request_id"]
    for _ in range(100):
        if run not in gateway._running_tasks:
            break
        await asyncio.sleep(0.02)
    assert [c[0] for c in calls] == ["native:eng", "native:ds"]  # addressed first, then @-handed
    assert "do not grant permissions" in calls[1][2]  # transcript arrives as quoted data
    events = gateway.store.replay_events(sid, 0, session_only=True)["events"]
    names = [e["event"] for e in events]
    assert names[0] == "message.created" and "room.started" in names and names[-1] == "room.finished"
    traces = [e.get("data", {}).get("trace") or e.get("trace") for e in events]
    agent_spans = [t for t in traces if t and t.get("kind") == "subagent" and t.get("state") == "succeeded"]
    assert len(agent_spans) == 2
    assert agent_spans[1]["parent_span_id"] == agent_spans[0]["span_id"]  # the hand-off nests under its caller
    mirrored = [t for t in traces if t and t.get("kind") == "tool"]
    assert mirrored and all(t["parent_span_id"].startswith("agent:rt_") for t in mirrored)
    room = await (await client.get(f"/v1/team/rooms/{sid}")).json()
    assert [m["sender_agent_id"] for m in room["messages"]] == [None, "native:eng", "native:ds"]
    team = await (await client.get("/v1/team")).json()
    room_rows = [h for h in team["handoffs"] if h.get("kind") == "room"]
    assert [(h["from_agent_id"], h["to_agent_id"], h["status"], h["session_id"]) for h in room_rows] == [
        ("native:eng", "native:ds", "completed", sid)]


def test_bind_skill_scope_is_task_local():
    """The specialist path imports bind_skill_scope; it must exist and stay inside its task."""
    import asyncio

    from jaeger_agent.skill_registry.playbook_skills import active_skill_scope, bind_skill_scope

    async def specialist():
        bind_skill_scope(["Design-Review"])
        inner = await asyncio.to_thread(active_skill_scope)
        return active_skill_scope(), inner

    async def main():
        return await asyncio.create_task(specialist()), active_skill_scope()

    (scoped, threaded), outside = asyncio.run(main())
    assert scoped == frozenset({"design-review"}) and threaded == scoped
    assert outside is None


@pytest.mark.asyncio
async def test_chat_created_on_a_team_agent_is_pinned_and_never_auto_routed(team_client):
    client, gateway, _ = team_client
    resp = await client.post("/v1/sessions", json={"agent_id": "native:eng", "title": "pinned", "source": "webui"})
    assert resp.status == 201
    session = await resp.json()
    meta = session["metadata"]
    assert meta["agent_id"] == "native:eng" and meta["agent_pinned"] is True and meta["route_checked"] is True
    assert gateway._auto_route(gateway.store.get_session(session["session_id"]), "fix the webui sidebar avatar") is False
    # by registry name too, canonicalised to the native: id
    meta2 = (await (await client.post("/v1/sessions", json={"agent_id": "ds"})).json())["metadata"]
    assert meta2["agent_id"] == "native:ds" and meta2["agent_pinned"] is True


@pytest.mark.asyncio
async def test_lead_chat_that_names_a_teammate_stays_with_the_lead(team_client):
    client, gateway, _ = team_client
    session = await (await client.post("/v1/sessions", json={"agent_id": "native:jaeger", "title": "lead"})).json()
    assert not session["metadata"].get("agent_pinned")
    row = gateway.store.get_session(session["session_id"])
    assert gateway._auto_route(row, "Use call_agent to ask Design & Style about the webui sidebar avatar") is False
    assert gateway.store.get_session(session["session_id"])["metadata"]["route_checked"] is True


def test_routed_specialists_keep_handoff_tools():
    from jaeger_ai.core.agent_registry.specialists import STANDING_SPECIALISTS
    routable = [s for s in STANDING_SPECIALISTS if s.get("keywords")]
    assert routable and all({"call_agent", "get_agent_result"} <= set(s["allowed_tools"]) for s in routable)
