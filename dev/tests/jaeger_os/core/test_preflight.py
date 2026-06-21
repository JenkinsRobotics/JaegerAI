"""Environment preflight — dependency + system-library verification.

pip can't install system libraries (PortAudio) or macOS binaries;
preflight checks the whole surface and reports the exact fix command,
so a missing dependency surfaces at boot, not mid-conversation.
"""

from __future__ import annotations

import json
import types

from jaeger_os.core.runtime.preflight import (
    Check,
    _check_memory_integrity,
    _check_skills_health,
    _check_tool_registry,
    boot_warning,
    check_environment,
    check_instance,
    fixable,
    format_report,
    missing,
    report_as_json,
)


def test_check_environment_covers_every_category():
    checks = check_environment()
    cats = {c.category for c in checks}
    # voice / vision / external / memory / messaging Python deps + system
    for expected in ("voice", "vision", "external", "system"):
        assert expected in cats, expected
    # The audio backend probe + git are always present.  0.3.0 renamed
    # the audio check from "PortAudio" to "audio I/O" because the
    # default backend on macOS is now AVAudioEngine (via avaudio_io)
    # with PortAudio kept as the cross-platform fallback — the check
    # probes whichever one is in use.
    names = {c.name for c in checks}
    assert "audio I/O" in names and "git" in names


def test_missing_returns_only_failures():
    checks = [
        Check("a", "voice", ok=True),
        Check("b", "vision", ok=False, fix="pip install x"),
    ]
    bad = missing(checks)
    assert len(bad) == 1 and bad[0].name == "b"


def test_report_clean_when_all_ok():
    report = format_report([Check("a", "voice", ok=True, detail="installed")])
    assert "fully operational" in report
    assert boot_warning([Check("a", "voice", ok=True)]) == ""


def test_report_and_boot_warning_surface_fixes():
    checks = [
        Check("kokoro", "voice", ok=False, detail="not installed",
              fix='pip install "jaeger-os[voice]"',
              fix_cmd=["python", "-m", "pip", "install", "kokoro"]),
        Check("PortAudio", "system", ok=False, detail="native load failed",
              fix="brew install portaudio",
              fix_cmd=["brew", "install", "portaudio"]),
    ]
    report = format_report(checks)
    assert 'pip install "jaeger-os[voice]"' in report
    assert "brew install portaudio" in report

    warning = boot_warning(checks)
    assert "kokoro" in warning and "PortAudio" in warning
    assert "--doctor" in warning  # boot points at the doctor to fix


def _write_config(tmp_path, *, model_path="dummy.gguf", ctx=8192):
    """Write a minimal but valid instance config.yaml under tmp_path."""
    import yaml
    cfg = {"model": {"path": str(model_path), "ctx": ctx}}
    (tmp_path / "config.yaml").write_text(yaml.safe_dump(cfg), encoding="utf-8")


def _layout(tmp_path):
    return types.SimpleNamespace(root=tmp_path, logs_dir=tmp_path / "logs")


def test_check_instance_flags_missing_config(tmp_path):
    """A fresh dir with no config.yaml gets one decisive failure
    instead of cascading checks against parsed config."""
    out = check_instance(_layout(tmp_path))
    cfg_checks = [c for c in out if c.name == "config.yaml"]
    assert cfg_checks and cfg_checks[0].ok is False
    # No model.path / model.ctx checks emitted when there's no config to read.
    assert not any(c.name in {"model.path", "model.ctx"} for c in out)


def test_check_instance_flags_missing_model_file(tmp_path):
    """A config that points at a model that can't be resolved (not a
    registry key, not a file on disk) must surface as a failure — this
    is the #1 broken-instance symptom."""
    _write_config(tmp_path, model_path="/nope/never/here.gguf")
    out = check_instance(_layout(tmp_path))
    model_checks = [c for c in out if c.name == "model.path"]
    assert model_checks and model_checks[0].ok is False
    assert "unresolved" in model_checks[0].detail


