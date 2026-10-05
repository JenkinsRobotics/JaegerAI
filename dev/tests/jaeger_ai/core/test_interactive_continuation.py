"""Turn-owned interactive requests continue only on evidence of unfinished work."""
from __future__ import annotations

from jaeger_ai.core.runtime import autonomous_runner as ar


def _run(monkeypatch, answers, objective, *, interactive=True, halts=None):
    prompts: list[str] = []
    halts = list(halts or [None] * len(answers))

    def step(p):
        prompts.append(p)
        i = len(prompts) - 1
        return {"text": answers[min(i, len(answers) - 1)], "halt_reason": halts[min(i, len(halts) - 1)]}

    monkeypatch.setattr(ar, "last_completion", lambda: None)
    monkeypatch.setattr(ar, "ledger_open", lambda: False)
    ar.run_continued_turn(step, objective, objective=objective, durable=True,
                          interactive=interactive, max_steps=4)
    return prompts


def test_settled_answer_ends_in_one_call(monkeypatch):
    prompts = _run(monkeypatch, ["The sha256 is 3f2a…"], "What is the sha256 of the string hello?")
    assert len(prompts) == 1


def test_durable_background_task_keeps_strict_harness(monkeypatch):
    prompts = _run(monkeypatch, ["The sha256 is 3f2a…"], "What is the sha256 of hello?", interactive=False)
    assert len(prompts) >= 4
    assert "Autonomous Harness" in prompts[1]


def test_promise_to_continue_gets_continuation(monkeypatch):
    prompts = _run(monkeypatch, ["I'll now read the remaining files.", "Done: 3 files read."],
                   "Read the three notes and summarise them.")
    assert len(prompts) == 2


def test_inner_cap_gets_continuation(monkeypatch):
    prompts = _run(monkeypatch, ["Summary so far.", "All done."], "Audit the repo.",
                   halts=["max_iterations reached", None])
    assert len(prompts) == 2


def test_missing_named_file_gets_one_neutral_check(monkeypatch, tmp_path):
    target = tmp_path / "out" / "report.md"
    prompts = _run(monkeypatch, ["Report written.", "Report written.", "x"],
                   f"Write a report to {target}")
    assert len(prompts) == 2
    assert str(target) in prompts[1]
    assert "say so plainly instead of creating them" in prompts[1]


def test_existing_named_file_needs_no_check(monkeypatch, tmp_path):
    target = tmp_path / "report.md"
    target.write_text("ok")
    prompts = _run(monkeypatch, ["Report written."], f"Write a report to {target}")
    assert len(prompts) == 1


def test_question_ends_turn(monkeypatch):
    prompts = _run(monkeypatch, ["Which directory should I use?"], "Write notes somewhere sensible.")
    assert len(prompts) == 1


def test_missing_named_paths_resolves_relative_to_instance(monkeypatch, tmp_path):
    from jaeger_agent.core import workspace as ws

    (tmp_path / "workspace").mkdir()
    (tmp_path / "workspace" / "in.txt").write_text("x")

    class L:
        root = tmp_path
        workspace_dir = tmp_path / "workspace"

    monkeypatch.setattr(ws, "_require_layout", lambda: L())
    monkeypatch.setattr(ws, "get_effective_workspace_dir", lambda: tmp_path / "workspace")
    monkeypatch.setattr(ws, "get_project_root", lambda: None)
    assert ar.missing_named_paths("read workspace/in.txt then write workspace/out.json") == ["workspace/out.json"]
    assert ar.missing_named_paths("read in.txt") == []


def test_required_paths_keeps_absolute_paths():
    assert ar._required_paths("Write a report to /tmp/x/report.md now.") == ["/tmp/x/report.md"]
    assert ar._required_paths("see ~/notes/a.txt and b.json") == ["~/notes/a.txt", "b.json"]

