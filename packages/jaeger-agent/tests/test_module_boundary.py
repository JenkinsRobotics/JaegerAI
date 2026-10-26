"""The module boundary, asserted rather than hoped for.

``docs/EXTRACTION.md`` states the rule: *JaegerAgent depends on JaegerOS.
JaegerAI depends on JaegerAgent. JaegerAgent must never import JaegerAI.*

Nothing enforced it, and 54 imports accumulated. They are lazy (inside
functions), so the package still imports with no host installed and the
rest of the suite still passes — which is exactly why this went unnoticed:
**the suite proves the package IMPORTS standalone, not that it RUNS
standalone.** Every one of those 54 call sites is untested.

These tests are a RATCHET, not a gate. They pin today's number so it can
only fall. Nobody has to fix 54 imports to land a change; nobody gets to
add a 55th by accident either.

When you remove some, lower the budget in the same commit. That edit is
the point — it is the only place the number is written down, so the
diff shows the boundary moving.
"""

from __future__ import annotations

import ast
import pathlib

# Package code only. Bundled skill scripts under ``jaeger_agent/skills/``
# are payloads with their own dependencies, not library code, and are
# counted separately below.
_PKG = pathlib.Path(__file__).parents[1] / "jaeger_agent"

# ── the budgets ────────────────────────────────────────────────────
# Measured 2026-08-25 at 1.0.5 (54/27 at 1.0.2; 50/25 at 1.0.3 — usage
# telemetry inverted; 47/25 at 1.0.5 — the person index moved to the
# agent's own facts store). Lower as couplings are removed;
# never raise them without a note in the commit message saying why.
MAX_APP_IMPORTS = 37
MAX_APP_IMPORT_FILES = 20

#: Sibling MODULES the mind must never import. Unlike the app budget
#: above, this one is zero and stays zero: TTS and STT are reached as
#: slots and topics. There is no migration in progress here, so any hit
#: is a straightforward mistake.
FORBIDDEN_MODULE_ROOTS = (
    "jaeger_kokoro_tts",
    "jaeger_whisper_stt",
    "jaeger_animation",
)


def _iter_imports(path: pathlib.Path):
    """Yield ``(module, lineno)`` for every absolute import in ``path``."""
    try:
        tree = ast.parse(path.read_text())
    except (SyntaxError, UnicodeDecodeError):  # a skill payload, not code
        return
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name, node.lineno
        elif isinstance(node, ast.ImportFrom) and not node.level:
            yield node.module or "", node.lineno


def _package_files() -> list[pathlib.Path]:
    return [p for p in _PKG.rglob("*.py") if "/skills/" not in str(p)]


def _app_imports() -> list[tuple[pathlib.Path, int, str]]:
    found = []
    for f in _package_files():
        for mod, line in _iter_imports(f):
            if mod == "jaeger_ai" or mod.startswith("jaeger_ai."):
                found.append((f, line, mod))
    return found


def test_no_sibling_module_imports() -> None:
    """Zero, and it must stay zero.

    The mind reaches TTS and STT through slots and topics — never by
    importing the package that fills them. This is what lets JaegerAI and
    Mochi run completely different engines over one agent.
    """
    offenders = [
        f"{f.relative_to(_PKG.parent)}:{line} imports {mod}"
        for f in _package_files()
        for mod, line in _iter_imports(f)
        if mod.split(".")[0] in FORBIDDEN_MODULE_ROOTS
    ]
    assert not offenders, (
        "the mind must not import a sibling module — use the slot and its "
        "topics instead:\n  " + "\n  ".join(offenders)
    )


def test_app_import_budget_does_not_grow() -> None:
    """The ratchet. Fail when the count RISES, and when it falls."""
    found = _app_imports()
    assert len(found) <= MAX_APP_IMPORTS, (
        f"jaeger_ai imports rose to {len(found)} (budget {MAX_APP_IMPORTS}). "
        "The module must not import the application — see docs/EXTRACTION.md. "
        "Push what you need through a seam the host fills, the way "
        "workspace.bind(layout) already does.\n  "
        + "\n  ".join(
            f"{f.relative_to(_PKG.parent)}:{line} -> {mod}" for f, line, mod in found
        )
    )
    # Falling is the goal, but a stale budget hides the next regression:
    # if 10 are removed and the budget stays 54, ten new ones can land
    # unnoticed. So make progress force the edit.
    assert len(found) == MAX_APP_IMPORTS, (
        f"jaeger_ai imports dropped to {len(found)} — good. Lower "
        f"MAX_APP_IMPORTS to {len(found)} in this file, in the same commit, "
        "so the budget keeps meaning something."
    )


def test_app_import_files_do_not_spread() -> None:
    """Count files too: 54 imports in 2 files is a far easier cleanup
    than 54 across 24. Concentration is progress even at a flat total."""
    files = {f for f, _, _ in _app_imports()}
    assert len(files) <= MAX_APP_IMPORT_FILES, (
        f"jaeger_ai imports spread to {len(files)} files "
        f"(budget {MAX_APP_IMPORT_FILES}):\n  "
        + "\n  ".join(sorted(str(f.relative_to(_PKG.parent)) for f in files))
    )


def test_package_imports_with_no_host_installed() -> None:
    """The property the budgets exist to protect.

    Every app import is lazy, so this passes today at 54. It is here to
    fail loudly if one is ever hoisted to module scope — which would make
    the package unimportable without JaegerAI and break every embedder.
    """
    import jaeger_agent  # noqa: F401  — the import IS the assertion

    assert jaeger_agent.__version__
