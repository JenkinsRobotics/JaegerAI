"""Registry-grade metadata on ``ToolDef`` + alias resolution.

Pins the new fields added in the "registry maturity" pass:

  * ``toolset`` / ``permission_tier`` / ``side_effect`` /
    ``max_result_chars`` defaults preserve old callers
  * ``check_fn`` is honoured by ``is_available()``
  * ``requires_env`` falls back to env-var presence when no
    ``check_fn`` is set
  * explicit ``_TOOL_ALIASES`` redirects pre-rename names to their
    canonical targets when the target is registered AND the alias
    isn't
"""

from __future__ import annotations

import os

import pytest
from pydantic import BaseModel

from jaeger_ai.agent.dialects import normalize_tool_name
from jaeger_os.core.tools.tool_schema import ToolDef


class _Args(BaseModel):
    x: int = 0


def _td(**kw) -> ToolDef:
    """Build a minimal ToolDef with sensible defaults for the test."""
    defaults = dict(
        name="probe",
        description="test tool",
        args_model=_Args,
        fn=lambda x=0: x,
    )
    defaults.update(kw)
    return ToolDef(**defaults)


# ── defaults preserve old callers ──────────────────────────────────


def test_defaults_match_pre_metadata_construction():
    """A ToolDef built with only the legacy positional/keyword args
    must still construct cleanly — none of the new fields can be
    REQUIRED or the 60+ existing call sites would break."""
    t = _td()
    assert t.toolset == ""
    assert t.permission_tier == ""
    # "" = unclassified — the conservative default. The old "read"
    # default silently classified every unannotated tool as
    # side-effect-free, which would have made the loop parallel-
    # dispatch and dedup write-side tools.
    assert t.side_effect == ""
    assert t.max_result_chars == 0
    assert t.check_fn is None
    assert t.requires_env == ()
    assert t.examples == ()


# ── is_available() ─────────────────────────────────────────────────


def test_is_available_default_true_when_no_constraints():
    assert _td().is_available() is True


def test_is_available_honours_explicit_check_fn():
    assert _td(check_fn=lambda: True).is_available() is True
    assert _td(check_fn=lambda: False).is_available() is False


def test_is_available_treats_check_fn_exception_as_unavailable():
    """A probe that crashes must NOT propagate — the rest of the
    tool surface stays healthy and the offending tool just reports
    unavailable."""
    def _boom():
        raise RuntimeError("synthetic")
    assert _td(check_fn=_boom).is_available() is False


def test_is_available_falls_back_to_requires_env(monkeypatch):
    """With no check_fn but requires_env declared, every named env
    var must be present and non-empty."""
    monkeypatch.delenv("PROBE_SECRET", raising=False)
    assert _td(requires_env=("PROBE_SECRET",)).is_available() is False
    monkeypatch.setenv("PROBE_SECRET", "value")
    assert _td(requires_env=("PROBE_SECRET",)).is_available() is True


def test_is_available_check_fn_wins_over_requires_env(monkeypatch):
    """When both are set, check_fn wins — it's the more specific
    signal."""
    monkeypatch.delenv("MISSING_VAR", raising=False)
    t = _td(check_fn=lambda: True, requires_env=("MISSING_VAR",))
    assert t.is_available() is True


# ── alias resolution ──────────────────────────────────────────────


def test_alias_redirects_run_python_to_execute_code():
    """Phase-9 rename: ``run_python`` → ``execute_code``. A model
    that emits the old name should land on the new tool when the
    target is registered."""
    valid = frozenset({"execute_code", "get_time"})
    assert normalize_tool_name("run_python", valid) == "execute_code"


def test_alias_redirects_speak_to_text_to_speech():
    valid = frozenset({"text_to_speech", "get_time"})
    assert normalize_tool_name("speak", valid) == "text_to_speech"


def test_alias_does_not_fire_when_target_is_not_registered():
    """The alias table only redirects to names that exist. If the
    target isn't registered, return the original so dispatch
    surfaces a clean "unknown tool" instead of silently routing
    to a nonexistent name."""
    valid = frozenset({"get_time"})  # no execute_code
    assert normalize_tool_name("run_python", valid) == "run_python"


def test_alias_does_not_fire_when_old_name_is_still_registered():
    """If BOTH the alias source and target are registered, the
    exact-match short-circuit returns the source. The model's
    explicit name wins over the alias table."""
    valid = frozenset({"run_python", "execute_code"})
    assert normalize_tool_name("run_python", valid) == "run_python"
