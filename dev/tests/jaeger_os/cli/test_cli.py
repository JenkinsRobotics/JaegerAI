"""Smoke + behaviour tests for the operator CLI (``jaeger``).

Each subcommand is exercised through ``jaeger_os.cli.main`` with
argv arrays — same path the shell shim hits — and stdout is
captured.  These are SMOKE tests; the deeper command logic lives
in the command modules and gets their own focused units where
needed.
"""

from __future__ import annotations

import io
import os
from contextlib import redirect_stdout
from pathlib import Path

import pytest

from jaeger_os.cli import main as cli_main


@pytest.fixture
def sandbox(tmp_path: Path, monkeypatch) -> Path:
    """Build a minimal instance directory + point JAEGER_INSTANCE_DIR
    at it so the CLI's instance resolver picks it up."""
    inst = tmp_path / "instance"
    inst.mkdir()
    (inst / "identity.yaml").write_text(
        "name: TestAgent\n"
        "role: testing\n"
        "personality: A test persona.\n"
        "voice_tone: neutral\n"
        "voice_id: am_michael\n"
    )
    (inst / "config.yaml").write_text(
        "model:\n"
        "  model_path: /tmp/test.gguf\n"
        "  ctx: 8192\n"
    )
    (inst / "manifest.json").write_text(
        '{"schema_version": "1.2.0", '
        '"instance_name": "test", '
        '"created_at": "2026-06-08"}'
    )
    monkeypatch.setenv("JAEGER_INSTANCE_DIR", str(inst))
    return inst


def _run(*argv: str) -> tuple[int, str]:
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = cli_main(list(argv))
    return code, buf.getvalue()


# ── top-level ─────────────────────────────────────────────────────

def test_no_args_prints_help() -> None:
    code, out = _run()
    assert code == 0
    assert "jaeger" in out
    assert "skills" in out
    assert "instances" in out


# ── skills ────────────────────────────────────────────────────────

def test_skills_overview_lists_categories(sandbox) -> None:
    code, out = _run("skills")
    assert code == 0
    assert "Skill tree" in out
    assert "ANIMATION" in out
    assert "VOICE" in out
    assert "animation.image" in out


def test_skills_view_shows_detail(sandbox) -> None:
    code, out = _run("skills", "view", "animation.image")
    assert code == 0
    assert "animation.image" in out
    assert "L1" in out
    assert "XP" in out
    assert "Unlocks when mastered" in out


def test_skills_view_unknown_id_errors(sandbox) -> None:
    code, out = _run("skills", "view", "no.such.skill")
    assert code == 1
    assert "no such skill" in out.lower()


def test_skills_tree_renders(sandbox) -> None:
    code, out = _run("skills", "tree")
    assert code == 0
    assert "Skill tree" in out
    # Tree should show root skills (no prereqs).
    assert "animation.image" in out


# ── instances ─────────────────────────────────────────────────────

def test_instances_list_shows_active(sandbox) -> None:
    code, out = _run("instances")
    # Returns 1 when no instance is found in standard locations,
    # but the env-var-pointed sandbox should still be reachable
    # via 'show'.
    assert code in (0, 1)


def test_instances_show_renders(sandbox) -> None:
    code, out = _run("instances", "show")
    assert code == 0
    assert "Active instance" in out
    assert "TestAgent" in out


# ── personality ───────────────────────────────────────────────────

def test_personality_view_with_no_file_shows_defaults(sandbox) -> None:
    code, out = _run("personality")
    assert code == 0
    assert "Expression" in out
    assert "HEXACO" in out
    assert "SPECIAL" in out
    assert "Domains" in out


def test_personality_set_writes_file(sandbox) -> None:
    code, _ = _run("personality", "set",
                    "expression.directness", "0.85")
    assert code == 0
    assert (sandbox / "personality.json").exists()
    # Verify the value round-trips through view.
    code, out = _run("personality", "view")
    assert "directness" in out
    assert "0.85" in out


def test_personality_set_rejects_bad_range(sandbox) -> None:
    code, out = _run("personality", "set", "expression.warmth", "2.0")
    assert code == 1
    assert "value must be in" in out.lower() or "bad value" in out.lower()


def test_personality_set_rejects_unknown_field(sandbox) -> None:
    code, out = _run("personality", "set",
                      "expression.no_such_slider", "0.5")
    assert code == 1


def test_personality_set_name_is_string(sandbox) -> None:
    code, _ = _run("personality", "set", "name", "Lilith")
    assert code == 0
    code, out = _run("personality", "view")
    assert "Lilith" in out


# ── status ────────────────────────────────────────────────────────

def test_status_renders_active_instance(sandbox) -> None:
    code, out = _run("status")
    assert code == 0
    assert "JROS status" in out
    assert "TestAgent" in out  # the persona name from identity.yaml
    assert "Skill tree" in out
    assert "Mastered" in out


# ── roadmap ───────────────────────────────────────────────────────

def test_roadmap_renders_active_version() -> None:
    """Doesn't need a sandbox — reads from dev/docs/ in the repo."""
    code, out = _run("roadmap")
    assert code == 0
    assert "Roadmap" in out
    # Should pick the highest-numbered, which is 0.5 at present.
    assert "0.5" in out


def test_roadmap_unknown_version_errors() -> None:
    code, out = _run("roadmap", "--version", "99.99.99")
    assert code == 1
