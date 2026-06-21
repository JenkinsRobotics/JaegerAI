"""``jaeger skill list`` + ``jaeger skill clone`` — INST-2 follow-up.

Pin the verb shape + the clone semantics (instance-wins-after-clone,
refuse-collision-without-force, helpful error for playbook skills).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from jaeger_os.cli.verbs import skill_verbs


def _seed_bundled(skills_root: Path, name: str, version: int = 1) -> Path:
    """Build a fake bundled tool-skill matching the `_v<N>` pattern.

    The skill loader requires the module file to be named ``<name>.py``
    (or ``skill.py`` / ``__init__.py``) — see ``_pick_module_file``.
    """
    folder = skills_root / f"{name}_v{version}"
    folder.mkdir(parents=True)
    (folder / "SKILL.md").write_text(f"# {name}\n", encoding="utf-8")
    (folder / f"{name}.py").write_text(
        'TOOLS = []\n\ndef setup():\n    return TOOLS\n',
        encoding="utf-8",
    )
    return folder


@pytest.fixture
def fake_layout(tmp_path, monkeypatch):
    """Wire a real layout into ``HOME`` so the resolver finds it."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("JAEGER_HOME", str(tmp_path))
    monkeypatch.delenv("JAEGER_INSTANCE_DIR", raising=False)
    monkeypatch.delenv("JAEGER_INSTANCE_NAME", raising=False)

    inst = tmp_path / ".jaeger_os" / "instances" / "default"
    inst.mkdir(parents=True)
    (inst / "identity.yaml").write_text("name: Test\nrole: r\npersonality: p\n",
                                         encoding="utf-8")
    (inst / "config.yaml").write_text(
        "instance_name: default\nmodel:\n  model_path: x\n  ctx: 32768\n",
        encoding="utf-8",
    )
    (inst / "manifest.json").write_text(
        '{"instance_name":"default","schema_version":"1.1.0"}',
        encoding="utf-8",
    )
    (inst / "skills").mkdir()

    return inst


@pytest.fixture
def fake_bundled(tmp_path, monkeypatch):
    """Monkeypatch ``CORE_SKILLS_DIR`` so the loader sees ONLY our
    fake bundled set — keeps the test self-contained."""
    bundled_root = tmp_path / "framework_skills"
    bundled_root.mkdir()
    _seed_bundled(bundled_root, "my_tool", version=1)
    _seed_bundled(bundled_root, "other_tool", version=2)
    from jaeger_os.agent.skill_registry import skill_loader as _sl
    monkeypatch.setattr(_sl, "CORE_SKILLS_DIR", bundled_root, raising=True)
    return bundled_root


# ── list ────────────────────────────────────────────────────────────


def test_skill_list_shows_bundled_zone(fake_layout, fake_bundled, capsys):
    rc = skill_verbs._skill_list([])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Tool-skills" in out
    assert "[bundled]" in out
    assert "my_tool" in out
    assert "other_tool" in out


def test_skill_list_shows_instance_zone_after_clone(fake_layout, fake_bundled, capsys):
    """After a successful clone, list should mark that name as
    ``[instance]`` — the resolver picked the instance copy."""
    rc = skill_verbs._skill_clone(["my_tool"])
    assert rc == 0, capsys.readouterr().err
    capsys.readouterr()  # discard clone output

    rc2 = skill_verbs._skill_list([])
    assert rc2 == 0
    out = capsys.readouterr().out
    # ``my_tool`` is now instance-zone; ``other_tool`` is still bundled.
    lines = [ln for ln in out.splitlines() if "my_tool" in ln]
    assert lines and "[instance]" in lines[0]
    other_lines = [ln for ln in out.splitlines() if "other_tool" in ln]
    assert other_lines and "[bundled]" in other_lines[0]


# ── clone ───────────────────────────────────────────────────────────


def test_clone_copies_skill_to_instance(fake_layout, fake_bundled, capsys):
    rc = skill_verbs._skill_clone(["my_tool"])
    assert rc == 0, capsys.readouterr().err
    dst = fake_layout / "skills" / "my_tool_v1"
    assert (dst / "SKILL.md").read_text() == "# my_tool\n"
    assert (dst / "my_tool.py").exists()


def test_clone_refuses_collision_without_force(fake_layout, fake_bundled, capsys):
    skill_verbs._skill_clone(["my_tool"])
    capsys.readouterr()  # discard

    rc = skill_verbs._skill_clone(["my_tool"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "already exists" in err


def test_clone_force_overwrites(fake_layout, fake_bundled, capsys):
    skill_verbs._skill_clone(["my_tool"])
    # Edit the cloned file so we can verify overwrite-takes-effect.
    edited = fake_layout / "skills" / "my_tool_v1" / "SKILL.md"
    edited.write_text("# I edited this", encoding="utf-8")

    rc = skill_verbs._skill_clone(["my_tool", "--force"])
    assert rc == 0
    assert edited.read_text() == "# my_tool\n"  # back to bundled


def test_clone_picks_highest_version_when_multiple(fake_layout, tmp_path, monkeypatch):
    bundled_root = tmp_path / "framework_skills"
    bundled_root.mkdir()
    _seed_bundled(bundled_root, "my_tool", version=1)
    _seed_bundled(bundled_root, "my_tool", version=2)  # newer
    from jaeger_os.agent.skill_registry import skill_loader as _sl
    monkeypatch.setattr(_sl, "CORE_SKILLS_DIR", bundled_root, raising=True)

    rc = skill_verbs._skill_clone(["my_tool"])
    assert rc == 0
    # v2 was picked, not v1.
    assert (fake_layout / "skills" / "my_tool_v2").exists()
    assert not (fake_layout / "skills" / "my_tool_v1").exists()


def test_clone_unknown_name_errors(fake_layout, fake_bundled, capsys):
    rc = skill_verbs._skill_clone(["nonexistent_tool"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "no bundled skill" in err


def test_clone_help_returns_0():
    rc = skill_verbs._skill_clone(["--help"])
    assert rc == 0


def test_clone_missing_name_returns_2(capsys):
    rc = skill_verbs._skill_clone([])
    assert rc == 2
    err = capsys.readouterr().err
    assert "usage:" in err
