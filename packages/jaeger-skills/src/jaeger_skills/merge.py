"""Three-way merge for ``SKILL.md`` files: YAML frontmatter by field, body by line.

Adapted from Significant-Gravitas/AutoGPT (MIT License):
``autogpt_platform/backend/backend/copilot/tools/skill_merge.py``.
The owner's edits win any field or hunk changed differently on both sides.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from typing import Any

import yaml

_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n(.*)$", re.DOTALL)
_MISSING = object()


@dataclass(frozen=True)
class MergedText:
    text: str
    conflicted: bool = False


def merge_text(base: str, ours: str, theirs: str) -> MergedText:
    """Line-by-line three-way merge; *ours* wins on overlapping edits."""
    if ours == theirs:
        return MergedText(text=ours, conflicted=False)
    if base == ours:
        return MergedText(text=theirs, conflicted=False)
    if base == theirs:
        return MergedText(text=ours, conflicted=False)

    b_lines = base.splitlines(keepends=True)
    o_lines = ours.splitlines(keepends=True)
    t_lines = theirs.splitlines(keepends=True)

    o_ops = difflib.SequenceMatcher(None, b_lines, o_lines).get_opcodes()
    t_ops = difflib.SequenceMatcher(None, b_lines, t_lines).get_opcodes()

    o_edits = [(i1, i2, o_lines[j1:j2]) for tag, i1, i2, j1, j2 in o_ops if tag != "equal"]
    t_edits = [(i1, i2, t_lines[j1:j2]) for tag, i1, i2, j1, j2 in t_ops if tag != "equal"]

    # Check overlaps; on overlap, ours wins and conflicted=True
    merged_edits: list[tuple[int, int, list[str]]] = []
    conflicted = False
    oi = ti = 0
    while oi < len(o_edits) or ti < len(t_edits):
        if ti >= len(t_edits):
            merged_edits.append(o_edits[oi])
            oi += 1
        elif oi >= len(o_edits):
            merged_edits.append(t_edits[ti])
            ti += 1
        else:
            o1, o2, o_rep = o_edits[oi]
            t1, t2, t_rep = t_edits[ti]
            if o2 <= t1 and not (o1 == o2 == t1 == t2):
                merged_edits.append(o_edits[oi])
                oi += 1
            elif t2 <= o1 and not (o1 == o2 == t1 == t2):
                merged_edits.append(t_edits[ti])
                ti += 1
            else:
                if o1 == t1 and o2 == t2 and o_rep == t_rep:
                    merged_edits.append(o_edits[oi])
                else:
                    conflicted = True
                    merged_edits.append((min(o1, t1), max(o2, t2), o_rep))
                oi += 1
                ti += 1

    out: list[str] = []
    cursor = 0
    for i1, i2, rep in merged_edits:
        if i1 > cursor:
            out.extend(b_lines[cursor:i1])
        out.extend(rep)
        cursor = max(cursor, i2)
    if cursor < len(b_lines):
        out.extend(b_lines[cursor:])
    return MergedText(text="".join(out), conflicted=conflicted)


def merge_skill_markdown(base: str, ours: str, theirs: str) -> MergedText:
    """Three-way merge of a ``SKILL.md`` (frontmatter field-by-field, body line-by-line)."""
    if ours == theirs:
        return MergedText(text=ours, conflicted=False)
    if base == ours:
        return MergedText(text=theirs, conflicted=False)
    if base == theirs:
        return MergedText(text=ours, conflicted=False)
    b, o, t = _split(base), _split(ours), _split(theirs)
    if b is None or o is None or t is None:
        return merge_text(base, ours, theirs)
    frontmatter = _merge_frontmatter(b[0], o[0], t[0])
    body = merge_text(b[1], o[1], t[1])
    return MergedText(
        text=f"---\n{frontmatter.text}\n---\n{body.text}",
        conflicted=frontmatter.conflicted or body.conflicted,
    )


def _split(text: str) -> tuple[str, str] | None:
    match = _FRONTMATTER_RE.match(text)
    if match is None:
        return None
    return match.group(1), match.group(2)


def _merge_frontmatter(base: str, ours: str, theirs: str) -> MergedText:
    if ours == theirs or base == theirs:
        return MergedText(text=ours, conflicted=False)
    if base == ours:
        return MergedText(text=theirs, conflicted=False)
    b, o, t = _mapping(base), _mapping(ours), _mapping(theirs)
    if b is None or o is None or t is None:
        return merge_text(base, ours, theirs)
    merged: dict[str, Any] = {}
    conflicted = False
    for key in [
        *t,
        *(k for k in o if k not in t),
        *(k for k in b if k not in t and k not in o),
    ]:
        bv, ov, tv = b.get(key, _MISSING), o.get(key, _MISSING), t.get(key, _MISSING)
        if _same(ov, tv):
            value = ov
        elif _same(ov, bv):
            value = tv
        elif _same(tv, bv):
            value = ov
        else:
            conflicted = True
            value = ov
        if value is not _MISSING:
            merged[key] = value
    if _same_mapping(merged, t):
        return MergedText(text=theirs, conflicted=conflicted)
    if _same_mapping(merged, o):
        return MergedText(text=ours, conflicted=conflicted)
    rendered = yaml.safe_dump(merged, sort_keys=False, allow_unicode=True).rstrip("\n")
    return MergedText(text=rendered, conflicted=conflicted)


def _mapping(text: str) -> dict[str, Any] | None:
    try:
        loaded = yaml.safe_load(text)
    except yaml.YAMLError:
        return None
    if not isinstance(loaded, dict):
        return None
    return {str(key): value for key, value in loaded.items()}


def _same(a: object, b: object) -> bool:
    return _scalar(a) == _scalar(b)


def _same_mapping(a: dict[str, Any], b: dict[str, Any]) -> bool:
    return a.keys() == b.keys() and all(_same(a[key], b[key]) for key in a)


def _scalar(value: object) -> object:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return str(value)
    return value
