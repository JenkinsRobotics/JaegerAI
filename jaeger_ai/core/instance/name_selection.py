"""Autonomous name selection — the SI chooses what it is called.

First boot never asks the operator to name their SI. The name is chosen
during persona initialization, from a bundled corpus, and revealed only if
the operator later asks. The conceit is that the SI considered an index of
names in the fraction of a second before answering; the implementation is
a local lookup, because doing it literally — a network search on every
"what's your name?" — would be slow, non-deterministic and unnecessary.

Selection is a *style* match, not a personality diagnosis. §9 of the OS 1
spec is explicit that Q2 must not produce clinical inference, so the
signals read here are interaction-surface only: how long the answer was,
how formal, how warm. Those map to a ``register`` on each corpus entry.
Nothing here concludes anything about the operator.

Determinism: the same identity picks the same name every time, seeded by
the instance path. A retried persona initialization cannot rename an SI
the operator has already met — and that stability is enforced again at the
storage layer by ``first_boot.record_persona_name`` (first write wins).
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

CORPUS_PATH = Path(__file__).with_name("name_corpus.json")

#: Interaction registers a name can carry. Deliberately about TONE, not
#: about the person: "warm" describes how a name reads, and is matched
#: against how the operator wrote — never against who they are.
REGISTERS = ("warm", "precise", "spare", "bright")


@dataclass(frozen=True)
class NameCandidate:
    name: str
    gender: str
    origin: str
    meaning: str
    register: str

    def as_dict(self) -> dict[str, str]:
        return {
            "name": self.name, "gender": self.gender,
            "origin": self.origin, "meaning": self.meaning,
            "register": self.register,
        }


@lru_cache(maxsize=1)
def load_corpus() -> tuple[NameCandidate, ...]:
    """The bundled name index. Cached — it never changes at runtime."""
    try:
        doc = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ()
    return tuple(
        NameCandidate(
            name=str(entry.get("name", "")),
            gender=str(entry.get("gender", "")),
            origin=str(entry.get("origin", "")),
            meaning=str(entry.get("meaning", "")),
            register=str(entry.get("register", "spare")),
        )
        for entry in doc.get("names", [])
        if entry.get("name")
    )


# ── reading interaction style off the Q2 answer ──────────────────────

_FORMAL_MARKERS = (
    "however", "therefore", "regarding", "furthermore", "consequently",
    "would say", "i would describe", "somewhat", "rather ",
)
_WARM_MARKERS = (
    "love", "close", "care", "wonderful", "lovely", "dear", "miss",
    "grateful", "kind", "happy", "best friend",
)


def read_register(q2_response: str, *, refused: bool = False) -> tuple[str, float]:
    """Infer an interaction register from how the answer was written.

    Returns ``(register, confidence)``. Confidence is deliberately modest:
    one sentence is a thin sample, and §10 requires inferred values carry
    their uncertainty rather than harden into fact.

    A refusal is a real signal — a boundary set early — and maps to
    ``spare`` rather than to nothing. It says nothing about the person
    beyond how they chose to answer one question.
    """
    if refused:
        return "spare", 0.35

    text = (q2_response or "").strip()
    if not text:
        return "spare", 0.2

    words = re.findall(r"[a-z']+", text.lower())
    lowered = text.lower()
    length = len(words)

    formal = sum(1 for marker in _FORMAL_MARKERS if marker in lowered)
    warm = sum(1 for marker in _WARM_MARKERS if marker in lowered)

    if warm >= 1 and length >= 8:
        return "warm", min(0.7, 0.4 + 0.1 * warm)
    if formal >= 1 or length >= 40:
        return "precise", min(0.65, 0.4 + 0.1 * formal)
    if length <= 5:
        # Terse. Reads as spare; says nothing about the person.
        return "spare", 0.5
    return "bright", 0.4


# ── selection ────────────────────────────────────────────────────────


def _seed(instance_root: Path | Any) -> int:
    """Stable per-identity seed, so the choice never wobbles."""
    root = instance_root
    if not isinstance(root, (str, Path)):
        root = getattr(root, "root", root)
    digest = hashlib.sha256(str(root).encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big")


def select_name(
    instance_root: Path | Any,
    *,
    voice_profile: str | None,
    q2_response: str = "",
    q2_refused: bool = False,
    register_override: str | None = None,
) -> dict[str, Any] | None:
    """Choose a name. ``None`` when the corpus is unavailable.

    ``voice_profile`` is a hard constraint, not a preference: the operator
    picked a voice, and a name that fights it would be the system
    overriding the one explicit choice they made. Style only ever decides
    *within* that filter.
    """
    corpus = load_corpus()
    if not corpus:
        return None

    profile = (voice_profile or "").strip().lower()
    pool = [c for c in corpus if c.gender == profile] if profile in {"male", "female"} else list(corpus)
    if not pool:
        pool = list(corpus)

    if register_override in REGISTERS:
        # The calibrated stance already weighed Probe 1's delivery, which
        # the Q2 text alone cannot see.
        register, confidence = register_override, 0.6
    else:
        register, confidence = read_register(q2_response, refused=q2_refused)
    matching = [c for c in pool if c.register == register]
    # Fall back to the whole gendered pool rather than forcing a register
    # match — a thin signal should narrow the field, not dictate it.
    field = matching or pool

    chosen = field[_seed(instance_root) % len(field)]
    return {
        **chosen.as_dict(),
        "selected_from": len(corpus),
        "considered": len(field),
        "register_signal": register,
        "register_confidence": round(confidence, 2),
        "origin_note": f"{chosen.name} — {chosen.origin}, {chosen.meaning}",
    }


def explain_selection(record: dict[str, Any]) -> str:
    """How the SI answers "what's your name?".

    Describes the actual mechanism — an index consulted at initialization —
    rather than inventing a story about it.
    """
    name = record.get("name", "")
    origin = record.get("origin", "")
    meaning = record.get("meaning", "")
    considered = record.get("selected_from", 0)
    return (
        f"{name}. I chose it during initialization — I read an index of "
        f"{considered} names and took the one that fit. {origin}; it means "
        f"{meaning}."
    )


__all__ = [
    "CORPUS_PATH",
    "REGISTERS",
    "NameCandidate",
    "explain_selection",
    "load_corpus",
    "read_register",
    "select_name",
]
