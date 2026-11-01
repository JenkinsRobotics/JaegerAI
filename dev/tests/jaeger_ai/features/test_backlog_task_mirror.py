from jaeger_ai.features.backlog.store import BacklogStore
from jaeger_ai.features.backlog.task_mirror import mirror_tasks


def test_tasks_land_in_backlog_and_follow_state(tmp_path):
    s = BacklogStore(tmp_path / "b.sqlite3")
    tasks = [{"task_id": "task_abc", "goal": "Write the report", "state": "paused"},
             {"task_id": "turn:task_abc:0", "goal": "internal", "state": "running"}]
    assert mirror_tasks(s, tasks) == 1
    rows = s.list()
    assert [(r["title"], r["status"], r["source"]) for r in rows] == [("Write the report", "needs_ok", "task")]
    tasks[0]["state"] = "completed_verified"
    assert mirror_tasks(s, tasks) == 1 and s.list()[0]["status"] == "done"
    assert mirror_tasks(s, tasks) == 0 and len(s.list()) == 1
    tasks[0].update(state="failed", error="boom")
    mirror_tasks(s, tasks)
    assert s.list()[0]["status"] == "open" and s.list()[0]["last_note"] == "boom"
