"""System-prompt assembly — operating discipline + soul.md.

Covers the two agentic-reliability additions mined from hermes-agent:
the always-on OPERATING_DISCIPLINE block, and the optional per-instance
`soul.md` free-form character doc that complements identity.yaml.
"""

from __future__ import annotations

from jaeger_os.core.instance.instance import InstanceLayout
from jaeger_os.agent.prompts.prompts import _load_soul, build_system_prompt


# ── operating discipline ────────────────────────────────────────────


def test_operating_discipline_in_system_prompt(tmp_path) -> None:
    sp = build_system_prompt(InstanceLayout(root=tmp_path))
    # Operating-discipline rules now live in the consolidated
    # framework_agent.md; pin their substance, not the old heading.
    assert "ANSWER THE CURRENT MESSAGE" in sp
    assert "EXECUTE, don't promise" in sp


# ── soul.md ─────────────────────────────────────────────────────────


def test_load_soul_absent_is_empty(tmp_path) -> None:
    assert _load_soul(InstanceLayout(root=tmp_path)) == ""


def test_load_soul_reads_the_file(tmp_path) -> None:
    (tmp_path / "soul.md").write_text("## Voice\nWarm and direct.", encoding="utf-8")
    soul = _load_soul(InstanceLayout(root=tmp_path))
    assert "Warm and direct" in soul


def test_load_soul_caps_runaway_length(tmp_path) -> None:
    """A huge soul.md must not crowd out the routing imperatives."""
    (tmp_path / "soul.md").write_text("x" * 9000, encoding="utf-8")
    soul = _load_soul(InstanceLayout(root=tmp_path))
    assert len(soul) < 5000
    assert "truncated" in soul


def test_active_character_persona_folds_into_the_system_prompt(tmp_path) -> None:
    """Characters are the only persona now — the active character (default
    Jarvis) drives identity/soul; the instance no longer reads soul.md."""
    sp = build_system_prompt(InstanceLayout(root=tmp_path))
    assert "Jarvis" in sp


def test_no_soul_md_still_builds_a_prompt(tmp_path) -> None:
    """soul.md is optional — absent, the prompt is still well-formed."""
    sp = build_system_prompt(InstanceLayout(root=tmp_path))
    # The mandatory memory-persist rule is the canary that the
    # framework rule block made it into the prompt.
    assert 'memory(action="remember"' in sp


def test_prompt_defaults_to_unscoped_tool_surface(tmp_path, monkeypatch) -> None:
    """Default is UNSCOPED — full tool surface visible to the model.

    History: we briefly flipped this to SCOPED-by-default after adding
    ``describe_tool`` + the catalog, but a/b benching against v5 showed
    Gemma 4 26B-A4B routing accuracy dropped from 100% to 67.6% under
    the new default. Reverted to unscoped (opt-in via env) until
    auto-load-on-intent lands. See docs/lean_surface.md and the
    code_review_2026_05_24 disposition doc for context."""
    monkeypatch.delenv("JAEGER_TOOLSET_SCOPING", raising=False)
    monkeypatch.delenv("JAEGER_FULL_TOOLS", raising=False)
    sp = build_system_prompt(InstanceLayout(root=tmp_path))
    assert "full built-in tool surface is visible" in sp
    assert "focused CORE set of tools" not in sp
    assert "TOOL CATALOG" not in sp


def test_prompt_scoped_when_explicit_env(tmp_path, monkeypatch) -> None:
    """``JAEGER_TOOLSET_SCOPING=1`` opts into the lean surface — the
    model sees CORE + a one-line-per-category catalog, can peek at any
    schema via ``describe_tool``, and widen via ``load_toolset``.
    Useful for context-tight runs; not the default while routing
    regressions are open."""
    monkeypatch.setenv("JAEGER_TOOLSET_SCOPING", "1")
    monkeypatch.delenv("JAEGER_FULL_TOOLS", raising=False)
    sp = build_system_prompt(InstanceLayout(root=tmp_path))
    assert "focused CORE set of tools" in sp
    assert "TOOL CATALOG" in sp
    assert "describe_tool" in sp


def test_prompt_full_tools_env_overrides_explicit_scoping(tmp_path, monkeypatch) -> None:
    """``JAEGER_FULL_TOOLS=1`` is the kill-switch — wins even when
    ``JAEGER_TOOLSET_SCOPING=1`` asks for the lean surface. Used by
    bench harnesses that want guaranteed parity across env."""
    monkeypatch.setenv("JAEGER_FULL_TOOLS", "1")
    monkeypatch.setenv("JAEGER_TOOLSET_SCOPING", "1")
    sp = build_system_prompt(InstanceLayout(root=tmp_path))
    assert "full built-in tool surface is visible" in sp
    assert "TOOL CATALOG" not in sp


