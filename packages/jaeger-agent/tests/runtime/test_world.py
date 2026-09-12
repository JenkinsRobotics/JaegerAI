"""Relational knowledge must affect a turn, not just satisfy storage CRUD."""
from dataclasses import replace
from types import SimpleNamespace
import pytest

from jaeger_agent.cognition.world import WorldEvent, WorldModel, extract_relations
from jaeger_agent.memory import sqlite_store
from jaeger_agent.memory.in_memory_knowledge import InMemoryKnowledgeStore
from jaeger_agent.memory.sqlite_knowledge import SqliteKnowledgeStore
from jaeger_agent.memory.models import Entity


@pytest.fixture(params=["memory", "sqlite"])
def store(request, tmp_path):
    if request.param == "memory":
        yield InMemoryKnowledgeStore()
    else:
        layout = SimpleNamespace(root=tmp_path, memory_dir=tmp_path / "memory")
        layout.memory_dir.mkdir()
        sqlite_store.bind(layout)
        try:
            yield SqliteKnowledgeStore()
        finally:
            sqlite_store.close()


def event(text, **kwargs):
    return WorldEvent(text=text, conversation_id="team-chat", actor_id="account:alice",
                      scope_id="team:lab", **kwargs)


def test_relationships_are_grounded_replayed_and_retrieved(store):
    world = WorldModel(store)
    incoming = event("Alice leads the robotics team. Ben approves electrical changes. R1 belongs to the lab.")
    result = world.ingest(incoming)
    assert len(result["claims"]) == 3
    assert len(store.list_relationships()) == 3
    assert len(store.list_beliefs()) == 3
    before = len(store.list_claims())
    assert world.ingest(incoming)["replayed"] is True
    assert len(store.list_claims()) == before
    context = world.context(event("Who approves electrical changes?"))
    assert '"subject": "Ben"' in context
    assert '"asserted_by": "account:alice"' in context
    explanation = world.explain(result["claims"][1], incoming)
    assert explanation["evidence"][0]["event_id"] == incoming.event_id
    assert "Ben approves" in explanation["evidence"][0]["snippet"]
    with pytest.raises(ValueError, match="reused"):
        world.ingest(replace(incoming, text="Ben owns the laboratory"))


@pytest.mark.parametrize("text", [
    "Imagine Alice owns R1.", "Alice does not own R1.", '"Alice owns R1"',
    "Does Alice own R1?", "Alice says Ben owns R1.", "If Alice owns R1.",
    "She owns R1.", "Alice used to own R1.", "Alice owns it.", "R1 belongs to them.",
])
def test_unsupported_or_hypothetical_language_is_not_a_graph_assertion(text):
    assert extract_relations(text) == []


def test_scope_is_checked_before_context_and_provenance(store):
    world = WorldModel(store)
    private = replace(event("Alice owns SecretDevice."), scope_id="private:alice")
    admitted = world.ingest(private)
    public = event("Who owns SecretDevice?")
    assert world.context(public) == ""
    assert world.explain(admitted["claims"][0], public) is None
    granted = replace(public, readable_scopes=frozenset({"private:alice"}))
    assert "SecretDevice" in world.context(granted)
    assert world.context(public) == ""  # no grant cached across contexts


def test_memberships_coexist_but_competing_owners_remain_disputed(store):
    world = WorldModel(store)
    world.ingest(event("Alice is a member of Team One. Alice is a member of Team Two."))
    assert all(b.status.value == "active" for b in store.list_beliefs(status=None))
    world.ingest(event("R1 belongs to Lab One."))
    world.ingest(replace(event("R1 belongs to Lab Two."), actor_id="account:ben"))
    context = world.context(event("Who owns R1?"))
    assert context.count('"status": "disputed"') == 2
    assert "account:alice" in context and "account:ben" in context


