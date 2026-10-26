"""The bench corpus is intact and well-formed.

The corpus is pure data, so it cannot fail at import the way code does —
a typo'd tag or an empty prompt just sits there and quietly measures
nothing. These checks are the smallest thing that fails when the data
rots.

Running the corpus is a separate matter: that needs a live agent, an
instance layout and a system prompt, so the runner is still in JaegerAI.
Structure is what this module can assert on its own today.
"""

from __future__ import annotations

from jaeger_agent.bench import CASES, BenchCase, all_tags


def test_corpus_is_present() -> None:
    assert len(CASES) >= 80, f"corpus shrank to {len(CASES)} cases"
    assert all(isinstance(c, BenchCase) for c in CASES)


def test_every_case_has_a_prompt_and_an_id() -> None:
    """An empty prompt or a blank id measures nothing and reports a pass."""
    bad = [
        c for c in CASES
        if not (getattr(c, "prompt", "") or "").strip()
        or not (getattr(c, "id", "") or "").strip()
    ]
    assert not bad, f"{len(bad)} case(s) with a blank id or prompt"


def test_case_ids_are_unique() -> None:
    """Duplicate ids make a result table lie: two rows, one name, and the
    second silently masks the first when results are keyed by id."""
    seen: dict[str, int] = {}
    for c in CASES:
        seen[c.id] = seen.get(c.id, 0) + 1
    dupes = {k: v for k, v in seen.items() if v > 1}
    assert not dupes, f"duplicate case ids: {dupes}"


def test_tags_are_declared_and_lowercase() -> None:
    """Tags select what runs (``--tags routing``). A stray capital or a
    typo makes a case unselectable without ever erroring."""
    tags = all_tags()
    assert tags, "no tags in the corpus"
    odd = [t for t in tags if t != t.strip().lower() or " " in t]
    assert not odd, f"tags should be lowercase and space-free: {odd}"


def test_expected_tools_look_like_tool_names() -> None:
    """A case asserting on a tool that cannot exist can never pass. This
    checks shape only — the real registry needs a host to be complete."""
    odd = [
        (c.id, t)
        for c in CASES
        for t in (getattr(c, "expected_tools", None) or [])
        if not t or not t.replace("_", "").isalnum()
    ]
    assert not odd, f"malformed expected_tools entries: {odd[:5]}"
