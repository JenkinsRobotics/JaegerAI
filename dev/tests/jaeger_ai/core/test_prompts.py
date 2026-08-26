"""System-prompt assembly — operating discipline + soul.md.

Covers the two agentic-reliability additions mined from hermes-agent:
the always-on OPERATING_DISCIPLINE block, and the optional per-instance
`soul.md` free-form character doc that complements identity.yaml.
"""

from __future__ import annotations

from jaeger_ai.core.instance.instance import InstanceLayout
from jaeger_agent.prompts.prompts import _load_soul, build_system_prompt


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


def test_active_character_persona_stays_out_of_worker_prompt(tmp_path) -> None:
    """Workers run vanilla EXCEPT the name: the agent's NAME (identity.yaml)
    is a fact (the output filter preserves facts verbatim, so a wrong name
    can't be fixed downstream) and flows into the prompt as one line. The
    persona BLOCK (soul/traits/voice) still stays out — it's applied by the
    two-pass output filter, never the execution context. See
    dev/docs/reality/persona_compiler.md."""
    (tmp_path / "identity.yaml").write_text(
        "name: Jarvis\nrole: assistant\npersonality: plain\n",
        encoding="utf-8",
    )
    sp = build_system_prompt(InstanceLayout(root=tmp_path))
    assert "Your name is Jarvis." in sp          # name-only fragment
    assert "## My voice —" not in sp             # compiled persona stays out
    # No persona prose leaks alongside the name (Jarvis' sheet mentions
    # neither of these outside the compiled block, so absence is the canary).
    assert "butler" not in sp.lower()


def test_the_active_character_supplies_the_name(tmp_path, monkeypatch) -> None:
    """Operator decision, 2026-08-19, reversing 2026-07-05: while a
    character is selected the agent IS that character, and its name is the
    only name in the prompt. The old rule kept identity.yaml's name no
    matter what, so the prompt said "you are Ted" while the persona block
    said "you are HAL 9000" — and the model, asked who it was, reported
    the conflict. The old JAEGER_BENCH_NEUTRAL_IDENTITY flag stays a
    no-op.

    Only the NEUTRAL sheet yields the name back to identity.yaml — see
    :func:`jaeger_ai.personality.character.persona_display_name` and
    dev/tests/jaeger_ai/core/test_prompt_identity.py.
    """
    import jaeger_ai.personality.character as character
    from jaeger_ai.core.prompt_identity import register_agent_identity

    # This file builds prompts through the DEPENDENCY's assembler directly;
    # at runtime jaeger_ai.main.build_system_prompt registers JaegerAI's
    # fragments first. Idempotent, so calling it here just makes the test
    # independent of whichever module registered earlier in the session.
    register_agent_identity()

    class _Hal:
        name = "HAL 9000"
        neutral = False

    monkeypatch.setattr(character, "active_character", lambda root: _Hal())
    (tmp_path / "identity.yaml").write_text(
        "name: Ted\nrole: assistant\npersonality: plain\n",
        encoding="utf-8",
    )
    sp = build_system_prompt(InstanceLayout(root=tmp_path))
    assert "Your name is HAL 9000." in sp        # the character is the agent
    assert "Your name is Ted." not in sp         # never both

    monkeypatch.setenv("JAEGER_BENCH_NEUTRAL_IDENTITY", "1")
    sp = build_system_prompt(InstanceLayout(root=tmp_path))
    assert "Your name is HAL 9000." in sp        # flag changes nothing


def test_the_neutral_sheet_leaves_the_instance_name_alone(
    tmp_path, monkeypatch,
) -> None:
    """The other half of the same rule: ``assistant`` is nobody in
    particular, so identity.yaml comes through — "Ted, a plain
    assistant" is still expressible, it is just a choice now."""
    import jaeger_ai.personality.character as character
    from jaeger_ai.core.prompt_identity import register_agent_identity

    register_agent_identity()

    class _Assistant:
        name = "Assistant"
        neutral = True

    monkeypatch.setattr(character, "active_character", lambda root: _Assistant())
    (tmp_path / "identity.yaml").write_text(
        "name: Ted\nrole: assistant\npersonality: plain\n",
        encoding="utf-8",
    )
    sp = build_system_prompt(InstanceLayout(root=tmp_path))
    assert "Your name is Ted." in sp
    assert "Your name is Assistant." not in sp


def test_no_soul_md_still_builds_a_prompt(tmp_path) -> None:
    """soul.md is optional — absent, the prompt is still well-formed."""
    sp = build_system_prompt(InstanceLayout(root=tmp_path))
    # The mandatory memory-persist rule is the canary that the
    # framework rule block made it into the prompt.
    assert 'memory(action="remember"' in sp


def test_prompt_defaults_to_full_tool_surface(tmp_path, monkeypatch) -> None:
    """Unset flag: the prompt says the full surface is visible."""
    monkeypatch.delenv("JAEGER_TOOLSET_SCOPING", raising=False)
    monkeypatch.delenv("JAEGER_FULL_TOOLS", raising=False)
    sp = build_system_prompt(InstanceLayout(root=tmp_path))
    assert "full built-in tool surface is visible" in sp
    assert "TOOL CATALOG" not in sp


def test_prompt_scoped_when_explicit_env(tmp_path, monkeypatch) -> None:
    """``JAEGER_TOOLSET_SCOPING=1`` opts into the lean surface — the
    model sees CORE + a one-line-per-category catalog, can peek at any
    schema via ``describe_tool``, and widen via ``load_tools``.
    Useful for context-tight runs; not the default while routing
    regressions are open."""
    monkeypatch.setenv("JAEGER_TOOLSET_SCOPING", "1")
    monkeypatch.delenv("JAEGER_FULL_TOOLS", raising=False)
    sp = build_system_prompt(InstanceLayout(root=tmp_path))
    assert "small CORE set of tools" in sp
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
    from jaeger_agent.skill_registry.toolset_scoping import CORE, TOOLSETS
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
    from jaeger_ai.main import SKIP_FINAL_TOOLS
    assert SKIP_FINAL_TOOLS == frozenset(), (
        "SKIP_FINAL_TOOLS must stay empty. Adding tools back here "
        "produces robotic answers AND silently breaks any rule "
        "that uses the tool as a preparation step. Don't re-add."
    )
