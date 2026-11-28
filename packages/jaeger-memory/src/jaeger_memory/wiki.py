"""Private-Safe Local Markdown Knowledge Wiki Store.

Adapted from ARES (`core/knowledge/wiki_store.py`) with strict symlink,
hardlink, path-traversal, and forbidden-root guards so Jaeger can maintain a
structured local wiki (`entities/`, `concepts/`, `comparisons/`, `queries/`,
`notes/`) cleanly under `<state_dir>/wiki/` with zero external daemons.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

WIKI_SECTIONS: tuple[str, ...] = ("entities", "concepts", "comparisons", "queries", "notes")
MAX_WIKI_FILES = 5_000
MAX_WIKI_PAGE_BYTES = 2 * 1024 * 1024
_FORBIDDEN_ROOTS = {str(Path(p).resolve()) for p in ("/", "/etc", "/usr", "/var", "/opt", "/sys", "/proc")}
_SLUG_RE = re.compile(r"[^a-z0-9_-]+")


class WikiStoreError(ValueError):
    """Raised on invalid wiki path, forbidden root, or size/link policy violation."""


class LocalWikiStore:
    """Safe, symlink-proof local Markdown knowledge wiki."""

    def __init__(self, root_dir: Path) -> None:
        resolved = Path(root_dir).expanduser().resolve()
        if str(resolved) in _FORBIDDEN_ROOTS:
            raise WikiStoreError(f"Refusing forbidden wiki root: {resolved}")
        self._root = resolved
        self._root.mkdir(parents=True, exist_ok=True)
        for sec in WIKI_SECTIONS:
            (self._root / sec).mkdir(parents=True, exist_ok=True)

    @property
    def root(self) -> Path:
        return self._root

    def _safe_entries(self) -> dict[str, Path]:
        entries: dict[str, Path] = {}
        visited = 0
        for sec in WIKI_SECTIONS:
            sec_dir = self._root / sec
            if not sec_dir.is_dir() or sec_dir.is_symlink():
                continue
            for md in sorted(sec_dir.rglob("*.md")):
                visited += 1
                if visited > MAX_WIKI_FILES:
                    return entries
                try:
                    if md.is_symlink():
                        continue
                    rel = md.relative_to(self._root)
                    if any(part.startswith(".") or part in ("", ".", "..") for part in rel.parts):
                        continue
                    st = md.lstat()
                    if st.st_nlink > 1 or not md.is_file() or st.st_size > MAX_WIKI_PAGE_BYTES:
                        continue
                    target = md.resolve()
                    target.relative_to(sec_dir.resolve())
                    entries[rel.as_posix()] = target
                except (OSError, ValueError):
                    continue
        return entries

    def browse(self, *, section: str | None = None) -> list[dict[str, Any]]:
        entries = self._safe_entries()
        pages: list[dict[str, Any]] = []
        for rel, path in sorted(entries.items(), key=lambda kv: kv[0].lower()):
            sec = rel.split("/", 1)[0]
            if section and sec != section:
                continue
            try:
                st = path.stat()
            except OSError:
                continue
            pages.append({
                "path": rel,
                "section": sec,
                "name": path.stem,
                "size": st.st_size,
                "mtime": int(st.st_mtime),
            })
        return pages

    def read_page(self, relative_path: str) -> dict[str, Any]:
        rel = str(relative_path or "").strip().lstrip("/")
        entries = self._safe_entries()
        target = entries.get(rel)
        if target is None:
            raise WikiStoreError(f"Wiki page not found or not allowed: {rel}")
        text = target.read_text(encoding="utf-8", errors="replace")
        return {
            "path": rel,
            "section": rel.split("/", 1)[0],
            "name": target.stem,
            "content": text,
            "size": len(text.encode("utf-8")),
        }

    def write_page(self, *, section: str, name: str, content: str) -> dict[str, Any]:
        sec = str(section or "notes").strip().lower()
        if sec not in WIKI_SECTIONS:
            raise WikiStoreError(f"Invalid section {sec!r}; expected one of {', '.join(WIKI_SECTIONS)}")
        slug = _SLUG_RE.sub("-", str(name or "").strip().lower()).strip("-_")[:64]
        if not slug:
            raise WikiStoreError("Page name must contain alphanumeric characters")
        body = str(content or "")
        if len(body.encode("utf-8")) > MAX_WIKI_PAGE_BYTES:
            raise WikiStoreError("Wiki page exceeds 2 MiB limit")
        target = (self._root / sec / f"{slug}.md").resolve()
        target.relative_to((self._root / sec).resolve())
        tmp = target.with_suffix(".md.tmp")
        tmp.write_text(body, encoding="utf-8")
        os.replace(tmp, target)
        rel = f"{sec}/{slug}.md"
        return {"path": rel, "section": sec, "name": slug, "size": len(body.encode("utf-8"))}

    def search(self, query: str, *, limit: int = 10) -> list[dict[str, Any]]:
        tokens = [t for t in re.findall(r"[a-z0-9]+", (query or "").lower()) if len(t) >= 2]
        entries = self._safe_entries()
        hits: list[tuple[int, dict[str, Any]]] = []
        for rel, path in entries.items():
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            low = (rel + "\n" + text).lower()
            score = sum(low.count(tok) for tok in tokens) if tokens else 1
            if score > 0:
                snippet = " ".join(text.split())[:220]
                hits.append((
                    score,
                    {
                        "path": rel,
                        "section": rel.split("/", 1)[0],
                        "name": path.stem,
                        "score": score,
                        "snippet": snippet,
                    },
                ))
        hits.sort(key=lambda item: (-item[0], item[1]["path"]))
        return [h for _, h in hits[: max(1, min(int(limit), 50))]]


__all__ = ["LocalWikiStore", "WIKI_SECTIONS", "WikiStoreError"]