def test_check_instance_passes_when_model_file_exists(tmp_path):
    """Real model file + sane ctx → green across instance checks."""
    fake_model = tmp_path / "real.gguf"
    fake_model.write_bytes(b"x" * 1024)
    _write_config(tmp_path, model_path=fake_model, ctx=8192)
    out = check_instance(_layout(tmp_path))
    instance_checks = [c for c in out if c.category == "instance"]
    assert all(c.ok for c in instance_checks), [c for c in instance_checks if not c.ok]


def test_check_instance_flags_implausibly_small_ctx(tmp_path):
    """ctx below 2048 won't fit most prompts — surface it as a warning."""
    fake_model = tmp_path / "m.gguf"
    fake_model.write_bytes(b"x")
    _write_config(tmp_path, model_path=fake_model, ctx=512)
    out = check_instance(_layout(tmp_path))
    ctx_checks = [c for c in out if c.name == "model.ctx"]
    assert ctx_checks and ctx_checks[0].ok is False


def test_check_instance_flags_unparseable_config(tmp_path):
    """A config.yaml that doesn't parse short-circuits later checks."""
    (tmp_path / "config.yaml").write_text("model: {ctx: 8192\n", encoding="utf-8")
    out = check_instance(_layout(tmp_path))
    cfg_checks = [c for c in out if c.name == "config.yaml"]
    assert cfg_checks and cfg_checks[0].ok is False


# ── new doctor checks (daemon / memory / tools / skills / json) ────


def _instance_layout(tmp_path):
    """Minimal layout duck-type for the new doctor checks."""
    return types.SimpleNamespace(
        root=tmp_path,
        memory_dir=tmp_path / "memory",
        skills_dir=tmp_path / "skills",
        logs_dir=tmp_path / "logs",
        config_path=tmp_path / "config.yaml",
    )


def test_memory_integrity_passes_for_fresh_instance(tmp_path):
    """Fresh instance — no memory files yet. Doctor reports absent
    files as PASS (they get created on first write) rather than
    failures."""
    out = _check_memory_integrity(_instance_layout(tmp_path))
    assert all(c.ok for c in out), \
        f"fresh instance should pass: {[c.detail for c in out if not c.ok]}"


def test_memory_integrity_flags_corrupted_json(tmp_path):
    """A board.json that doesn't parse must surface a decisive FAIL
    so the user can fix or restore before the agent trips over it
    mid-conversation."""
    mem = tmp_path / "memory"
    mem.mkdir(parents=True, exist_ok=True)
    (mem / "board.json").write_text("{ this is not json", encoding="utf-8")
    out = _check_memory_integrity(_instance_layout(tmp_path))
    board_rows = [c for c in out if c.name == "memory/board.json"]
    assert board_rows and board_rows[0].ok is False
    assert "corrupted" in board_rows[0].detail.lower()


def test_memory_integrity_passes_for_valid_json(tmp_path):
    """A well-formed JSON file passes with a size detail."""
    mem = tmp_path / "memory"
    mem.mkdir(parents=True, exist_ok=True)
    (mem / "facts.json").write_text('{"k": "v"}', encoding="utf-8")
    out = _check_memory_integrity(_instance_layout(tmp_path))
    facts_rows = [c for c in out if c.name == "memory/facts.json"]
    assert facts_rows and facts_rows[0].ok is True


def test_tool_registry_check_no_agent_reports_skip(tmp_path):
    """Without a booted agent the check can't resolve CORE / LEAN_CORE
    names (they're the agent-facing aliases registered at boot time,
    not the function symbols in jaeger_os.agent.tools). The check
    surfaces a single 'not checked' row so the doctor stays useful
    when run from the CLI without a live session."""
    out = _check_tool_registry()
    assert len(out) == 1
    row = out[0]
    assert row.name == "tools.registry"
    assert row.ok is True
    assert "not checked" in row.detail.lower()


