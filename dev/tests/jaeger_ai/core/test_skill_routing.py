"""High-confidence playbook routing before raw tool use."""

from __future__ import annotations

from jaeger_agent.skill_registry import playbook_skills


def test_exact_task_phrase_selects_safari_bookmarks_skill(monkeypatch):
    # Safari skills are intentionally hidden on Linux. Pin the platform so this
    # routing test is hermetic on macOS workstations and Linux CI runners.
    monkeypatch.setattr(playbook_skills, "_current_platform", lambda: "macos")
    skill, score, reason = playbook_skills.match_playbook(
        "Audit and sync my Safari bookmarks, remove duplicates, and organize them"
    )
    assert skill is not None
    assert skill.name == "safari-bookmarks"
    assert score >= 100
    assert "exact phrase" in reason


def test_generic_chat_does_not_auto_select_a_skill():
    skill, score, reason = playbook_skills.match_playbook("What is the capital of France?")
    assert skill is None
    assert score == 0
    assert "match" in reason


def test_ambiguous_generic_fix_does_not_guess():
    skill, _score, _reason = playbook_skills.match_playbook("Please fix this issue")
    assert skill is None
