"""/api/skills used to 500 on hermes-only imports (agent.skill_utils)."""
import sys
from pathlib import Path

# The WebUI server runs with its own dir on sys.path and imports ``api.*``.
sys.path.insert(0, str(Path(__file__).resolve().parents[5] / "jaeger_ai" / "features" / "webui"))
from api import routes, skill_scan  # noqa: E402


def _skill(root: Path, rel: str, fm: str, body: str = "Body line") -> None:
    d = root / rel
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(f"---\n{fm}\n---\n# Title\n{body}\n")


def test_skills_list_from_dir_no_hermes_modules(tmp_path, monkeypatch):
    monkeypatch.setattr(routes, "_get_disabled_skill_names_for_profile", lambda: {"beta"})
    _skill(tmp_path, "cat1/alpha", "name: alpha\ndescription: Does A\ntags: [x, y]")
    _skill(tmp_path, "beta", "name: beta")
    _skill(tmp_path, "winonly", "name: winonly\nplatforms: [windows]")
    _skill(tmp_path, "node_modules/junk", "name: junk")
    out = routes._skills_list_from_dir(tmp_path)
    names = {s["name"]: s for s in out["skills"]}
    assert out["success"] and set(names) == {"alpha", "beta"}
    assert names["alpha"]["description"] == "Does A"
    assert names["beta"]["description"] == "Body line" and names["beta"]["disabled"]


def test_skill_view_and_find(tmp_path):
    _skill(tmp_path, "cat1/alpha", "name: alpha\ndescription: Does A\ntags: [x, y]")
    d, md = routes._find_skill_in_dirs("alpha", [tmp_path])
    assert md and md.name == "SKILL.md"
    view = routes._skill_view_from_file(d, md)
    assert view["success"] and view["tags"] == ["x", "y"]


def test_frontmatter_parse_edge_cases():
    assert skill_scan.parse_frontmatter("no fm") == ({}, "no fm")
    fm, body = skill_scan.parse_frontmatter("---\nname: a\n---\nhello\n")
    assert fm == {"name": "a"} and body == "hello\n"
    assert skill_scan.parse_tags("a, b") == ["a", "b"]