def test_tool_registry_check_with_booted_agent(monkeypatch):
    """When the agent IS booted, the check inspects its registered
    tool names and reports unresolved CORE / LEAN_CORE entries as
    failures. We simulate a healthy boot by injecting a fake agent
    whose registry covers everything in both tiers."""
    from jaeger_os.agent.skill_registry.toolset_scoping import CORE, LEAN_CORE
    fake_registry = dict.fromkeys(CORE | LEAN_CORE, "stub")

    class _FakeToolset:
        def __init__(self, tools): self.tools = tools

    class _FakeAgent:
        _function_toolset = _FakeToolset(fake_registry)

    from jaeger_os.main import _pipeline
    monkeypatch.setitem(_pipeline, "agent", _FakeAgent())
    out = _check_tool_registry()
    # Both tiers produce a row, both pass.
    names = {c.name for c in out}
    assert "tools.CORE" in names
    assert "tools.LEAN_CORE" in names
    assert all(c.ok for c in out)


def test_tool_registry_check_surfaces_missing_names(monkeypatch):
    """A registry missing a CORE name is the regression we care about
    — a rename that broke the lean filter silently. The check must
    name the missing entries so the user knows what to re-register."""
    fake_registry = {"get_time": "stub"}  # deliberately tiny

    class _FakeToolset:
        def __init__(self, tools): self.tools = tools

    class _FakeAgent:
        _function_toolset = _FakeToolset(fake_registry)

    from jaeger_os.main import _pipeline
    monkeypatch.setitem(_pipeline, "agent", _FakeAgent())
    out = _check_tool_registry()
    failing = [c for c in out if not c.ok]
    assert failing, "missing CORE names should produce at least one failure"
    # The failure detail enumerates SPECIFIC missing names — not a
    # generic 'tools missing' string.
    assert any("calculate" in c.detail or "memory" in c.detail
               for c in failing)


def test_skills_health_returns_at_least_one_row(tmp_path):
    """Even with no skills the doctor reports the (zero-)count row
    rather than skipping skills entirely. Users want to see all the
    checks, including 'nothing to check'."""
    out = _check_skills_health(_instance_layout(tmp_path))
    assert out
    # Fresh instance — discovery returns 0 skills, surfaced as PASS.
    assert all(c.ok for c in out)


def test_report_as_json_emits_stable_shape(tmp_path):
    """The JSON report has a fixed top-level shape so a monitoring
    script can rely on it. Schema: ``ok / total / passed / failed /
    checks[].{name, category, ok, detail, fix, fix_cmd}``."""
    checks = [
        Check("a", "voice", ok=True, detail="installed"),
        Check("b", "vision", ok=False, detail="missing",
              fix="pip install x",
              fix_cmd=["pip", "install", "x"]),
    ]
    payload = json.loads(report_as_json(checks))
    assert payload["ok"] is False
    assert payload["total"] == 2
    assert payload["passed"] == 1
    assert payload["failed"] == 1
    assert {"name", "category", "ok", "detail", "fix", "fix_cmd"} <= \
        set(payload["checks"][0].keys())


def test_check_instance_includes_every_new_category(tmp_path):
    """The unified ``check_instance`` must return rows from every new
    category (memory / runtime / skills) on top of the
    classic env + instance-config rows. A regression that drops one
    of these would silently shrink the doctor."""
    # Seed a minimal config so the instance path is exercised.
    import yaml
    fake_model = tmp_path / "m.gguf"
    fake_model.write_bytes(b"x")
    (tmp_path / "config.yaml").write_text(
        yaml.safe_dump({"model": {"path": str(fake_model), "ctx": 8192}}),
        encoding="utf-8",
    )
    out = check_instance(_instance_layout(tmp_path))
    cats = {c.category for c in out}
    for required in ("instance", "memory", "runtime", "skills"):
        assert required in cats, \
            f"check_instance dropped category {required!r}: have {sorted(cats)}"


def test_fixable_dedups_runnable_commands():
    """fixable() returns the runnable argv for each missing check that
    has one — what --doctor offers to run. No fix_cmd → not offered."""
    checks = [
        Check("kokoro", "voice", ok=False,
              fix_cmd=["pip", "install", "kokoro"]),
        Check("kokoro", "voice", ok=False,            # dup → collapsed
              fix_cmd=["pip", "install", "kokoro"]),
        Check("git", "system", ok=False),             # no fix_cmd → skipped
        Check("scipy", "voice", ok=True),             # ok → skipped
    ]
    cmds = fixable(checks)
    assert cmds == [["pip", "install", "kokoro"]]
