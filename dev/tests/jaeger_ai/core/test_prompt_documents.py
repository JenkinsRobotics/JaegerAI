"""The two context documents: SOUL.md (identity) and AGENTS.md (operations).

Identity and operations were one file, and the runtime read neither into
the prompt — ``load_soul`` existed but no fragment called it. These pin
the split: each document is discovered dynamically, they land in the
right order, neither has a built-in fallback, and a sub-agent gets
neither.

File reads go through a stub layout over ``tmp_path`` rather than a real
instance, so the suite behaves the same on a developer box and in CI,
where no instance directory exists at all.

The loaders and the fragments are JaegerAI's; the assembler they plug
into ships in jaeger-agent. These cover both halves — the documents
themselves, and the fact that registering them into the dependency's
registry lands them in the right order without the dependency changing.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from jaeger_agent.prompts import assemble

from jaeger_ai.core.prompt_documents import (
    load_agent_directives,
    load_soul,
    register_context_documents,
)


@dataclass
class _Layout:
    """The slice of a host layout a context document needs. JaegerAI's
    InstanceLayout satisfies this structurally."""

    root: Path

    @property
    def config_path(self) -> Path:
        return self.root / "config.yaml"

    @property
    def identity_path(self) -> Path:
        return self.root / "identity.yaml"


@pytest.fixture()
def layout(tmp_path) -> _Layout:
    # Idempotent: the fragments may already be registered by an earlier
    # test or a booted pipeline in the same process.
    register_context_documents()
    return _Layout(root=tmp_path)


# ── discovery ───────────────────────────────────────────────────────


def test_soul_is_read_from_disk(layout) -> None:
    (layout.root / "SOUL.md").write_text("I am a lighthouse keeper.\n")
    assert load_soul(layout) == "I am a lighthouse keeper."


def test_legacy_lowercase_soul_still_resolves(layout) -> None:
    """Instances created by the setup wizard have ``soul.md`` on disk."""
    (layout.root / "soul.md").write_text("written by the wizard")
    assert load_soul(layout) == "written by the wizard"


def _case_sensitive(root: Path) -> bool:
    """macOS ships a case-INSENSITIVE filesystem by default, where
    SOUL.md and soul.md are one file and precedence cannot be observed.
    Linux CI is case-sensitive, so the check runs there."""
    probe = root / "CaseProbe.tmp"
    probe.write_text("x")
    try:
        return not (root / "caseprobe.tmp").exists()
    finally:
        probe.unlink()


def test_uppercase_wins_when_both_exist(layout) -> None:
    if not _case_sensitive(layout.root):
        pytest.skip("case-insensitive filesystem: one file, not two")
    (layout.root / "SOUL.md").write_text("canonical")
    (layout.root / "soul.md").write_text("legacy")
    assert load_soul(layout) == "canonical"


def test_directives_are_read_from_agents_md(layout) -> None:
    (layout.root / "AGENTS.md").write_text("Never drive the arm above 40%.")
    assert load_agent_directives(layout) == "Never drive the arm above 40%."


@pytest.mark.parametrize("loader", [load_soul, load_agent_directives])
def test_absent_document_is_empty_not_an_error(loader, layout) -> None:
    assert loader(layout) == ""


@pytest.mark.parametrize("loader", [load_soul, load_agent_directives])
def test_empty_document_is_empty(loader, layout) -> None:
    for name in ("SOUL.md", "AGENTS.md"):
        (layout.root / name).write_text("   \n\n")
    assert loader(layout) == ""


@pytest.mark.parametrize("loader", [load_soul, load_agent_directives])
def test_unreadable_document_never_raises(loader, layout, monkeypatch) -> None:
    for name in ("SOUL.md", "AGENTS.md"):
        (layout.root / name).write_text("content")

    def _boom(*_a, **_k):
        raise OSError("disk gone")

    monkeypatch.setattr(Path, "read_text", _boom)
    assert loader(layout) == ""


def test_a_long_document_is_capped(layout) -> None:
    """A 10K-char soul pushed the routing imperatives into low-attention
    territory in benchmarks — the cap is why it can't."""
    (layout.root / "SOUL.md").write_text("x" * 20_000)
    text = load_soul(layout)
    assert len(text) < 20_000
    assert text.endswith("(SOUL.md truncated)")


def test_the_two_documents_do_not_read_each_other(layout) -> None:
    (layout.root / "SOUL.md").write_text("who I am")
    (layout.root / "AGENTS.md").write_text("what I run")
    assert load_soul(layout) == "who I am"
    assert load_agent_directives(layout) == "what I run"


