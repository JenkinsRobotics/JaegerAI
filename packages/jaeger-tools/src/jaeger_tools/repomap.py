"""Token-budgeted repository symbol map (aider RepoMap pattern using stdlib Python AST)."""

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


def _extract_python_symbols(path: Path) -> list[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
    except SyntaxError:
        return []
    out: list[str] = []
    for node in tree.body:
        lineno = getattr(node, "lineno", 0)
        loc = f" [L{lineno}]" if lineno else ""
        if isinstance(node, ast.ClassDef):
            methods = [
                n.name for n in node.body
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and not n.name.startswith("__")
            ]
            suffix = f" ({', '.join(methods[:8])})" if methods else ""
            out.append(f"class {node.name}{suffix}{loc}")
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out.append(f"def {node.name}(){loc}")
    return out


def _extract_ts_symbols(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8", errors="ignore")
    return [m.group(1) for m in _TS_SYMBOL_RE.finditer(text)][:12]


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
    """Render a compact, token-budgeted symbol outline of a repository.

    Supports optional ``subpath`` scoping and ``query`` relevance ranking so
    large repositories return the most relevant files and symbol line numbers
    first instead of truncating alphabetically.
    """
    root = workspace.expanduser().resolve()
    scan_root = (root / subpath).resolve() if subpath else root
    if not scan_root.exists():
        return ""
    if root != scan_root and root not in scan_root.parents:
        raise ValueError(f"subpath escapes workspace: {subpath!r}")

    q_tokens = [t for t in _TOKEN_RE.findall((query or "").lower()) if len(t) >= 2]
    candidates: list[tuple[int, str, list[str]]] = []
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
        syms = _extract_python_symbols(path) if path.suffix == ".py" else _extract_ts_symbols(path)
        if not syms:
            continue
        rel = str(path.relative_to(root))
        if q_tokens:
            score = _score_entry(rel, syms, q_tokens)
            if score > 0:
                candidates.append((score, rel, syms))
        else:
            candidates.append((0, rel, syms))

    if q_tokens:
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