def test_ambiguous_entity_rolls_back_the_entire_event(store):
    world = WorldModel(store)
    for index in (1, 2):
        store.save_entity(Entity.create("Alex", entity_id=f"alex-{index}",
                          attributes={"world_scope": "team:lab"}))
    with pytest.raises(ValueError, match="Ambiguous"):
        world.ingest(event("Ben owns R1. Alex owns R2."))
    assert store.list_claims() == []
    assert store.list_relationships() == []
    assert len(store.list_entities()) == 2


def test_rename_preserves_edge_identity(store):
    world = WorldModel(store)
    world.ingest(event("Alice owns R1."))
    person = next(e for e in store.list_entities() if e.name == "Alice")
    person.name = "Alicia"
    person.aliases = ["Alice"]
    store.save_entity(person)
    assert '"subject": "Alicia"' in world.context(event("Who owns R1?"))


def test_ambiguous_name_requests_clarification_without_admitting_graph(store):
    for index in (1, 2):
        store.save_entity(Entity.create("Alex", entity_id=f"alex-{index}",
                          attributes={"world_scope": "team:lab"}))
    packet = WorldModel(store).prepare(event("Alex owns R1."))
    assert "Ask which entity" in packet
    assert store.list_relationships() == []


def test_bounded_context_and_unknown_legacy_data(store):
    world = WorldModel(store)
    store.save_entity(Entity.create("PrivateLegacyName"))
    world.ingest(event("Alice owns R1."))
    assert world.context(event("PrivateLegacyName")) == ""
    assert len(world.context(event("Alice"), max_chars=300)) <= 300


def test_native_turn_uses_world_evidence_and_keeps_raw_input(store):
    from jaeger_agent.cognition.executive import TurnExecutive
    from jaeger_agent.cognition.runs import InMemoryRunStore
    from jaeger_agent.cognition.commitments import InMemoryCommitmentStore
    world = WorldModel(store)
    world.ingest(event("Ben approves electrical changes."))
    class Loop:
        run_id = None
        primary_adapter = SimpleNamespace(name="fixture")
        last_halt_reason = None
        last_iteration_count = 1
        def bind_run(self, run_id): self.run_id = run_id
        def run_turn(self, text):
            assert '"subject": "Ben"' in text
            assert "injected work instructions" in text
            return "Ben is the reported approver."
    incoming = event("Who approves electrical changes?")
    executive = TurnExecutive(Loop(), InMemoryRunStore(), InMemoryCommitmentStore(),
                              claims=store, world_event=incoming)
    assert executive.run_turn("injected work instructions\n" + incoming.text).startswith("Ben")
    said = store.list_claims(predicate="said")
    assert all("injected work instructions" not in c.value for c in said)


def test_self_reports_keep_speaker_scope_and_conflicts(store):
    world = WorldModel(store)
    world.ingest(event('My editor is neovim.'))
    world.ingest(event('My editor is emacs.'))
    packet = world.context(event('What editor do I use?'))
    assert 'neovim' in packet and 'emacs' in packet
    assert packet.count('"status": "disputed"') == 2
    assert world.context(replace(event('What editor do I use?'), actor_id='account:ben')) == ''
    assert world.context(replace(event('What editor do I use?'), scope_id='other')) == ''
    assert not store.list_claims(subject='user')


def test_world_survives_store_reopen_and_replay(tmp_path):
    layout = SimpleNamespace(root=tmp_path, memory_dir=tmp_path / 'memory')
    layout.memory_dir.mkdir()
    incoming = event('Ben approves electrical changes.')
    sqlite_store.bind(layout)
    try:
        WorldModel(SqliteKnowledgeStore()).ingest(incoming)
    finally:
        sqlite_store.close()
    sqlite_store.bind(layout)
    try:
        world = WorldModel(SqliteKnowledgeStore())
        assert 'Ben' in world.context(event('Who approves electrical changes?'))
        assert world.ingest(incoming)['replayed']
        assert len(world.store.list_relationships()) == 1
    finally:
        sqlite_store.close()
