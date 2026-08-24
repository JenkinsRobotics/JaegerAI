"""TurnExecutive binds a durable run around the loop."""

from __future__ import annotations

from pydantic import BaseModel

from jaeger_agent import JaegerAgent, Message, ProviderAdapter, ToolDef
from jaeger_agent.cognition.commitments import InMemoryCommitmentStore
from jaeger_agent.cognition.effects import EffectIndeterminate, InMemoryEffectLedger
from jaeger_agent.cognition.executive import TURN_LOOP_KIND, TurnExecutive
from jaeger_agent.cognition.intake import record_told
from jaeger_agent.memory.in_memory_knowledge import InMemoryKnowledgeStore
from jaeger_agent.memory.models import Entity, ProvenanceKind
from jaeger_agent.cognition.runs import InMemoryRunStore
from jaeger_agent.tool_executor import LedgerToolExecutor


class _Scripted(ProviderAdapter):
    name = "scripted"

    def __init__(self, script: list[Message]) -> None:
        self.script = list(script)

    def format_messages(self, messages, tools, system):
        return messages

    def call(self, formatted, interrupt_event, **kwargs):
        return self.script.pop(0)

    def parse_response(self, raw):
        return raw

    def supports(self, feature: str) -> bool:
        return False


def test_executive_reuses_one_active_run_and_checkpoints():
    runs = InMemoryRunStore()
    commitments = InMemoryCommitmentStore()
    agent = JaegerAgent(
        adapter=_Scripted([
            {"role": "assistant", "content": "one"},
            {"role": "assistant", "content": "two"},
        ]),
        tools=[],
    )
    execu = TurnExecutive(agent, runs, commitments, provider="scripted")
    assert execu.run_turn("a") == "one"
    run_id = agent.run_id
    assert run_id
    assert execu.run_turn("b") == "two"
    assert agent.run_id == run_id
    run = runs.get(run_id)
    assert run is not None
    assert run.state == "active"
    assert commitments.get(run.commitment_id).kind == TURN_LOOP_KIND
    assert runs.latest_checkpoint(run_id) is not None


def test_executive_records_user_text_as_told_claim():
    store = InMemoryKnowledgeStore()
    agent = JaegerAgent(
        adapter=_Scripted([{"role": "assistant", "content": "noted"}]),
        tools=[],
    )
    execu = TurnExecutive(
        agent, InMemoryRunStore(), InMemoryCommitmentStore(), claims=store,
    )
    execu.run_turn("my editor is neovim")
    said = store.list_claims(predicate="said", provenance=ProvenanceKind.TOLD)
    assert said[0].value == "my editor is neovim"
    structured = store.list_claims(predicate="editor", provenance=ProvenanceKind.TOLD)
    assert structured[0].value == "neovim"
    assert store.get_active_belief("user", "editor").value == "neovim"


def test_external_tool_writes_a_checkpoint():
    from pydantic import BaseModel
    from jaeger_agent.tool_executor import LedgerToolExecutor
    from jaeger_agent.cognition.effects import InMemoryEffectLedger

    class _Args(BaseModel):
        n: int

    tool = ToolDef(
        name="send_email",
        description="Send",
        args_model=_Args,
        fn=lambda n: {"sent": n},
        side_effect="external",
    )
    adapter = _Scripted([
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {"id": "c1", "name": "send_email", "arguments": {"n": 1}},
            ],
        },
        {"role": "assistant", "content": "sent"},
    ])
    agent = JaegerAgent(
        adapter=adapter,
        tools=[tool],
        tool_executor=LedgerToolExecutor(InMemoryEffectLedger(), run_id="r1"),
    )
    runs = InMemoryRunStore()
    execu = TurnExecutive(agent, runs, InMemoryCommitmentStore())
    assert execu.run_turn("send it") == "sent"
    point = runs.latest_checkpoint(agent.run_id)
    assert point is not None
    assert point.cursor.get("tool") == "send_email" or "halt" in point.cursor


