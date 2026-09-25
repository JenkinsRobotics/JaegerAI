"""LocalAgreement is two rules, and both fail silently when wrong: a
broken cursor duplicates seconds of text into the final transcript, and
a broken agreement check publishes words Whisper is about to revise.
Neither raises. So they get a test.

Pure functions — no model, no mic, no bus.
"""

from jaeger_whisper_stt.engine.window import (
    agreed_prefix_len,
    commit_cursor,
    word_pairs,
)


def _norm(text: str) -> list[str]:
    return [n for n, _ in word_pairs(text)]


def _cursor(committed: str, candidate: str, **kw):
    return commit_cursor(_norm(committed), _norm(candidate), **kw)


# ── the cursor: which words are past what we already published ────────
def test_cursor_finds_the_boundary() -> None:
    # Nothing committed yet -> everything is new.
    assert _cursor("", "hello there friend") == 0

    # The normal case: the window still holds what we already took.
    assert _cursor("hello there", "hello there friend") == 2

    # Case-and-punctuation blind. This is the one that broke a real run:
    # Whisper emits "moon" mid-window and "moon!" once it has heard the
    # sentence end, and a raw compare then reports no overlap at all.
    assert _cursor("we choose to go to the moon",
                   "We choose to go to the Moon! In this decade") == 7

    # Anchor sits further inside the candidate — the window scrolled and
    # re-decoded a little context ahead of the cursor.
    assert _cursor("the pod bay", "sorry the pod bay doors") == 4

    # Re-decoding the identical window advances the cursor to the end,
    # so nothing new is taken. A regression here doubles every word.
    assert _cursor("hello there friend", "hello there friend") == 3


def test_cursor_refuses_to_guess() -> None:
    # No overlap -> None, NOT "take everything". Returning the whole
    # window here is what dumped already-published text back into the
    # transcript; the caller waits for the next pass instead.
    assert _cursor("completely different words", "brand new sentence") is None

    # A single shared word must not count as an anchor, or "the" would
    # align anything with anything.
    assert _cursor("something about the", "the quick brown fox") is None
    assert _cursor("something about the", "the quick brown fox",
                   min_overlap=1) == 1

    # Degenerate inputs are answers, not crashes.
    assert _cursor("hello there", "") == 0
    assert _cursor("", "") == 0


# ── the agreement: which of those are stable enough to publish ────────
def test_agreement_holds_back_the_unstable_tail() -> None:
    # Two passes agree on "in this decade and" then diverge — only the
    # agreed prefix is safe. "decade"/"decay" is the real flap this
    # rule exists to absorb.
    prev = _norm("in this decade and do the other")
    now = _norm("in this decade and do the other things")
    assert agreed_prefix_len(now, prev) == 7

    prev = _norm("in this decade and do the")
    now = _norm("in this decay and do the")
    assert agreed_prefix_len(now, prev) == 2   # stops at decade/decay

    # No previous hypothesis -> nothing is confirmed yet. The first pass
    # over new audio must commit NOTHING, which is what makes the mode
    # trustworthy rather than merely fast.
    assert agreed_prefix_len(_norm("hello there"), []) == 0

    # Identical hypotheses -> all of it.
    assert agreed_prefix_len(_norm("a b c"), _norm("a b c")) == 3

    # Divergence at the first word confirms nothing.
    assert agreed_prefix_len(_norm("x b c"), _norm("a b c")) == 0


def test_word_pairs_keeps_the_original_spelling() -> None:
    """Match on normalized, publish the original — otherwise the final
    transcript comes out as lowercase unpunctuated mush."""
    pairs = word_pairs("We choose, to go to the Moon!")
    assert [n for n, _ in pairs][:3] == ["we", "choose", "to"]
    assert " ".join(o for _, o in pairs) == "We choose to go to the Moon"


def test_registry_partials_flags() -> None:
    """Interfaces branch on `partials` to decide whether a caption pane
    is worth wiring, so it must match which classes really emit them."""
    from jaeger_whisper_stt.engine.registry import METHODS

    streaming = {n for n, m in METHODS.items() if m.partials}
    assert streaming == {"phrase_word", "window", "local_agreement"}
    assert all(m.available for m in METHODS.values())


if __name__ == "__main__":
    for fn in (test_cursor_finds_the_boundary, test_cursor_refuses_to_guess,
               test_agreement_holds_back_the_unstable_tail,
               test_word_pairs_keeps_the_original_spelling,
               test_registry_partials_flags):
        fn()
    print("cursor + agreement OK")
