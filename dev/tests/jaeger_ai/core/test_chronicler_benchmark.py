import importlib.util
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location("chronicler_benchmark", Path(__file__).resolve().parents[4] / "scripts/benchmark-chronicler.py")
benchmark = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(benchmark)


def test_delayed_probe_cannot_pass_before_two_hours():
    recorded_at = 1000
    due = recorded_at + benchmark.DELAY_SECONDS
    assert benchmark.due_status(due, recorded_at + 7199) == "pending"
    assert benchmark.due_status(due, recorded_at + 7200) == "due"


def test_generated_memory_claim_is_not_a_memory_receipt():
    answer = {"memory": "Stored in Honcho successfully", "open_questions": ["A?", "B?"]}
    checks = benchmark.structure_checks(answer)
    assert not checks["claims_attributed"]
    assert not checks["three_domains_declared"]
    assert "honcho" not in checks and "memory" not in checks


def test_cycle_and_missing_sources_fail_even_with_mermaid_prose():
    answer = {"claims": [{"id": "a", "status": "supported", "source_ids": ["fake"]},
                         {"id": "b", "status": "supported", "source_ids": ["fake"]}],
              "causal_edges": [{"from": "a", "to": "b", "status": "hypothesis", "source_ids": []},
                               {"from": "b", "to": "a", "status": "supported", "source_ids": []}],
              "mermaid": "graph LR; A-->B"}
    checks = benchmark.structure_checks(answer)
    assert not checks["causal_graph_is_dag"]
    assert not checks["causal_edges_attributed"]
    assert not checks["claims_attributed"]


def test_prose_is_not_silently_accepted_as_structured_output():
    with pytest.raises(ValueError):
        benchmark.decode_answer("I finished everything successfully")
    assert benchmark.decode_answer('```json\n{"claims": []}\n```') == {"claims": []}


@pytest.mark.asyncio
async def test_collection_reconciles_original_request_without_redispatch(tmp_path, monkeypatch):
    from types import SimpleNamespace
    import json
    calls = []
    class Response:
        status = 200
        def __init__(self, payload): self.payload = payload
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        def raise_for_status(self): pass
        async def json(self): return self.payload
    class Client:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        def get(self, url):
            calls.append(("GET", url))
            return Response({"status": "execution_unknown"})
        def post(self, url, json):
            calls.append(("POST", url))
            assert json == {"request_id": "original"}
            return Response({"status": "completed", "result": {
                "backend": "native_receipt", "output": "{}",
                "reconciliation": {"execution_unknown": False, "source": "native_bridge_receipt"}}})
    benchmark.save(tmp_path / "report.json", {"session_id": "s", "request_id": "original", "topic": "trial", "started_at": "2026-09-11T00:00:00+00:00"})
    monkeypatch.setattr(benchmark.aiohttp, "ClientSession", Client)
    monkeypatch.setattr(benchmark, "read_memory", lambda *args: {"local": [{}, {}], "honcho": {"found": False}})
    code = await benchmark.collect(SimpleNamespace(timeout=1, instance=tmp_path), tmp_path)
    assert code == 2
    assert calls == [("GET", benchmark.GATEWAY + "/v1/sessions/s/requests/original"),
                     ("POST", benchmark.GATEWAY + "/v1/sessions/s/reconcile")]
    report = json.loads((tmp_path / "report.json").read_text())
    assert report["native_completion"] is True
    assert report["overall_status"] == "incomplete"


def test_regional_table_escapes_pipes_inside_cells():
    table = benchmark.regional_table({"regions": [{"region": "Chinese", "finding": "A | B\nC"}]})
    assert "A \\| B C" in table


@pytest.mark.asyncio
async def test_legacy_completed_receipt_with_halt_cannot_pass(tmp_path, monkeypatch):
    from types import SimpleNamespace
    report = {"topic": "trial", "receipt": {"status": "completed", "result": {
        "backend": "native_receipt", "output": "[halted]", "reconciliation": {
            "source": "native_bridge_receipt", "execution_unknown": False,
            "reply": {"halt_reason": "repeated_tool_failure"}}}}}
    monkeypatch.setattr(benchmark, "read_memory", lambda *args: {"local": [{}, {}]})
    await benchmark.finish_report(report, tmp_path, SimpleNamespace(instance=tmp_path))
    assert report["native_reply_received"]
    assert not report["native_completion"]
    assert report["native_halt_reason"] == "repeated_tool_failure"
