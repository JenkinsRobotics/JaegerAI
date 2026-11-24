"""Swappable code editing engines: SearchReplaceEditor (aider) & ApplyPatchEditor (codex + unified diff)."""

from __future__ import annotations

import difflib
import re
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class EditOutcome:
    ok: bool
    strategy: str
    path: str
    message: str
    replacements: int = 0


@runtime_checkable
class EditEngine(Protocol):
    @property
    def name(self) -> str: ...
    def apply(self, path: Path, payload: dict) -> EditOutcome: ...


def _closest_region_hint(original: str, target: str) -> str:
    o_lines = original.splitlines()
    t_lines = [ln.strip() for ln in target.strip("\n").splitlines()]
    span = max(1, len(t_lines))
    want = "\n".join(t_lines)
    best, best_at = 0.0, -1
    for i in range(max(1, len(o_lines) - span + 1)):
        got = "\n".join(ln.strip() for ln in o_lines[i : i + span])
        ratio = difflib.SequenceMatcher(None, want, got).ratio()
        if ratio > best:
            best, best_at = ratio, i
    if best < 0.45 or best_at < 0:
        return ""
    snippet = "\n".join(o_lines[best_at : best_at + min(span, 8)])
    return f"closest match at lines {best_at + 1}-{best_at + span}:\n{snippet}"


class SearchReplaceEditor:
    """Cascading fault-tolerant editor (aider pattern): exact -> rstrip -> relative indent."""

    @property
    def name(self) -> str:
        return "aider_search_replace"

    def apply(self, path: Path, payload: dict) -> EditOutcome:
        target = str(payload.get("target", ""))
        replacement = str(payload.get("replacement", ""))
        replace_all = bool(payload.get("replace_all", False))
        if not target:
            return EditOutcome(False, self.name, str(path), "Empty search target.")
        if target == replacement:
            return EditOutcome(False, self.name, str(path), "old and new are identical")
        if not path.is_file():
            return EditOutcome(False, self.name, str(path), f"File not found: {path}")

        original = path.read_text(encoding="utf-8")

        # 1. Exact match (with uniqueness enforcement unless replace_all=True)
        count = original.count(target)
        if count > 0:
            if count > 1 and not replace_all:
                lines = [original.count("\n", 0, m.start()) + 1 for m in re.finditer(re.escape(target), original)]
                return EditOutcome(
                    False,
                    self.name,
                    str(path),
                    f"old text appears {count}× (lines {', '.join(map(str, lines[:8]))}) — not unique. "
                    "Pass a longer unique snippet, or replace_all=true.",
                )
            updated = original.replace(target, replacement) if replace_all else original.replace(target, replacement, 1)
            path.write_text(updated, encoding="utf-8")
            return EditOutcome(True, "exact", str(path), "Applied exact replacement.", replacements=count if replace_all else 1)

        # 2. Leading/trailing whitespace-tolerant + relative-indent match (aider pattern)
        orig_lines = original.splitlines(keepends=True)
        targ_raw = target.strip("\n").splitlines()
        targ_stripped = [ln.strip() for ln in targ_raw]
        n = len(targ_raw)
        if n > 0 and any(targ_stripped):
            hits = [
                i
                for i in range(len(orig_lines) - n + 1)
                if [orig_lines[j].strip() for j in range(i, i + n)] == targ_stripped
            ]
            if len(hits) == 1 and not replace_all:
                i = hits[0]
                chunk = "".join(orig_lines[i : i + n])
                first_t = next((ln for ln in targ_raw if ln.strip()), "")
                first_f = next((ln for ln in orig_lines[i : i + n] if ln.strip()), "")
                t_indent = first_t[: len(first_t) - len(first_t.lstrip())]
                f_indent = first_f[: len(first_f) - len(first_f.lstrip())]
                rep_lines = replacement.strip("\n").splitlines()
                reindented_lines = []
                for ln in rep_lines:
                    if t_indent and ln.startswith(t_indent):
                        reindented_lines.append(f_indent + ln[len(t_indent) :])
                    elif not t_indent and ln.strip():
                        reindented_lines.append(f_indent + ln)
                    else:
                        reindented_lines.append(ln)
                reindented = "\n".join(reindented_lines)
                if chunk.endswith("\n") and not reindented.endswith("\n"):
                    reindented += "\n"
                updated = "".join(orig_lines[:i]) + reindented + "".join(orig_lines[i + n :])
                path.write_text(updated, encoding="utf-8")
                strategy = "rstrip_lines" if t_indent == f_indent else "relative_indent"
                return EditOutcome(True, strategy, str(path), "Applied whitespace-tolerant replacement.", replacements=1)
            if len(hits) > 1:
                return EditOutcome(
                    False,
                    self.name,
                    str(path),
                    f"old text matches {len(hits)} places ignoring whitespace (lines "
                    f"{', '.join(str(h + 1) for h in hits[:6])}). Include more surrounding lines to make it unique.",
                )

        hint = _closest_region_hint(original, target)
        return EditOutcome(
            False,
            self.name,
            str(path),
            "old text not found in file" + (f"; {hint}" if hint else ". Re-read the file (read_file) and copy the exact lines."),
        )


