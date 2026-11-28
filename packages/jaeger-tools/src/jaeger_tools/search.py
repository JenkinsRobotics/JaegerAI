"""BM25 + IDF-gated ranked tool retrieval (adapted from hermes-agent, MIT licensed)."""

from __future__ import annotations

import functools
import math
import re
import threading
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Optional

try:
    import snowballstemmer
except ImportError:  # pragma: no cover — graceful minimal-env fallback
    snowballstemmer = None  # type: ignore[assignment]


@dataclass
class CatalogEntry:
    """One deferrable tool, in a form search/router tools can index and serve."""

    name: str
    description: str
    schema: dict[str, Any]
    source: str
    source_name: str
    _tokens: list[str] = field(default_factory=list)


_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")
_thread_local = threading.local()


@functools.lru_cache(maxsize=16384)
def _stem(token: str) -> str:
    if snowballstemmer is None:
        return token[:-1] if len(token) > 3 and token.endswith("s") else token
    if getattr(_thread_local, "stemmer", None) is None:
        _thread_local.stemmer = snowballstemmer.stemmer("english")
    return _thread_local.stemmer.stemWord(token)


def _tokenize(text: str) -> list[str]:
    return [_stem(token.lower()) for token in _TOKEN_RE.findall(text)] if text else []


def _fn(td: dict[str, Any]) -> dict[str, Any]:
    return td.get("function") or {}


def _entry_search_text(td: dict[str, Any], source_label: str = "") -> str:
    fn = _fn(td)
    name = fn.get("name", "").removeprefix("mcp__")
    name_words = re.sub(r"[_.:-]", " ", name)
    extra = source_label if source_label and source_label not in name_words.split() else ""
    param_names = " ".join(((fn.get("parameters") or {}).get("properties") or {}).keys())
    return f"{name_words} {extra} {fn.get('description', '') or ''} {param_names}"


def _bm25_score(
    query_tokens: list[str],
    doc_tokens: list[str],
    doc_lengths: list[int],
    avg_dl: float,
    doc_freq: dict[str, int],
    n_docs: int,
    k1: float = 1.5,
    b: float = 0.75,
) -> float:
    score = 0.0
    dl = len(doc_tokens)
    doc_tf = Counter(doc_tokens)
    for q in query_tokens:
        df, tf = doc_freq.get(q, 0), doc_tf.get(q, 0)
        if df and tf:
            idf = math.log(1 + (n_docs - df + 0.5) / (df + 0.5))
            score += idf * tf * (k1 + 1) / (tf + k1 * (1 - b + b * dl / max(avg_dl, 1.0)))
    return score


_CorpusStats = tuple[list[int], float, dict[str, int], int]


def _corpus_stats(catalog: list[CatalogEntry]) -> _CorpusStats:
    doc_lengths = [len(entry._tokens) for entry in catalog]
    avg_dl = sum(doc_lengths) / max(len(doc_lengths), 1)
    doc_freq = Counter(tok for entry in catalog for tok in set(entry._tokens))
    return doc_lengths, avg_dl, dict(doc_freq), len(catalog)


def _gate_token(query_tokens: list[str], doc_freq: dict[str, int], n_docs: int) -> str:
    def _idf(token: str) -> float:
        df = doc_freq.get(token, 0)
        return math.log(1 + (n_docs - df + 0.5) / (df + 0.5))
    return max(query_tokens, key=_idf)


MIN_QUERY_TERM_COVERAGE = 0.5
MIN_ANSWERABLE_TERMS_FOR_COVERAGE = 4


def _required_term_coverage(answerable_term_count: int) -> int:
    if answerable_term_count < MIN_ANSWERABLE_TERMS_FOR_COVERAGE:
        return 1
    return math.ceil(answerable_term_count * MIN_QUERY_TERM_COVERAGE)


def search_catalog(
    catalog: list[CatalogEntry],
    query: str,
    limit: int = 5,
    *,
    corpus_stats: Optional[_CorpusStats] = None,
) -> list[CatalogEntry]:
    query_tokens = _tokenize(query) if catalog and limit > 0 else []
    if not query_tokens:
        return []
    corpus_stats = corpus_stats or _corpus_stats(catalog)
    doc_freq = corpus_stats[2]
    gate = _gate_token(query_tokens, doc_freq, corpus_stats[3])
    answerable = {t for t in query_tokens if doc_freq.get(t, 0) > 0}
    required_terms = _required_term_coverage(len(answerable))
    exact_name = query.strip().lower()

    def _admitted(entry: CatalogEntry) -> bool:
        if entry.name.lower() == exact_name:
            return True
        tokens = set(entry._tokens)
        return gate in tokens and sum(1 for t in answerable if t in tokens) >= required_terms

    scored = [
        (
            float("inf")
            if entry.name.lower() == exact_name
            else _bm25_score(query_tokens, entry._tokens, *corpus_stats),
            entry,
        )
        for entry in catalog
        if _admitted(entry)
    ]
    scored.sort(key=lambda x: x[0], reverse=True)
    return [e for _, e in scored[:limit]]


__all__ = [
    "CatalogEntry",
    "MIN_ANSWERABLE_TERMS_FOR_COVERAGE",
    "MIN_QUERY_TERM_COVERAGE",
    "_corpus_stats",
    "_entry_search_text",
    "_tokenize",
    "search_catalog",
]
