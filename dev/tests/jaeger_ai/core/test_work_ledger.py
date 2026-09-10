"""Native work ledger — the count of record for autonomous batch work."""

from __future__ import annotations

import json

import pytest

from jaeger_ai.core.runtime.work_ledger import (
    active_ledger,
    complete_task,
    consume_completion,
    context_block,
    progress_event,
    reset,
    set_progress_publisher,
    work_ledger,
)


@pytest.fixture(autouse=True)
def _clean():
    reset()
    set_progress_publisher(None)
    yield
    reset()
    set_progress_publisher(None)


def test_create_then_status():
    out = work_ledger(
        action="create", task_name="notes", total_items=10,
    )
    assert out["ok"] is True
    ledger = out["ledger"]
    assert ledger["total_items"] == 10
    assert ledger["remaining"] == 10
    assert work_ledger(action="status")["ledger"]["task_id"] == ledger["task_id"]


def test_create_requires_a_name():
    assert work_ledger(action="create")["ok"] is False


def test_update_moves_items_and_recomputes_remaining():
    work_ledger(action="create", task_name="batch", total_items=5)
    out = work_ledger(
        action="update",
        completed_ids=["1", "2"],
        in_progress_ids=["3"],
        remaining_ids=["4", "5"],
    )
    ledger = out["ledger"]
    assert ledger["done_count"] == 2
    assert ledger["remaining"] == 2
    assert "3" in ledger["in_progress_ids"]


def test_complete_task_refuses_without_evidence():
    work_ledger(action="create", task_name="x", total_items=1)
    assert complete_task(summary="done")["ok"] is False


def test_complete_task_refuses_while_items_remain():
    work_ledger(action="create", task_name="x", total_items=2)
    work_ledger(action="update", completed_ids=["1"], remaining_count=1)
    out = complete_task(evidence="only one done")
    assert out["ok"] is False
    assert "remaining" in out["error"]


def test_complete_task_refuses_an_empty_ledger():
    """F3 fail-closed: a ledger with no countable items cannot complete."""
    work_ledger(action="create", task_name="empty")
    out = complete_task(evidence="I did it")
    assert out["ok"] is False
    assert "fail closed" in out["error"] or "countable" in out["error"]


def test_complete_task_paths_exist_spec_refuses_missing_files(tmp_path):
    work_ledger(
        action="create",
        task_name="files",
        total_items=1,
        verify={"kind": "paths_exist", "paths": [str(tmp_path / "nope.txt")]},
    )
    work_ledger(action="update", completed_ids=["1"], remaining_count=0)
    out = complete_task(evidence="claimed")
    assert out["ok"] is False
    assert "missing" in out["error"]


def test_complete_task_paths_exist_spec_passes_when_files_are_there(tmp_path):
    path = tmp_path / "item_00.txt"
    path.write_text("ok\n")
    work_ledger(
        action="create",
        task_name="files",
        total_items=1,
        verify={"kind": "paths_exist", "paths": [str(path)]},
    )
    work_ledger(action="update", completed_ids=["1"], remaining_count=0)
    out = complete_task(evidence="item_00.txt written")
    assert out["ok"] is True
    receipts = out["verification_receipts"]
    assert receipts[0] == {
        "kind": "ledger_count", "done": 1, "total": 1, "remaining": 0,
    }
    assert receipts[1]["kind"] == "file_sha256"
    assert receipts[1]["bytes"] == 3
    assert len(receipts[1]["sha256"]) == 64


def test_complete_task_callable_verifier_can_refuse():
    from jaeger_ai.core.runtime.work_ledger import set_completion_verifier
    work_ledger(action="create", task_name="x", total_items=1)
    work_ledger(action="update", completed_ids=["1"], remaining_count=0)
    set_completion_verifier(lambda ledger: "nope")
    out = complete_task(evidence="claimed")
    assert out["ok"] is False
    assert "nope" in out["error"]


def test_work_ledger_tool_rejects_truncated_raw_arguments():
    from jaeger_ai.core.runtime.work_ledger import _t_work_ledger
    out = _t_work_ledger(_raw_arguments='{"task_name": "x", "total_items":')
    assert out["ok"] is False
    assert "truncated" in out["error"] or "unparsed" in out["error"]


def test_registered_work_ledger_exposes_structured_progress_arguments():
    from jaeger_os.core.tools.tool_registry import get_tool

    from jaeger_ai.core.runtime.work_ledger import _t_work_ledger

    registered = get_tool("work_ledger")
    fields = registered.args_model.model_fields
    assert registered.fn is _t_work_ledger
    assert {"action", "completed_ids", "remaining_ids", "remaining_count"} <= set(fields)
    assert "kwargs" not in fields


def test_complete_task_succeeds_when_every_item_is_done():
    created = work_ledger(action="create", task_name="x", total_items=2)
    task_id = created["ledger"]["task_id"]
    work_ledger(
        action="update", completed_ids=["a", "b"], remaining_count=0,
        in_progress_ids=[],
    )
    out = complete_task(
        task_id=task_id, summary="all done", evidence="a and b written",
    )
    assert out["ok"] is True and out["completed"] is True
    assert out["verification_receipts"][0]["remaining"] == 0
    assert consume_completion()["task_id"] == task_id
    assert consume_completion() is None