class ApplyPatchEditor:
    """Structured hunk patch engine (Codex apply-patch + standard unified diff + Aider SEARCH/REPLACE)."""

    @property
    def name(self) -> str:
        return "codex_apply_patch"

    def apply(self, path: Path, payload: dict) -> EditOutcome:
        patch_text = str(payload.get("patch", "")).replace("\r\n", "\n")
        if not patch_text.strip():
            return EditOutcome(False, self.name, str(path), "Empty patch payload.")
        if not path.is_file():
            return EditOutcome(False, self.name, str(path), f"File not found: {path}")

        # Support Aider SEARCH/REPLACE blocks seamlessly
        sr_blocks = re.findall(
            r"<<<<<<< SEARCH\n(.*?)\n=======\n(.*?)\n>>>>>>> REPLACE",
            patch_text,
            flags=re.DOTALL,
        )
        if sr_blocks:
            editor = SearchReplaceEditor()
            applied = 0
            for old_blk, new_blk in sr_blocks:
                out = editor.apply(path, {"target": old_blk, "replacement": new_blk})
                if not out.ok:
                    return EditOutcome(False, self.name, str(path), out.message, replacements=applied)
                applied += 1
            return EditOutcome(True, "search_replace_blocks", str(path), f"Applied {applied} SEARCH/REPLACE block(s).", replacements=applied)

        lines = path.read_text(encoding="utf-8").splitlines()
        hunks: list[list[str]] = []
        current: list[str] = []
        for raw in patch_text.splitlines():
            if raw.startswith(("--- ", "+++ ", "diff --git ", "index ")):
                continue
            if raw.startswith("@@"):
                if current:
                    hunks.append(current)
                    current = []
                continue
            if raw.startswith("\\"):
                continue
            if raw.startswith((" ", "+", "-")):
                current.append(raw)
        if current:
            hunks.append(current)
        if not hunks:
            return EditOutcome(False, self.name, str(path), "No valid patch hunks found.")

        for hunk in hunks:
            old_seq = [ln[1:] for ln in hunk if ln.startswith((" ", "-"))]
            new_seq = [ln[1:] for ln in hunk if ln.startswith((" ", "+"))]
            pos = self._find_sequence(lines, old_seq)
            if pos is None:
                return EditOutcome(False, self.name, str(path), "Patch hunk context did not match.")
            lines = lines[:pos] + new_seq + lines[pos + len(old_seq) :]

        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return EditOutcome(True, "apply_patch", str(path), f"Applied {len(hunks)} patch hunk(s).", replacements=len(hunks))

    @staticmethod
    def _find_sequence(haystack: list[str], needle: list[str]) -> int | None:
        if not needle:
            return 0
        n = len(needle)
        # 1. Exact sequence match
        for i in range(len(haystack) - n + 1):
            if haystack[i : i + n] == needle:
                return i
        # 2. Trailing-whitespace match
        r_needle = [s.rstrip() for s in needle]
        for i in range(len(haystack) - n + 1):
            if [s.rstrip() for s in haystack[i : i + n]] == r_needle:
                return i
        # 3. Whitespace-trimmed fallback (codex seek_sequence)
        trimmed_needle = [s.strip() for s in needle]
        for i in range(len(haystack) - n + 1):
            if [s.strip() for s in haystack[i : i + n]] == trimmed_needle:
                return i
        return None
