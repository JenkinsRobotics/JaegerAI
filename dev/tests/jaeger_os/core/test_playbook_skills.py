"""Playbook skills — discovery + the skill() tool.

The hermes skill library (markdown playbooks, often with embedded
shell/Python or a scripts/ folder) was imported into skills/. The
`skill` tool discovers and reads them ON DEMAND — they are never dumped
into the prompt, so the library can't bloat context.
"""

from __future__ import annotations

from jaeger_os.agent.skill_registry import playbook_skills as pb
from jaeger_os.agent.tools import skill


# ── discovery ────────────────────────────────────────────────────────


def test_playbooks_are_discovered() -> None:
    skills = pb.discover_playbooks()
    assert len(skills) >= 50           # 87 imported — generous floor
    assert all(s.name and s.path.name == "SKILL.md" for s in skills)


def test_a_skill_can_be_both_module_and_recipe() -> None:
    # Presence-based unification: a folder that ships a module (registers tools)
    # AND a SKILL.md is BOTH — its recipe is indexed too. No "code_skill vs
    # playbook" mutual exclusion. See dev/docs/skill_unification.md.
    names = {s.name for s in pb.discover_playbooks()}
    assert "computer_use" in names       # a module-providing skill's recipe...
    assert "macos_computer" in names     # ...is now surfaced via use_skill too


def test_find_playbook_is_fuzzy() -> None:
    s = pb.find_playbook("codebase")
    assert s is not None and "codebase" in s.name.lower()


# ── the skill() tool ─────────────────────────────────────────────────


def test_skill_list() -> None:
    """``list`` returns the FULL active catalog by default (limit=0) — the
    coordinator doesn't gate scope; the agent is the routing intelligence.
    ``total`` carries the full corpus count (≥50 for the bundled library)."""
    r = skill(action="list")
    assert r["ok"] is True
    assert r["total"] >= 50
    # Default is the complete list (no cap): every active skill returned.
    assert r["limit"] == 0
    assert len(r["skills"]) == r["total"]
    # Category counts are always included so the model can pick a
    # category before drilling in.
    assert isinstance(r["category_counts"], dict)
    assert r["category_counts"]


def test_skill_search_finds_by_keyword() -> None:
    r = skill(action="search", query="codebase")
    assert r["ok"] is True
    assert any("codebase" in s["name"].lower() for s in r["skills"])


def test_skill_search_needs_a_query() -> None:
    assert skill(action="search")["ok"] is False


def test_skill_view_returns_instructions() -> None:
    r = skill(action="view", name="codebase-inspection")
    assert r["ok"] is True
    assert "pygount" in r["instructions"].lower()


def test_skill_view_unknown_is_clean() -> None:
    assert skill(action="view", name="no-such-skill-xyz")["ok"] is False


def test_skill_unknown_action_is_clean() -> None:
    r = skill(action="teleport")
    assert r["ok"] is False and "unknown" in r["error"]


# ── scripts/ affordance (audit gap #9) ───────────────────────────────


def test_skill_view_lists_bundled_files() -> None:
    # view returns a `files` dict bucketing the skill's bundled files.
    r = skill(action="view", name="codebase-inspection")
    assert r["ok"] is True
    assert isinstance(r.get("files"), dict)


def test_bucket_skill_files_categorises(tmp_path) -> None:
    from jaeger_os.agent.tools.skills import _bucket_skill_files
    (tmp_path / "SKILL.md").write_text("# skill\n")
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "run.py").write_text("print(1)\n")
    (tmp_path / "notes.txt").write_text("misc\n")
    buckets = _bucket_skill_files(tmp_path)
    assert buckets["scripts"] == ["scripts/run.py"]
    assert buckets["other"] == ["notes.txt"]
    assert "SKILL.md" not in str(buckets)   # SKILL.md is excluded


def test_read_skill_file_reads_a_bundled_file(tmp_path) -> None:
    from jaeger_os.agent.tools.skills import _read_skill_file
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "go.sh").write_text("echo hi\n")
    r = _read_skill_file(tmp_path, "scripts/go.sh")
    assert r["ok"] is True and "echo hi" in r["content"]


def test_read_skill_file_rejects_escape(tmp_path) -> None:
    from jaeger_os.agent.tools.skills import _read_skill_file
    assert _read_skill_file(tmp_path, "../../etc/passwd")["ok"] is False
    assert _read_skill_file(tmp_path, "/etc/passwd")["ok"] is False


# ── skill provenance (audit gap #8) ──────────────────────────────────


def test_skill_origin_defaults_to_builtin(tmp_path) -> None:
    assert pb.read_skill_origin(tmp_path) == "builtin"


def test_mark_and_read_skill_origin_round_trip(tmp_path) -> None:
    pb.mark_skill_origin(tmp_path, "agent")
    assert pb.read_skill_origin(tmp_path) == "agent"


def test_mark_skill_origin_rejects_unknown(tmp_path) -> None:
    pb.mark_skill_origin(tmp_path, "nonsense")
    assert not (tmp_path / ".origin").exists()
    assert pb.read_skill_origin(tmp_path) == "builtin"


def test_discovered_playbooks_carry_an_origin() -> None:
    skills = pb.discover_playbooks()
    assert all(s.origin in ("builtin", "user", "agent", "marketplace")
               for s in skills)


def test_discover_playbooks_includes_instance_authored(tmp_path) -> None:
    """An agent-authored playbook in the bound instance's skills/ dir
    must be discovered — not just the bundled ones. (Agent writes are
    sandboxed to the instance, so this is where its playbooks land.)"""
    from jaeger_os.agent import tools
    from jaeger_os.core.instance.instance import InstanceLayout

    layout = InstanceLayout(root=tmp_path / "inst")
    layout.root.mkdir(parents=True, exist_ok=True)
    layout.ensure_dirs()
    tools.bind(layout)
    folder = layout.skills_dir / "my-playbook"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "SKILL.md").write_text(
        "---\nname: my-playbook\ndescription: an instance-authored skill\n"
        "---\nDo the thing.\n",
        encoding="utf-8",
    )
    found = {s.name: s for s in pb.discover_playbooks()}
    assert "my-playbook" in found
    assert found["my-playbook"].description == "an instance-authored skill"
