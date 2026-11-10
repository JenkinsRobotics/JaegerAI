"""Ranked tool retrieval adapted from NousResearch/hermes-agent.

Pinned source: b7db40d82568ea68ce321ac1ead3bfea354c7f56, tools/tool_search_catalog.py.
Only pure retrieval is reused; Jaeger owns admission, inventory and dispatch.
"""
# MIT License
#
# Copyright (c) 2025 Nous Research
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

from __future__ import annotations

import functools
import math
import re
import threading
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import snowballstemmer


@dataclass
class CatalogEntry:
    """One deferrable tool, in a form the bridge tools can search and serve."""

    name: str
    description: str
    schema: dict[str, Any]  # the full {"type":"function", "function": {...}} entry
    source: str  # "mcp" | "plugin" | "other"
    source_name: str  # toolset name, e.g. "mcp-github" or "kanban"
    _tokens: list[str] = field(default_factory=list)  # pre-tokenized for BM25


_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")
_thread_local = threading.local()


@functools.lru_cache(maxsize=16384)
def _stem(token: str) -> str:
    """Stem one token, memoized across stateless catalog rebuilds. Snowball stemmers carry
    mutable parsing state and bridge dispatch runs on parallel tool-call threads, so the
    stemmer is one-per-thread, created lazily."""
    if getattr(_thread_local, "stemmer", None) is None:
        _thread_local.stemmer = snowballstemmer.stemmer("english")
    return _thread_local.stemmer.stemWord(token)


def _tokenize(text: str) -> list[str]:
    """Lowercase alphanumeric tokens, Snowball-stemmed (English); shared by the index and
    query paths so "issues" matches ``create_issue``."""
    return [_stem(token.lower()) for token in _TOKEN_RE.findall(text)] if text else []


def _fn(td: dict[str, Any]) -> dict[str, Any]:
    """The ``function`` block of a tool-def (``{}`` when absent/None)."""
    return td.get("function") or {}


def _entry_search_text(td: dict[str, Any], source_label: str = "") -> str:
    """Search-text blob: split name words + source label + description + top-level parameter
    names (schema bodies are noise with no recall gain). The ``mcp__`` prefix is dropped — it
    is in every MCP document, so its IDF is ~0. The source label lets a service-name query
    ("linear") reach a tool whose own name omits the vendor."""
    fn = _fn(td)
    name = fn.get("name", "")
    name = name.removeprefix("mcp__")
    name_words = re.sub(r"[_.:-]", " ", name)
    extra = source_label if source_label and source_label not in name_words.split() else ""
    param_names = " ".join(((fn.get("parameters") or {}).get("properties") or {}).keys())
    return f"{name_words} {extra} {fn.get('description', '') or ''} {param_names}"


def _bm25_score(query_tokens: list[str], doc_tokens: list[str], doc_lengths: list[int],
                avg_dl: float, doc_freq: dict[str, int], n_docs: int, k1: float = 1.5,
                b: float = 0.75) -> float:
    """Standard BM25 for one query against one document (inlined; the catalog is bounded —
    typically < 500 tools — so a dependency is not worth it)."""
    score = 0.0
    dl = len(doc_tokens)
    doc_tf = Counter(doc_tokens)
    for q in query_tokens:
        df, tf = doc_freq.get(q, 0), doc_tf.get(q, 0)
        if df and tf:
            idf = math.log(1 + (n_docs - df + 0.5) / (df + 0.5))
            score += idf * tf * (k1 + 1) / (tf + k1 * (1 - b + b * dl / max(avg_dl, 1.0)))
    return score


_CorpusStats = tuple[list[int], float, dict[str, int], int]  # doc_lengths, avg_dl, df, n_docs


def _corpus_stats(catalog: list[CatalogEntry]) -> _CorpusStats:
    """Compute the BM25 statistics shared by every query over a catalog."""
    doc_lengths = [len(entry._tokens) for entry in catalog]
    avg_dl = sum(doc_lengths) / max(len(doc_lengths), 1)
    doc_freq = Counter(tok for entry in catalog for tok in set(entry._tokens))
    return doc_lengths, avg_dl, dict(doc_freq), len(catalog)


def _gate_token(query_tokens: list[str], doc_freq: dict[str, int], n_docs: int) -> str:
    """The query token with the highest IDF: the word that names the intent. ``send``,
    ``read``, ``create`` sit in dozens of tool documents and separate nothing; ``gmail``,
    ``github``, ``incident`` sit in a few and separate everything. A document without this
    token answered a different question, however many common tokens it shares."""
    def _idf(token: str) -> float:
        df = doc_freq.get(token, 0)
        return math.log(1 + (n_docs - df + 0.5) / (df + 0.5))
    return max(query_tokens, key=_idf)


# Relevance floor. The rarest-token gate stops queries whose intent word no tool carries; it
# does not stop a long hunt whose every word exists SOMEWHERE in the catalog while no single
# tool carries more than one of them (observed: "run shell command execute code python" -> a
# workflow-rerun tool sharing only "run"; the model read "results exist" as "it is in here"
# and re-searched 216 times). A document must also match MIN_QUERY_TERM_COVERAGE of the
# query's ANSWERABLE terms (present in at least one document) before it is offered. Coverage
# only engages from MIN_ANSWERABLE_TERMS_FOR_COVERAGE terms up: short queries ("list issues")
# legitimately differ from a tool by a word, and are where a coverage rule costs real recall.
MIN_QUERY_TERM_COVERAGE = 0.5
MIN_ANSWERABLE_TERMS_FOR_COVERAGE = 4


def _required_term_coverage(answerable_term_count: int) -> int:
    """How many of a query's ANSWERABLE unique terms a document must match to be offered:
    one below the engagement floor, else at least half, rounded up."""
    if answerable_term_count < MIN_ANSWERABLE_TERMS_FOR_COVERAGE:
        return 1
    return math.ceil(answerable_term_count * MIN_QUERY_TERM_COVERAGE)


def search_catalog(catalog: list[CatalogEntry], query: str, limit: int = 5, *,
                   corpus_stats: Optional[_CorpusStats] = None) -> list[CatalogEntry]:
    """Top-``limit`` catalog entries for ``query`` by BM25 (exact name match ranks first).

    Admission is by the query's rarest token (:func:`_gate_token`), not by ``score > 0``:
    BM25 is additive over the tokens a document shares with the query, so on a large catalog
    ``score > 0`` admits one-token matches and fills every slot with them (measured: "send
    gmail email" returned 5 incident tools that only shared ``email``). A token no document
    carries admits nothing; the caller's empty-group hint tells the model to retry without it.
    Long queries additionally need :func:`_required_term_coverage` of their answerable terms."""
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
        """Carries the intent word AND enough of the answerable terms (exact name is exempt)."""
        if entry.name.lower() == exact_name:
            return True
        tokens = set(entry._tokens)
        return gate in tokens and sum(1 for t in answerable if t in tokens) >= required_terms

    scored = [
        (float("inf") if entry.name.lower() == exact_name
         else _bm25_score(query_tokens, entry._tokens, *corpus_stats), entry)
        for entry in catalog if _admitted(entry)]
    scored.sort(key=lambda x: x[0], reverse=True)
    return [e for _, e in scored[:limit]]


