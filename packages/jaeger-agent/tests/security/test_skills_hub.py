"""Skills hub — installing third-party skills without handing over the box.

Ported from hermes-agent ``tools/skills_hub.py``. Most of these tests are
containment tests, because that is what the module is for: everything it
installs is code someone else wrote.
"""

from __future__ import annotations

import pytest

from jaeger_agent.skill_registry import skills_hub as hub
from jaeger_agent.skill_registry.skills_hub import BundleError


@pytest.fixture()
def instance(tmp_path, monkeypatch):
    from jaeger_ai.core.instance.instance import InstanceLayout

    layout = InstanceLayout(root=tmp_path / "inst")
    layout.skills_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("jaeger_agent.workspace.get_layout", lambda: layout)
    monkeypatch.delenv("JAEGER_SKILL_LEDGER", raising=False)
    return layout


def _bundle(name="demo", files=None):
    # `files if files is not None` — an explicitly empty dict is a test case
    # (a bundle with no members), and `files or {...}` would silently
    # substitute the default for it.
    if files is None:
        files = {"SKILL.md": b"# demo\nDoes a thing.\n"}
    return hub.SkillBundle(
        meta=hub.SkillMeta(name=name, source_id="local", identifier=name),
        files=files)


# ---------------------------------------------------------------------------
# Name validation
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("bad", [
    "", "   ", ".", "..", "a/b", "a\\b", ".hidden", "x" * 100, "a\x00b",
])
def test_illegal_skill_names_are_refused(bad):
    with pytest.raises(BundleError):
        hub.validate_skill_name(bad)


def test_legal_names_pass():
    for good in ("demo", "my-skill", "my_skill", "skill.v2"):
        assert hub.validate_skill_name(good) == good


# ---------------------------------------------------------------------------
# Path containment
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("bad", [
    "../escape", "a/../../escape", "/etc/passwd", "C:\\win", "", "a\x00b",
    "..", "a/../..",
])
def test_traversal_paths_are_refused(bad):
    with pytest.raises(BundleError):
        hub.validate_rel_path(bad)


def test_nested_paths_are_allowed():
    assert hub.validate_rel_path("scripts/run.py") == "scripts/run.py"
    assert hub.validate_rel_path("a\\b") == "a/b"


def test_safe_join_checks_the_resolved_path(tmp_path):
    """`a/../../b` normalises past a naive prefix test."""
    root = tmp_path / "bundle"
    root.mkdir()
    with pytest.raises(BundleError):
        hub._safe_join(root, "a/../../outside")
    assert hub._safe_join(root, "a/b.txt").parent.name == "a"


def test_bundle_with_a_traversal_member_is_rejected(instance):
    b = _bundle(files={"SKILL.md": b"# x", "../../evil.sh": b"rm -rf /"})
    out = hub.install(b)
    assert out["ok"] is False
    assert "escapes" in out["error"]
    assert not (instance.skills_dir / "demo").exists()


def test_traversal_bundle_leaves_nothing_in_quarantine(instance):
    hub.install(_bundle(files={"SKILL.md": b"# x", "../evil": b"x"}))
    staged = hub.quarantine_dir() / "demo"
    assert not (staged / ".." / "evil").exists()


# ---------------------------------------------------------------------------
# Bundle structure
# ---------------------------------------------------------------------------

def test_bundle_without_skill_md_is_refused(instance):
    out = hub.install(_bundle(files={"notes.txt": b"hi"}))
    assert out["ok"] is False
    assert "SKILL.md" in out["error"]


def test_empty_bundle_is_refused(instance):
    out = hub.install(_bundle(files={}))
    assert out["ok"] is False


def test_oversized_bundle_is_refused(instance):
    big = {"SKILL.md": b"# x", "blob.bin": b"x" * (hub._MAX_BUNDLE_BYTES + 1)}
    out = hub.install(_bundle(files=big))
    assert out["ok"] is False
    assert "bytes" in out["error"]


def test_too_many_files_refused(instance):
    files = {"SKILL.md": b"# x"}
    files.update({f"f{i}.txt": b"x" for i in range(hub._MAX_BUNDLE_FILES + 1)})
    out = hub.install(_bundle(files=files))
    assert out["ok"] is False
    assert "files" in out["error"]


# ---------------------------------------------------------------------------
# URL policy
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("bad", [
    "http://example.com/x", "ftp://example.com", "file:///etc/passwd",
    "https://", "",
])
def test_non_https_sources_are_refused(bad):
    with pytest.raises(BundleError):
        hub.validate_url(bad)


def test_https_passes():
    assert hub.validate_url("https://github.com/a/b.git")


# ---------------------------------------------------------------------------
# Install / uninstall
# ---------------------------------------------------------------------------

def test_install_lands_in_skills_dir(instance):
    out = hub.install(_bundle())
    assert out["ok"] is True
    assert (instance.skills_dir / "demo" / "SKILL.md").is_file()


