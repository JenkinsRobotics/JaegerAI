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


def test_frontmatter_parse_edge_cases():
    assert skill_scan.parse_frontmatter("no fm") == ({}, "no fm")
    fm, body = skill_scan.parse_frontmatter("---\nname: a\n---\nhello\n")
    assert fm == {"name": "a"} and body == "hello\n"
    assert skill_scan.parse_tags("a, b") == ["a", "b"]
