from jaeger_ai.features.engines import catalog as c


def test_catalog_reads_skills_and_memory_without_secrets(tmp_path, monkeypatch):
    h = tmp_path / "hermes"; (h / "skills/research/deep").mkdir(parents=True)
    (h / "skills/research/deep/SKILL.md").write_text("---\nname: deep-research\ndescription: Dig in\n---\nbody")
    (h / "memories").mkdir(); (h / "memories/notes.md").write_text("remember")
    ws = tmp_path / "oc/workspace"; (ws / "skills/x").mkdir(parents=True)
    (ws / "skills/x/SKILL.md").write_text("no frontmatter")
    (ws / "MEMORY.md").write_text("m"); (ws / "memory").mkdir(); (ws / "memory/secret-token.md").write_text("nope")
    monkeypatch.setenv("JAEGER_HERMES_SKILLS_HOME", str(h))
    monkeypatch.setenv("JAEGER_OPENCLAW_WORKSPACE", str(ws))
    monkeypatch.setenv("JAEGER_OPENCLAW_PKG", str(tmp_path / "nopkg"))
    out = c.catalog(with_text=True)["engines"]
    assert [s["name"] for s in out["hermes"]["skills"]] == ["deep-research"]
    assert out["hermes"]["skills"][0]["category"] == "research"
    assert out["openclaw"]["skills"][0]["name"] == "x"
    names = [m["name"] for m in out["openclaw"]["memory"]]
    assert "MEMORY.md" in names and "secret-token.md" not in names
    assert all(r["read_only"] for e in out.values() for r in e["skills"] + e["memory"])