def test_install_records_the_lock(instance):
    hub.install(_bundle())
    rows = hub.installed()
    assert len(rows) == 1
    assert rows[0]["name"] == "demo"
    assert rows[0]["source"] == "local"


def test_install_is_ledgered_and_therefore_reversible(instance):
    from jaeger_agent.skill_registry import skill_ledger as led

    hub.install(_bundle())
    entries = led.list_entries(skill="demo")
    assert entries and entries[0]["action"] == "hub-install"

    ok, msg = led.rollback_entry(entries[0]["id"])
    assert ok, msg
    assert not (instance.skills_dir / "demo" / "SKILL.md").exists()


def test_install_refuses_to_clobber(instance):
    hub.install(_bundle())
    (instance.skills_dir / "demo" / "SKILL.md").write_text(
        "# hand edited", encoding="utf-8")

    out = hub.install(_bundle())
    assert out["ok"] is False
    assert "already installed" in out["error"]
    assert "hand edited" in (
        instance.skills_dir / "demo" / "SKILL.md").read_text(encoding="utf-8")


def test_overwrite_is_explicit(instance):
    hub.install(_bundle())
    out = hub.install(_bundle(files={"SKILL.md": b"# v2"}), overwrite=True)
    assert out["ok"] is True
    assert "v2" in (instance.skills_dir / "demo" / "SKILL.md").read_text(
        encoding="utf-8")


def test_uninstall_removes_and_ledgers(instance):
    from jaeger_agent.skill_registry import skill_ledger as led

    hub.install(_bundle())
    out = hub.uninstall("demo")
    assert out["ok"] is True
    assert not (instance.skills_dir / "demo").exists()
    assert hub.installed() == []
    assert any(e["action"] == "hub-uninstall" for e in led.list_entries("demo"))


def test_uninstall_unknown(instance):
    assert hub.uninstall("nope")["ok"] is False


def test_uninstall_rejects_a_traversal_name(instance):
    assert hub.uninstall("../../etc")["ok"] is False


# ---------------------------------------------------------------------------
# LocalSource
# ---------------------------------------------------------------------------

def test_local_source_finds_and_fetches(instance, tmp_path):
    root = tmp_path / "catalog"
    (root / "alpha").mkdir(parents=True)
    (root / "alpha" / "SKILL.md").write_text("# alpha\nDoes alpha.\n",
                                             encoding="utf-8")
    (root / "alpha" / "scripts").mkdir()
    (root / "alpha" / "scripts" / "run.py").write_text("print(1)",
                                                       encoding="utf-8")

    src = hub.LocalSource(root)
    found = src.search("alpha")
    assert [m.name for m in found] == ["alpha"]
    assert found[0].description == "alpha"

    bundle = src.fetch(str(root / "alpha"))
    assert set(bundle.files) == {"SKILL.md", "scripts/run.py"}
    assert bundle.meta.trust == hub.TRUST_LOCAL


def test_local_source_refuses_paths_outside_its_root(instance, tmp_path):
    root = tmp_path / "catalog"
    root.mkdir()
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    (outside / "SKILL.md").write_text("# x", encoding="utf-8")

    with pytest.raises(BundleError):
        hub.LocalSource(root).fetch(str(outside))


def test_install_from_local_source(instance, tmp_path):
    root = tmp_path / "catalog"
    (root / "beta").mkdir(parents=True)
    (root / "beta" / "SKILL.md").write_text("# beta", encoding="utf-8")

    out = hub.install_from(hub.LocalSource(root), str(root / "beta"))
    assert out["ok"] is True
    assert (instance.skills_dir / "beta" / "SKILL.md").is_file()


def test_install_from_missing_identifier(instance, tmp_path):
    root = tmp_path / "catalog"
    root.mkdir()
    out = hub.install_from(hub.LocalSource(root), str(root / "ghost"))
    assert out["ok"] is False


# ---------------------------------------------------------------------------
# GitHubSource
# ---------------------------------------------------------------------------

def test_github_repo_spec_is_validated():
    for bad in ("", "noslash", "a/b/c", "/b", "a/"):
        with pytest.raises(BundleError):
            hub.GitHubSource(bad)


def test_github_clone_url_is_https():
    assert hub.GitHubSource("owner/repo").clone_url == \
        "https://github.com/owner/repo.git"


def test_github_trust_levels():
    assert hub.GitHubSource("anthropics/skills").trust_level_for("x") == \
        hub.TRUST_OFFICIAL
    assert hub.GitHubSource("someone/random").trust_level_for("x") == \
        hub.TRUST_COMMUNITY


def test_github_fetch_validates_the_skill_name(instance):
    with pytest.raises(BundleError):
        hub.GitHubSource("owner/repo").fetch("owner/repo#../../evil")
