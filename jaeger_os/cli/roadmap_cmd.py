"""``jaeger roadmap`` — render the active roadmap.

Read-only view of the markdown roadmap with progress markers
(✓ / · / ✗) so the operator sees what's shipped vs. queued.

Looks for ``dev_docs/ROADMAP_0.5.md`` (or the highest-numbered
ROADMAP at the time), strips the structure, prints the rest.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from . import _common as c


def register(subparsers: Any) -> None:
    parser = subparsers.add_parser(
        "roadmap",
        help="view the active roadmap (current vs. queued vs. deferred)",
    )
    parser.add_argument(
        "--version",
        help="render a specific roadmap (default: highest-numbered)",
        default=None,
    )
    parser.set_defaults(_handler=run_roadmap)


def run_roadmap(args: Any) -> int:
    repo = Path(__file__).resolve().parents[2]
    dev_docs = repo / "dev_docs"
    if not dev_docs.is_dir():
        print(c.red("no dev_docs/ — are you in the JROS repo?"))
        return 1

    target = _pick_roadmap(dev_docs, args.version)
    if target is None:
        print(c.red(
            f"no ROADMAP file found for version {args.version!r}"
            if args.version else "no ROADMAP files in dev_docs/"
        ))
        return 1

    print()
    print(f"  {c.bold('Roadmap')}  {c.dim(str(target.relative_to(repo)))}")
    print()
    raw = target.read_text(encoding="utf-8", errors="replace")
    _render_markdown(raw)
    return 0


# ── pick roadmap ──────────────────────────────────────────────────

def _pick_roadmap(dev_docs: Path, version: str | None) -> Path | None:
    candidates = []
    for p in dev_docs.iterdir():
        m = re.match(r"^ROADMAP[_\-]?(\d+\.\d+(?:\.\d+)?)\.md$", p.name)
        if m:
            candidates.append((m.group(1), p))
    if version is not None:
        for v, path in candidates:
            if v == version:
                return path
        return None
    if not candidates:
        return None
    # Pick highest-numbered (lexicographic on the dotted version
    # happens to be the right order for 0.X / 0.Y / etc.).
    candidates.sort(key=lambda pair: tuple(
        int(part) for part in pair[0].split(".")
    ))
    return candidates[-1][1]


# ── render markdown ───────────────────────────────────────────────

def _render_markdown(text: str) -> None:
    """Minimal terminal renderer for the roadmap doc.  Headings get
    a bold treatment; bullet points get a glyph; everything else is
    printed verbatim with light dimming for context lines."""
    for line in text.splitlines():
        stripped = line.rstrip()
        if not stripped:
            print()
            continue
        # Headings
        if stripped.startswith("### "):
            print()
            print(c.bold("  " + stripped[4:]))
            continue
        if stripped.startswith("## "):
            print()
            print(c.bold(c.cyan(stripped[3:])))
            continue
        if stripped.startswith("# "):
            print()
            print(c.bold(stripped[2:]))
            continue
        # Bullets
        m = re.match(r"^(\s*)[-*]\s+(.*)$", stripped)
        if m:
            indent, body = m.group(1), m.group(2)
            print(f"{indent}  • {body}")
            continue
        # Status table line — light pass-through
        if "|" in stripped:
            print(c.dim(stripped))
            continue
        print(stripped)
