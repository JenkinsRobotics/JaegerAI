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



def propose_live_name(
    instance_root: Path | Any,
    *,
    voice_profile: str | None = None,
    q2_response: str = "",
    q2_refused: bool = False,
    register_override: str | None = None,
    stance: dict[str, Any] | None = None,
    bench: dict[str, Any] | None = None,
    character_id: str = "",
    character_path: str = "",
) -> dict[str, Any] | None:
    """Pick a name with live model reasoning, or the corpus path.

    The model is asked to choose from the gendered corpus subset and give
    a one-to-two sentence why. On any failure the corpus selector runs
    and ``reason_source`` is ``"corpus"`` so the UI can say it fell back
    instead of pretending live reasoning happened.
    """
    fallback = select_name(
        instance_root,
        voice_profile=voice_profile,
        q2_response=q2_response,
        q2_refused=q2_refused,
        register_override=register_override,
    )
    if fallback is None:
        return None
    live = _try_live_pick(
        fallback,
        voice_profile=voice_profile or "",
        stance=stance or {},
        bench=bench or {},
        q2_response=q2_response,
        character_id=character_id,
        character_path=character_path,
    )
    if live:
        return live
    out = dict(fallback)
    out["reason"] = explain_selection(out)
    out["reason_source"] = "corpus"
    return out


def enrich_with_model_reason(
    record: dict[str, Any],
    *,
    stance: dict[str, Any] | None = None,
    voice_profile: str = "",
    bench: dict[str, Any] | None = None,
    q2_response: str = "",
    character_id: str = "",
    character_path: str = "",
) -> dict[str, Any]:
    """Attach a live naming reason. Soft-fails honestly to the corpus note."""
    out = dict(record or {})
    if out.get("reason") and out.get("reason_source"):
        return out
    live = _try_live_pick(
        out,
        voice_profile=voice_profile,
        stance=stance or {},
        bench=bench or {},
        q2_response=q2_response,
        character_id=character_id,
        character_path=character_path,
    )
    if live:
        return live
    out["reason"] = explain_selection(out)
    out["reason_source"] = "corpus"
    return out


def _candidate_pool(record: dict[str, Any]) -> list[NameCandidate]:
    profile = str(record.get("gender") or "").strip().lower()
    corpus = load_corpus()
    pool = [c for c in corpus if c.gender == profile] if profile in {"male", "female"} else list(corpus)
    return pool or list(corpus)


def _try_live_pick(
    record: dict[str, Any],
    *,
    voice_profile: str,
    stance: dict[str, Any],
    bench: dict[str, Any],
    q2_response: str,
    character_id: str,
    character_path: str,
) -> dict[str, Any] | None:
    """Ask a live model to pick a corpus name + why. Never raises."""
    import os

    if os.environ.get("PYTEST_CURRENT_TEST"):
        return None

    pool = _candidate_pool(record)
    if not pool:
        return None
    # Keep the prompt small: a dozen names is enough to choose among.
    names = pool[:12]
    listing = "; ".join(
        f"{c.name} ({c.origin}, {c.meaning}, {c.register})" for c in names
    )
    tier = str((bench or {}).get("tier_label") or "")
    awake = ((bench or {}).get("awake") or {})
    awake_name = str(awake.get("display_name") or awake.get("key") or "")
    stance_label = str((stance or {}).get("stance") or "")
    register = str((stance or {}).get("register") or record.get("register") or "")
    prompt = (
        "You are naming a Jenkins Robotics Jaeger AI OS1 persona. "
        "Pick exactly one name from this list and explain why in 1-2 short "
        "sentences. Reply as JSON only: {\"name\": \"...\", \"why\": \"...\"}. "
        f"List: {listing}. "
        f"Voice: {voice_profile or 'unspecified'}. "
        f"Character: {character_path or 'unset'} {character_id or ''}. "
        f"Host: {tier} {awake_name}. Stance: {stance_label}/{register}. "
        f"Operator style sample: {(q2_response or '')[:180] or 'none'}."
    )
    text = _try_ollama_reason(prompt) or _try_utility_reason(prompt, listing)
    if not text:
        return None
    parsed = _parse_name_json(text)
    if parsed is None:
        return None
    chosen_name, why = parsed
    match = next((c for c in pool if c.name.lower() == chosen_name.lower()), None)
    if match is None:
        return None
    why = why.strip().strip('"').strip("'")
    if len(why) < 8:
        return None
    if len(why) > 280:
        why = why[:277].rstrip() + "…"
    return {
        **match.as_dict(),
        "selected_from": len(load_corpus()),
        "considered": len(pool),
        "register_signal": str(record.get("register_signal") or match.register),
        "register_confidence": record.get("register_confidence", 0.5),
        "origin_note": f"{match.name} — {match.origin}, {match.meaning}",
        "reason": why,
        "reason_source": "model",
    }


def _try_ollama_reason(prompt: str) -> str | None:
    import json
    import os
    import urllib.request

    from jaeger_ai.contract.frameworks import DEFAULT_AGENT_MODEL
    from jaeger_ai.contract.ports import OLLAMA_URL
    url = OLLAMA_URL
    model = (
        os.environ.get("JAEGER_ONBOARD_REASON_MODEL")
        or os.environ.get("JAEGER_GATEWAY_OLLAMA_MODEL")
        or DEFAULT_AGENT_MODEL
    )
    body = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": "Return JSON only. No markdown."},
            {"role": "user", "content": prompt},
        ],
        "stream": False,
        "options": {"num_predict": 90, "temperature": 0.5},
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{url}/api/chat",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=8.0) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None
    return str((payload.get("message") or {}).get("content") or payload.get("response") or "").strip() or None


def _try_utility_reason(prompt: str, facts: str) -> str | None:
    try:
        from jaeger_ai.core.models.system_utility import SystemUtilityModel
        utility = SystemUtilityModel()
        try:
            return utility.respond(prompt, mode="onboarding", facts=facts)
        finally:
            utility.unload()
    except Exception:
        return None


def _parse_name_json(text: str) -> tuple[str, str] | None:
    import json
    import re

    raw = (text or "").strip()
    if not raw:
        return None
    fence = re.search(r"\{.*\}", raw, re.DOTALL)
    blob = fence.group(0) if fence else raw
    try:
        data = json.loads(blob)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    name = str(data.get("name") or "").strip()
    why = str(data.get("why") or data.get("reason") or "").strip()
    if not name or not why:
        return None
    return name, why


__all__ = [
    "CORPUS_PATH",
    "REGISTERS",
    "NameCandidate",
    "explain_selection",
    "enrich_with_model_reason",
    "propose_live_name",
    "load_corpus",
    "read_register",
    "select_name",
]
