"""Every imported Codex skill is a discoverable, attributed playbook skill."""
from __future__ import annotations

import json
from collections import Counter

from jaeger_agent.skill_registry import playbook_skills
from jaeger_agent.skill_registry.playbook_skills import discover_playbooks

CODEX_ROOT = playbook_skills._SKILLS_DIR / "codex"


def _codex_skills():
    return [s for s in discover_playbooks() if CODEX_ROOT in s.path.parents]


def test_every_imported_skill_folder_is_discovered():
    on_disk = {p.resolve() for p in CODEX_ROOT.rglob("SKILL.md")}
    found = {s.path.resolve() for s in _codex_skills()}
    assert on_disk, "no Codex skills imported"
    assert on_disk == found, sorted(str(p) for p in on_disk - found)


def test_discovery_never_shadows_a_skill_by_name():
    """Discovery keys by name: a repeated name would silently drop a skill."""
    names = Counter(s.name for s in discover_playbooks())
    assert [n for n, c in names.items() if c > 1] == []
    on_disk = sum(1 for _ in CODEX_ROOT.rglob("SKILL.md"))
    assert len(_codex_skills()) == on_disk


def test_imported_skills_do_not_widen_the_default_routing_surface():
    assert {s.lifecycle for s in _codex_skills()} == {"optional"}


def test_every_imported_skill_carries_provenance_and_license_state():
    for md in CODEX_ROOT.rglob("SKILL.md"):
        prov = json.loads((md.parent / ".provenance.json").read_text())
        assert prov["source"] and prov["origin_path"] and prov["skill_md_sha256"]
        assert prov["license"] in {"Apache-2.0", "MIT", "see-license-file", "none-declared"}
        if prov["license"] != "none-declared":
            source_dir = md.parent
            while source_dir.parent != CODEX_ROOT:
                source_dir = source_dir.parent
            assert (source_dir / f"LICENSE.{prov['source']}").is_file(), prov["source"]


def test_renamed_collisions_keep_their_original_name():
    for md in CODEX_ROOT.rglob("SKILL.md"):
        prov = json.loads((md.parent / ".provenance.json").read_text())
        if prov["name"] != prov["original_name"]:
            assert ":" in prov["name"] and prov["name"].endswith(prov["original_name"])
