"""`@file` / `@url` reference expansion (audit A4).

`core/context_refs.expand_references` inlines a referenced file or URL
into a user turn. The file-read and URL-fetch are injected here so the
tests need no real filesystem path or network.
"""

from __future__ import annotations

from jaeger_os.agent.prompts.context_refs import expand_references


def _reader(mapping):
    def _read(path: str) -> str:
        if path not in mapping:
            raise FileNotFoundError(path)
        return mapping[path]
    return _read


def _fetcher(mapping):
    def _fetch(url: str) -> str:
        if url not in mapping:
            raise RuntimeError("404")
        return mapping[url]
    return _fetch


# ── no references ───────────────────────────────────────────────────


def test_text_without_references_is_unchanged():
    text = "just a normal message with no refs"
    assert expand_references(text, read_file=_reader({}),
                             fetch_url=_fetcher({})) == text


def test_email_address_is_not_treated_as_a_reference():
    text = "email me at jonathan@gmail.com please"
    assert expand_references(text, read_file=_reader({}),
                             fetch_url=_fetcher({})) == text


# ── file references ─────────────────────────────────────────────────


def test_file_reference_is_inlined():
    out = expand_references(
        "look at @main.py for the bug",
        read_file=_reader({"main.py": "print('hello')"}),
        fetch_url=_fetcher({}),
    )
    assert "look at @main.py for the bug" in out      # original kept
    assert "referenced file: @main.py" in out
    assert "print('hello')" in out


def test_trailing_punctuation_is_stripped_from_the_ref():
    out = expand_references(
        "check @main.py.",
        read_file=_reader({"main.py": "CONTENT"}),
        fetch_url=_fetcher({}),
    )
    assert "CONTENT" in out          # resolved 'main.py', not 'main.py.'


def test_unresolvable_reference_is_noted_inline_not_raised():
    out = expand_references(
        "see @nope.txt",
        read_file=_reader({}),
        fetch_url=_fetcher({}),
    )
    assert "could not read" in out
    assert "@nope.txt" in out


def test_duplicate_references_expand_once():
    out = expand_references(
        "compare @a.py and @a.py again",
        read_file=_reader({"a.py": "BODY"}),
        fetch_url=_fetcher({}),
    )
    assert out.count("referenced file: @a.py") == 1


def test_oversized_file_is_truncated():
    big = "x" * 50_000
    out = expand_references(
        "@big.txt",
        read_file=_reader({"big.txt": big}),
        fetch_url=_fetcher({}),
    )
    assert "(truncated)" in out
    assert len(out) < len(big) + 2_000


# ── url references ──────────────────────────────────────────────────


def test_url_reference_is_fetched_and_inlined():
    out = expand_references(
        "summarize @https://example.com/doc",
        read_file=_reader({}),
        fetch_url=_fetcher({"https://example.com/doc": "PAGE TEXT"}),
    )
    assert "referenced url: @https://example.com/doc" in out
    assert "PAGE TEXT" in out