def test_context_block_is_injected_while_open():
    work_ledger(action="create", task_name="notes", total_items=3)
    block = context_block()
    assert "[Work Ledger]" in block
    assert "notes" in block
    assert "0/3" in block


def test_persists_under_instance_run_dir(tmp_path, monkeypatch):
    from jaeger_ai.core.instance.instance import InstanceLayout
    from jaeger_ai.main import _pipeline

    layout = InstanceLayout(root=tmp_path / "inst")
    layout.root.mkdir()
    layout.ensure_dirs()
    monkeypatch.setitem(_pipeline, "layout", layout)

    created = work_ledger(action="create", task_name="disk", total_items=1)
    task_id = created["ledger"]["task_id"]
    path = layout.run_dir / f"ledger_{task_id}.json"
    assert path.is_file()
    payload = json.loads(path.read_text())
    assert payload["task_name"] == "disk"

    work_ledger(action="update", completed_ids=["1"], remaining_count=0)
    complete_task(evidence="wrote the file")
    payload = json.loads(path.read_text())
    assert payload["completed"] is True


def test_status_by_task_id_from_another_view(tmp_path, monkeypatch):
    """The main session inspects a worker's ledger by id."""
    from jaeger_ai.core.instance.instance import InstanceLayout
    from jaeger_ai.main import _pipeline

    layout = InstanceLayout(root=tmp_path / "inst")
    layout.root.mkdir()
    layout.ensure_dirs()
    monkeypatch.setitem(_pipeline, "layout", layout)

    created = work_ledger(action="create", task_name="worker-job", total_items=4)
    task_id = created["ledger"]["task_id"]
    # Simulate the main thread having no tls active by resetting tls only:
    active_ledger()  # still this thread
    probed = work_ledger(action="status", task_id=task_id)
    assert probed["ok"] is True
    assert probed["ledger"]["task_name"] == "worker-job"


def test_update_accepts_a_json_encoded_id_list():
    """Qwen / GLM hand ``completed_ids`` over as a JSON string, not an
    array. Comma-splitting that left ``["item_00.txt`` and
    ``"item_19.txt"]`` in the ledger (observed on a live 20-file run)."""
    work_ledger(action="create", task_name="batch", total_items=3)
    out = work_ledger(
        action="update",
        completed_ids='["item_00.txt", "item_01.txt", "item_02.txt"]',
    )
    ledger = out["ledger"]
    assert ledger["completed_ids"] == [
        "item_00.txt", "item_01.txt", "item_02.txt",
    ]
    assert ledger["done_count"] == 3


def test_json_ids_containing_commas_do_not_inflate_the_count():
    """An id with a comma in it used to split into two, so the ledger
    could report a total it never reached."""
    work_ledger(action="create", task_name="batch", total_items=2)
    ledger = work_ledger(
        action="update", completed_ids='["a, with comma", "b"]',
    )["ledger"]
    assert ledger["completed_ids"] == ["a, with comma", "b"]
    assert ledger["done_count"] == 2


def test_plain_comma_string_still_splits():
    work_ledger(action="create", task_name="batch", total_items=3)
    ledger = work_ledger(action="update", completed_ids="a, b, c")["ledger"]
    assert ledger["completed_ids"] == ["a", "b", "c"]


def test_progress_event_carries_structured_args():
    created = work_ledger(
        action="create", task_name="notes", total_items=10,
        remaining_count=10,
    )
    event = progress_event(active_ledger(), state="RUNNING", step=2)
    assert event["name"] == "work_ledger"
    assert event["phase"] == "progress"
    assert event["args"]["task_name"] == "notes"
    assert event["args"]["done"] == 0
    assert event["args"]["total"] == 10
    assert event["args"]["step"] == 2
    assert "notes" in event["detail"]
    assert "0/10" in event["detail"]
    assert created["ok"] is True


def test_create_update_complete_emit_live_progress():
    events: list[dict] = []
    set_progress_publisher(lambda **kw: events.append(kw))
    work_ledger(action="create", task_name="notes", total_items=2)
    work_ledger(
        action="update", completed_ids=["a"], remaining_count=1,
        in_progress_ids=["b"],
    )
    work_ledger(
        action="update", completed_ids=["a", "b"], remaining_count=0,
        in_progress_ids=[],
    )
    complete_task(evidence="wrote a and b", summary="two notes")
    assert len(events) == 4
    assert events[0]["args"]["done"] == 0
    assert events[1]["args"]["done"] == 1
    assert events[1]["args"]["in_progress"] == ["b"]
    assert "b" in events[1]["detail"]
    assert events[-1]["phase"] == "done"
    assert events[-1]["args"]["completed"] is True
    assert events[-1]["args"]["state"] == "COMPLETED"
