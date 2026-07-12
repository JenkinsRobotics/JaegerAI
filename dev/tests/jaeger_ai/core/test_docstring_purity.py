"""Tool docstring purity — POLISH-6 in docs/ROADMAP_0.2.0.md.

``core/prompts/rules.py`` carries the imperative behavioural text the
agent reads every turn ("you MUST call X", "always run Y first",
"never claim Z"). Tool docstrings are a DIFFERENT contract: they
describe what a tool DOES — its inputs, outputs, and side effects —
not when the agent should reach for it. Mixing the two duplicates
the contract and lets the two copies drift.

This linter scans every public function in ``core/tools/`` for
imperative-behavioural phrases and reports each match. The current
codebase has known violations from the 0.1.x era; this test runs as
a SCOREBOARD (records the count + sample) rather than a hard
failure, so each future PR sees whether the score moved.

Flip ``ENFORCE_CEILING = True`` once we've worked the count down to
zero — at that point the test fails on any regression.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

import jaeger_os

# 0.9 step 4 split: core/tools/ moved to JaegerOS (framework, a pinned
# dependency) — resolved off the INSTALLED package, not a monorepo-
# relative REPO / "jaeger_os" / ... path, which stopped existing here.
REPO = Path(__file__).resolve().parents[4]
TOOLS_DIR = Path(jaeger_os.__file__).resolve().parent / "core" / "tools"


# Imperative phrases that signal "this docstring is telling the agent
# WHEN to act" rather than "this is what the tool does". Tuned to
# avoid the common input-spec false positives — "must appear once",
# "must be a string", "must be a key in …" are arg-validation
# language, not behavioural rules, and stay below this radar.
_BEHAVIOURAL_PATTERNS: tuple[re.Pattern[str], ...] = (
    # "you MUST" — pure behavioural; the bare "must" alone catches
    # arg constraints and lands too many false positives.
    re.compile(r"\byou MUST\b"),
    re.compile(r"\balways call\b", re.IGNORECASE),
    re.compile(r"\bnever (?:call|use|do|claim|answer)\b", re.IGNORECASE),
    re.compile(r"\bdo NOT (?:call|use|echo|store|skip|free-?text|claim)\b"),
    re.compile(r"\bcall (?:this )?(?:BEFORE|AFTER|FIRST|LAST)\b",
               re.IGNORECASE),
    re.compile(r"\bis forbidden\b", re.IGNORECASE),
    re.compile(r"\bis expected\b", re.IGNORECASE),
    re.compile(r"\bis lying\b", re.IGNORECASE),
    re.compile(r"\bthe MOMENT\b"),
)


# Toggle this when we want the linter to FAIL on regression. Today
# the existing codebase has violations; we record them rather than
# block CI. Future PRs that touch tool docstrings should NOT raise
# the count.
ENFORCE_CEILING = False


def _iter_tool_files():
    for path in sorted(TOOLS_DIR.rglob("*.py")):
        if path.name.startswith("_"):
            continue
        yield path


def _scan_module(path: Path) -> list[tuple[str, str, str]]:
    """Return [(qualified_name, pattern, snippet), …] for every
    public function whose docstring trips a behavioural pattern."""
    findings: list[tuple[str, str, str]] = []
    src = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(src, filename=str(path))
    except SyntaxError:
        return []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name.startswith("_"):
            continue
        doc = ast.get_docstring(node) or ""
        if not doc:
            continue
        for pat in _BEHAVIOURAL_PATTERNS:
            m = pat.search(doc)
            if m:
                # Capture the matched line + a tiny surrounding context.
                start = max(0, m.start() - 20)
                end = min(len(doc), m.end() + 60)
                snippet = doc[start:end].replace("\n", " ").strip()
                try:
                    rel = path.relative_to(REPO)
                except ValueError:
                    rel = path
                qualname = f"{rel}:{node.lineno} {node.name}"
                findings.append((qualname, pat.pattern, snippet))
                break  # one finding per function is enough for the score
    return findings


def test_collect_behavioural_findings():
    """Walk every tool file, collect findings, and either fail (when
    ``ENFORCE_CEILING`` is on) or write them out so the next PR can
    see whether the count moved.

    Skip-by-default-not-fail keeps the linter useful during the long
    sweep without turning every PR into a docstring-rewrite session.
    """
    all_findings: list[tuple[str, str, str]] = []
    for path in _iter_tool_files():
        all_findings.extend(_scan_module(path))

    # ``score`` lands in pytest's captured output so a human can read
    # what the sweep needs to address next.
    score = len(all_findings)
    print(f"\n[docstring-purity] {score} behavioural-text finding(s) "
          f"across core/tools/")
    for qual, pat, snip in all_findings[:20]:
        print(f"  • {qual}  ({pat})")
        print(f"      …{snip}…")
    if len(all_findings) > 20:
        print(f"  …and {len(all_findings) - 20} more")

    if ENFORCE_CEILING:
        assert score == 0, (
            f"docstring purity regressed — {score} behavioural phrase(s) "
            "in core/tools/ docstrings. Move imperative text into "
            "core/prompts/rules.py and keep tool docstrings to "
            "input/output/side-effect descriptions."
        )


def test_linter_catches_obvious_violation_synthetic():
    """Sanity-check the patterns: a synthetic docstring with one of
    each pattern must produce findings. If this regresses, the
    scoreboard test is silently passing because the matcher broke."""
    import textwrap
    src = textwrap.dedent('''
        def foo():
            """You MUST call this BEFORE answering. Never claim
            otherwise. Do NOT skip. Is forbidden to ignore.
            """
            return 0
    ''')
    tmp = Path("/tmp/_purity_synth.py")
    tmp.write_text(src)
    findings = _scan_module(tmp)
    tmp.unlink(missing_ok=True)
    assert findings, "linter failed to match any pattern on a stuffed docstring"


def test_skip_private_functions():
    """Patterns inside ``_helper`` docstrings are out of scope —
    only the model-visible tool surface matters."""
    import textwrap
    src = textwrap.dedent('''
        def _helper():
            """You MUST call this — but it's private so it doesn't matter."""
            return 0
    ''')
    tmp = Path("/tmp/_purity_priv.py")
    tmp.write_text(src)
    findings = _scan_module(tmp)
    tmp.unlink(missing_ok=True)
    assert findings == []
