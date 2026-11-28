"""Token-budgeted repository symbol map with PageRank reference weighting (aider RepoMap pattern)."""

from __future__ import annotations

import ast
import re
from pathlib import Path

_IGNORE_DIRS = frozenset({
    ".git", "__pycache__", "node_modules", ".venv", "venv", "dist", "build", ".tox", ".mypy_cache",
})
_TS_SYMBOL_RE = re.compile(
    r"^\s*(?:export\s+)?(?:async\s+)?(?:function|class|interface|type)\s+([A-Za-z_][A-Za-z0-9_]*)",
    re.MULTILINE,
)
_TOKEN_RE = re.compile(r"[a-z0-9_]+")
_IDENT_RE = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]{2,}\b")


def _extract_python_symbols(text: str) -> tuple[list[str], set[str]]:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return [], set()
    out: list[str] = []
    defined: set[str] = set()
    for node in tree.body:
        lineno = getattr(node, "lineno", 0)
        loc = f" [L{lineno}]" if lineno else ""
        if isinstance(node, ast.ClassDef):
            defined.add(node.name)
            methods = [
                n.name for n in node.body
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and not n.name.startswith("__")
            ]
            suffix = f" ({', '.join(methods[:8])})" if methods else ""
            out.append(f"class {node.name}{suffix}{loc}")
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            defined.add(node.name)
            out.append(f"def {node.name}(){loc}")
    return out, defined


def _extract_ts_symbols(text: str) -> tuple[list[str], set[str]]:
    names = [m.group(1) for m in _TS_SYMBOL_RE.finditer(text)][:12]
    return names, set(names)


def _pagerank(
    nodes: list[str],
    edges: dict[str, set[str]],
    *,
    damping: float = 0.85,
    iterations: int = 8,
) -> dict[str, float]:
    """Lightweight damped PageRank over the file reference graph."""
    n = len(nodes)
    if n == 0:
        return {}
    ranks = {node: 1.0 / n for node in nodes}
    inbound: dict[str, list[str]] = {node: [] for node in nodes}
    out_deg: dict[str, int] = {node: len(edges.get(node, ())) for node in nodes}
    for src, targets in edges.items():
        for dst in targets:
            if dst in inbound:
                inbound[dst].append(src)
    base = (1.0 - damping) / n
    for _ in range(iterations):
        nxt: dict[str, float] = {}
        for node in nodes:
            acc = sum(ranks[src] / max(1, out_deg[src]) for src in inbound[node])
            nxt[node] = base + damping * acc
        ranks = nxt
    return ranks


def _score_entry(rel_str: str, syms: list[str], q_tokens: list[str]) -> int:
    if not q_tokens:
        return 0
    rel_low = rel_str.lower()
    sym_low = " ".join(syms).lower()
    score = 0
    for tok in q_tokens:
        if tok in rel_low:
            score += 3
        if tok in sym_low:
            score += 4
            if f"class {tok}" in sym_low or f"def {tok}(" in sym_low:
                score += 6
    return score


def build_repo_map(
    workspace: Path,
    *,
    subpath: str = "",
    query: str = "",
    max_chars: int = 4000,
    max_files: int = 200,
) -> str:
    """Render a compact, PageRank-ranked, token-budgeted symbol outline of a repository."""
    root = workspace.expanduser().resolve()
    scan_root = (root / subpath).resolve() if subpath else root
    if not scan_root.exists():
        return ""
    if root != scan_root and root not in scan_root.parents:
        raise ValueError(f"subpath escapes workspace: {subpath!r}")

    q_tokens = [t for t in _TOKEN_RE.findall((query or "").lower()) if len(t) >= 2]
    records: list[tuple[str, list[str], set[str], set[str]]] = []
    scanned = 0

    for path in sorted(scan_root.rglob("*")):
        if any(part in _IGNORE_DIRS for part in path.parts):
            continue
        if not path.is_file():
            continue
        if path.suffix not in (".py", ".ts", ".tsx", ".js", ".jsx"):
            continue
        scanned += 1
        if not q_tokens and scanned > max_files:
            break
        if q_tokens and scanned > max(max_files * 8, 2000):
            break
        text = path.read_text(encoding="utf-8", errors="ignore")
        syms, defined = _extract_python_symbols(text) if path.suffix == ".py" else _extract_ts_symbols(text)
        if not syms:
            continue
        rel = str(path.relative_to(root))
        refs = set(_IDENT_RE.findall(text)) - defined
        records.append((rel, syms, defined, refs))

    # Build symbol -> defining files map for reference-graph PageRank
    sym_owners: dict[str, list[str]] = {}
    for rel, _syms, defined, _refs in records:
        for name in defined:
            sym_owners.setdefault(name, []).append(rel)

    nodes = [r[0] for r in records]
    edges: dict[str, set[str]] = {rel: set() for rel in nodes}
    for rel, _syms, _defined, refs in records:
        for ident in refs:
            owners = sym_owners.get(ident)
            if owners and len(owners) <= 4:
                for owner in owners:
                    if owner != rel:
                        edges[rel].add(owner)

    pr = _pagerank(nodes, edges)

    candidates: list[tuple[float, str, list[str]]] = []
    for rel, syms, _defined, _refs in records:
        rank_boost = pr.get(rel, 0.0)
        if q_tokens:
            q_score = _score_entry(rel, syms, q_tokens)
            if q_score > 0:
                candidates.append((float(q_score) + rank_boost * 5.0, rel, syms))
        else:
            candidates.append((rank_boost, rel, syms))

    candidates.sort(key=lambda item: (-item[0], item[1]))

    entries: list[str] = []
    used = 0
    for _score, rel, syms in candidates[:max_files]:
        if q_tokens:
            matched_syms = [s for s in syms if any(t in s.lower() for t in q_tokens)]
            display_syms = matched_syms[:12] + [s for s in syms if s not in matched_syms][:6]
        else:
            display_syms = syms[:16]
        block = f"{rel}:\n" + "\n".join(f"  - {s}" for s in display_syms) + "\n"
        if used + len(block) > max_chars:
            if not entries:
                entries.append(block[:max_chars])
            break
        entries.append(block)
        used += len(block)

    return "".join(entries).strip()


__all__ = ["build_repo_map"]