def test_write_tool_checkpoints_finalized_transcript_and_observation():
    class _Args(BaseModel):
        path: str
    tool = ToolDef(name="write_note", description="Write", args_model=_Args,
                   fn=lambda path: {"ok": True, "path": path}, side_effect="write")
    agent = JaegerAgent(adapter=_Scripted([
        {"role": "assistant", "content": None, "tool_calls": [{"id": "w1", "name": "write_note", "arguments": {"path": "a.md"}}]},
        {"role": "assistant", "content": "done"},
    ]), tools=[tool])
    runs = InMemoryRunStore()
    cursors = []
    checkpoint = runs.checkpoint
    runs.checkpoint = lambda run_id, cursor: (cursors.append(cursor), checkpoint(run_id, cursor))[1]
    store = InMemoryKnowledgeStore()
    execu = TurnExecutive(agent, runs, InMemoryCommitmentStore(), claims=store)
    execu.run_turn("write it")
    tool_point = next(cursor for cursor in cursors if cursor.get("event") == "tool_result")
    assert tool_point["message"]["tool_call_id"] == "w1"
    assert store.list_claims(subject="agent", predicate="tool_result")[0].provenance == ProvenanceKind.OBSERVED


def test_known_person_mention_is_linked_without_guessing_new_entities():
    store = InMemoryKnowledgeStore()
    person = store.save_entity(Entity.create("Ada Lovelace", kind="person", aliases=["Ada"]))
    record_told(store, "I met Ada about the compiler", source_id="turn-1")
    links = store.list_claims(predicate="mentioned_person")
    assert links[0].value == person.id
    assert store.find_entity("Ada").attributes["last_mentioned_source"] == "turn-1"
    record_told(store, "I met Grace about the compiler", source_id="turn-2")
    assert store.find_entity("Grace") is None


def test_contradicted_belief_requests_evidence_before_calling_model():
    store = InMemoryKnowledgeStore()
    adapter = _Scripted([{"role": "assistant", "content": "should not run"}])
    agent = JaegerAgent(adapter=adapter, tools=[])
    execu = TurnExecutive(agent, InMemoryRunStore(), InMemoryCommitmentStore(), claims=store)
    assert execu.run_turn("my editor is vim") == "should not run"
    answer = execu.run_turn("my editor is neovim")
    assert "conflicting information" in answer
    assert len(adapter.script) == 0


def test_record_told_skips_blank():
    store = InMemoryKnowledgeStore()
    assert record_told(store, "  ") is None
    assert store.list_claims() == []


def test_crash_after_success_does_not_duplicate_external_effect():
    class _Args(BaseModel):
        n: int

    calls: list[int] = []
    tool = ToolDef(
        name="send_email",
        description="Send",
        args_model=_Args,
        fn=lambda n: calls.append(n) or {"sent": n},
        side_effect="external",
    )
    ledger = InMemoryEffectLedger()
    first = LedgerToolExecutor(ledger, run_id="r-crash")
    assert first.execute(tool, {"n": 1}) == {"sent": 1}
    resumed = LedgerToolExecutor(ledger, run_id="r-crash")
    assert resumed.execute(tool, {"n": 1}) == {"sent": 1}
    assert calls == [1]


def test_failure_before_claim_is_retryable():
    class _Args(BaseModel):
        n: int

    tool = ToolDef(
        name="send_email",
        description="Send",
        args_model=_Args,
        fn=lambda n: {"sent": n},
        side_effect="external",
    )
    ledger = InMemoryEffectLedger()
    executor = LedgerToolExecutor(ledger, run_id="r-val")
    import pytest
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        executor.execute(tool, {})
    assert ledger.list() == []
    assert executor.execute(tool, {"n": 2}) == {"sent": 2}


def test_failure_after_claim_is_indeterminate():
    class _Args(BaseModel):
        n: int

    tool = ToolDef(
        name="send_email",
        description="Send",
        args_model=_Args,
        fn=lambda n: (_ for _ in ()).throw(RuntimeError("lost after claim")),
        side_effect="external",
    )
    ledger = InMemoryEffectLedger()
    executor = LedgerToolExecutor(ledger, run_id="r-mid")
    import pytest
    with pytest.raises(RuntimeError, match="lost after claim"):
        executor.execute(tool, {"n": 3})
    with pytest.raises(EffectIndeterminate):
        executor.execute(tool, {"n": 3})
