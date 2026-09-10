"""Direct tests for the unified jaeger_ai.features.roundtable package."""
from jaeger_ai.features.roundtable import (
    TableService,
    member_session,
    MEMBERS,
    MODES,
    COLLABORATION_TASKS,
    plan,
    chair_for,
    decide,
    registry,
    Progress,
    budgets,
)


def test_roundtable_feature_exports():
    assert TableService is not None
    assert callable(member_session)
    assert MEMBERS == ("jaeger", "hermes", "openclaw")
    assert "ask" in MODES
    assert "collaborate" in MODES
    assert "vote" in MODES
    assert "analysis" in COLLABORATION_TASKS
    assert callable(plan)
    assert callable(chair_for)
    assert callable(decide)
    assert callable(registry)
    assert Progress is not None
    assert callable(budgets)


def test_roundtable_member_session_deterministic():
    s1 = member_session("test-table", "jaeger")
    s2 = member_session("test-table", "jaeger")
    assert s1 == s2
    assert isinstance(s1, str)
    assert len(s1) == 32
