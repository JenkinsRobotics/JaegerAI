"""Self-update tools — set_name / update_soul input validation.

The happy path writes identity.yaml / soul.md at the instance root and
needs a bound layout; the validation guards (which run before any file
access) are the unit-testable surface and the part that keeps a small
model from corrupting its own identity.
"""

from __future__ import annotations

from jaeger_ai.agent.tools.identity_tools import set_name, update_soul


def test_set_name_rejects_empty() -> None:
    r = set_name("   ")
    assert r["ok"] is False and "empty" in r["error"]


def test_set_name_rejects_path_characters() -> None:
    r = set_name("Erin/Jaeger")
    assert r["ok"] is False and "illegal" in r["error"]


def test_set_name_rejects_overlong() -> None:
    r = set_name("E" * 65)
    assert r["ok"] is False and "long" in r["error"]


def test_update_soul_rejects_empty() -> None:
    r = update_soul("")
    assert r["ok"] is False and "empty" in r["error"]


def test_update_soul_rejects_overlong() -> None:
    r = update_soul("x" * 8001)
    assert r["ok"] is False and "long" in r["error"]