def test_prompt_unscoped_when_toolset_scoping_env_disabled(tmp_path, monkeypatch) -> None:
    """Explicit ``JAEGER_TOOLSET_SCOPING=0`` is the older way to opt out."""
    monkeypatch.setenv("JAEGER_TOOLSET_SCOPING", "0")
    monkeypatch.delenv("JAEGER_FULL_TOOLS", raising=False)
    sp = build_system_prompt(InstanceLayout(root=tmp_path))
    assert "full built-in tool surface is visible" in sp


# ── regression pins for tool-usage rules (2026-05-26) ─────────────
# Surfaced from live user testing: agent set ``*/5 * * * *`` for
# "schedule X 5 minutes from now" (cron fires on clock 5-minute
# marks, not five minutes after the request); skipped ``get_time``
# before computing the schedule; muddled one-shot vs recurring. The
# system prompt now teaches the right pattern. Pin the directives
# so a future cleanup of framework_agent.md doesn't silently drop them.


def test_schedule_rule_requires_get_time_first(tmp_path) -> None:
    """The system prompt must direct the agent to call ``get_time``
    before building a cron expression from a relative or absolute
    time. Without this, the model guesses the clock and the schedule
    lands at the wrong wall time."""
    sp = build_system_prompt(InstanceLayout(root=tmp_path))
    assert "schedule_prompt" in sp
    assert "get_time" in sp
    # Must explicitly call out that the call comes FIRST.
    schedule_block = sp[sp.index("schedule_prompt"):]
    assert "FIRST" in schedule_block[:600], (
        "the tool-usage rules should tell the model to call get_time FIRST "
        "when scheduling a relative/absolute time"
    )


def test_schedule_rule_disambiguates_oneshot_vs_recurring(tmp_path) -> None:
    """The agent must distinguish 'in 5 minutes' (one-shot) from
    'every 5 minutes' (recurring) — these have completely different
    cron expressions and the agent conflated them in live testing."""
    sp = build_system_prompt(InstanceLayout(root=tmp_path))
    # Both patterns called out explicitly.
    assert "one-shot" in sp.lower() or "ONE-SHOT" in sp
    assert "recurring" in sp.lower() or "RECURRING" in sp
    # Must warn about the */5 trap specifically.
    assert "*/5 * * * *" in sp
    assert "clock" in sp.lower()  # "clock 5-minute marks"


def test_self_check_is_exposed_to_agent() -> None:
    """``self_check`` (the agent's doctor) IS exposed — in the
    ``diagnostics`` toolset, loaded on demand like ``run_benchmark``.

    History: the original ``system_health`` tool was pulled from the
    agent surface because "do a self check" stalled in prefill (the
    model dithered between ``system_health`` and ``system_status`` and
    llama.cpp's Metal sampler hung at high first-token entropy). The
    2026-06-20 rename to ``self_check`` + this generation's engine/gemma
    fixes removed the stall — verified live: "do a self check" routes in
    ~0.2s TTFT. So the doctor is agent-runnable again, paired with
    ``run_benchmark`` (substrate health vs. answer quality).

    The old ``system_health`` name must be gone everywhere."""
    from jaeger_os.agent.skill_registry.toolset_scoping import CORE, TOOLSETS
    diagnostics = TOOLSETS.get("diagnostics", frozenset())
    assert "self_check" in diagnostics, (
        "self_check (the agent doctor) must be in the diagnostics toolset"
    )
    assert "system_health" not in CORE, "system_health was renamed to self_check"
    for ts in TOOLSETS.values():
        assert "system_health" not in ts, "stale system_health name in a toolset"


def test_skip_final_tools_is_empty() -> None:
    """Skip-final is DISABLED — the set must stay empty so every
    turn runs the full agent loop. Re-adding any tool here means:

      (a) the model's reasoning is bypassed for that tool — the
          120-token bounded formatter produces robotic answers
          ("workspace/haiku.txt", "2026-05-26 10:13:19 PM PDT")
          instead of conversational ones
      (b) any rule that uses the tool as a PREPARATION step (e.g.
          "call get_time before schedule_prompt") silently breaks,
          because skip-final exits the loop after the first tool
          call

    We removed the mechanism 2026-05-26 after live testing showed
    both failure modes. If you want fast-paths back, do it as an
    opt-in per-turn signal from the model, NOT a static list."""
    from jaeger_os.main import SKIP_FINAL_TOOLS
    assert SKIP_FINAL_TOOLS == frozenset(), (
        "SKIP_FINAL_TOOLS must stay empty. Adding tools back here "
        "produces robotic answers AND silently breaks any rule "
        "that uses the tool as a preparation step. Don't re-add."
    )