# ── assembly ────────────────────────────────────────────────────────


def _prompt(layout, **kw) -> str:
    return assemble.assemble_prompt(layout, **kw)


def test_identity_precedes_operations_in_the_prompt(layout) -> None:
    """Order is the contract: who you are, then the framework rules,
    then how this deployment operates."""
    (layout.root / "SOUL.md").write_text("SOUL_MARKER")
    (layout.root / "AGENTS.md").write_text("AGENTS_MARKER")
    text = _prompt(layout)
    assert "SOUL_MARKER" in text and "AGENTS_MARKER" in text
    assert text.index("SOUL_MARKER") < text.index("AGENTS_MARKER")


def test_safety_still_leads_the_prompt(layout) -> None:
    """The Three Laws is fragment #1 in every mode — a document on disk
    must not be able to displace it."""
    (layout.root / "SOUL.md").write_text("SOUL_MARKER")
    text = _prompt(layout)
    names = [f.name for f, _ in assemble.iter_fragments(layout)]
    assert names[0] == "three_laws"
    assert text.index("SOUL_MARKER") > 0


def test_no_documents_means_no_identity_prose(layout) -> None:
    """No hardcoded fallback: an instance without SOUL.md gets no
    identity text at all, rather than a persona nobody wrote."""
    names = [f.name for f, _ in assemble.iter_fragments(layout)]
    assert "soul_identity" not in names
    assert "agent_directives" not in names


def test_sub_agents_get_neither_document(layout) -> None:
    """A delegated child works a brief; the parent owns identity and the
    deployment's standing directives."""
    (layout.root / "SOUL.md").write_text("SOUL_MARKER")
    (layout.root / "AGENTS.md").write_text("AGENTS_MARKER")
    text = _prompt(layout, mode="subagent", goal="do one thing")
    assert "SOUL_MARKER" not in text and "AGENTS_MARKER" not in text


def test_edited_document_is_picked_up_on_the_next_assembly(layout) -> None:
    """Dynamic ingestion: nothing is baked in at import time."""
    soul = layout.root / "SOUL.md"
    soul.write_text("IDENTITY_REV_ONE")
    assert "IDENTITY_REV_ONE" in _prompt(layout)
    soul.write_text("IDENTITY_REV_TWO")
    text = _prompt(layout)
    assert "IDENTITY_REV_TWO" in text and "IDENTITY_REV_ONE" not in text


def test_both_documents_are_declared_fragments(layout) -> None:
    """Nothing reaches the model that isn't in the registry — that is
    what makes ``jaeger prompt show`` complete."""
    declared = {f.name: f for f in assemble.PROMPT_FRAGMENTS}
    assert declared["soul_identity"].kind == "instance"
    assert declared["agent_directives"].kind == "instance"
    assert "SOUL.md" in declared["soul_identity"].source
    assert "AGENTS.md" in declared["agent_directives"].source


# ── the seam: extending a dependency that ships its own registry ────


def test_registration_is_idempotent() -> None:
    """A re-boot in the same process must not duplicate fragments."""
    register_context_documents()
    register_context_documents()
    names = [f.name for f in assemble.PROMPT_FRAGMENTS]
    assert names.count("soul_identity") == 1
    assert names.count("agent_directives") == 1


def test_fragments_land_around_the_dependency_anchors() -> None:
    register_context_documents()
    names = [f.name for f in assemble.PROMPT_FRAGMENTS]
    assert names.index("identity_name") < names.index("soul_identity")
    assert names.index("soul_identity") < names.index("framework")
    assert names.index("framework") < names.index("agent_directives")


def test_a_renamed_anchor_degrades_ordering_rather_than_dropping_a_document():
    """jaeger-agent has no register_fragment API, so placement is
    anchored on fragment NAMES. If upstream renames one, the document
    must still reach the model — just later in the prompt."""
    from jaeger_ai.core import prompt_documents as pd

    fragments = [assemble.PromptFragment("something_else", "framework",
                                         "(x)", lambda c: "")]
    marker = assemble.PromptFragment("late", "instance", "(x)", lambda c: "")
    pd._insert_after(fragments, "identity_name", marker)
    assert [f.name for f in fragments] == ["something_else", "late"]


def test_the_dependency_is_not_modified() -> None:
    """The whole point of registering from the host: jaeger-agent ships
    unchanged, so nothing here needs a fork or a re-pin."""
    import inspect

    from jaeger_agent.prompts import context_blocks

    source = inspect.getsource(context_blocks)
    assert "load_agent_directives" not in source
    assert "AGENTS.md" not in source
