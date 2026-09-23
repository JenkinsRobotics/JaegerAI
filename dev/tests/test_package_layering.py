"""Dependency-direction ratchet (Q01; RELEASE_AUDIT.md A07).

Target (RELEASE_AGENT_PROMPT.md section 5): reusable packages never import the
product; core/mind never import the WebUI's bare ``api.*`` modules. Existing
violations are frozen in ``fixtures/package_layering_baseline.json`` while
H01 extracts them. This test fails when

* a file gains an upward import it did not have (new growth), or
* a baselined import disappears but the baseline was not ratcheted down
  (so the recorded debt always matches the code).

Static AST scan: no module is imported, so optional dependencies and import
side effects cannot mask a violation. Imports inside functions count — a
lazy upward import is still an upward dependency.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
BASELINE = Path(__file__).resolve().parent / "fixtures" / "package_layering_baseline.json"

#: rule name -> (source roots, forbidden top-level module predicate)
RULES = {
    "jaeger_os_imports_product_or_agent": (
        ["packages/jaeger-os/jaeger_os"],
        lambda module: module.split(".")[0] in {"jaeger_ai", "jaeger_agent"},
    ),
    "jaeger_agent_imports_product": (
        ["packages/jaeger-agent/jaeger_agent"],
        lambda module: module.split(".")[0] == "jaeger_ai",
    ),
    "core_or_mind_imports_webui_api": (
        ["jaeger_ai/core", "jaeger_ai/mind"],
        lambda module: module == "api" or module.startswith("api.")
        or module.startswith("jaeger_ai.features.webui"),
    ),
}


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.add(node.module)
    return found


def scan() -> dict[str, dict[str, list[str]]]:
    result: dict[str, dict[str, list[str]]] = {}
    for rule, (roots, forbidden) in RULES.items():
        hits: dict[str, list[str]] = {}
        for root in roots:
            for path in sorted((REPO / root).rglob("*.py")):
                bad = sorted(m for m in _imports(path) if forbidden(m))
                if bad:
                    hits[str(path.relative_to(REPO))] = bad
        result[rule] = hits
    return result


def test_no_new_upward_imports_and_baseline_is_current():
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    current = scan()
    problems: list[str] = []
    for rule in RULES:
        allowed = {f: set(m) for f, m in baseline.get(rule, {}).items()}
        actual = {f: set(m) for f, m in current[rule].items()}
        for path, modules in actual.items():
            new = modules - allowed.get(path, set())
            if new:
                problems.append(f"NEW {rule}: {path} imports {sorted(new)}")
        for path, modules in allowed.items():
            gone = modules - actual.get(path, set())
            if gone:
                problems.append(f"STALE baseline {rule}: {path} no longer imports {sorted(gone)} "
                                "— remove it from the baseline (ratchet down)")
    assert not problems, "\n".join(problems)


def test_baseline_totals_only_shrink():
    """Recorded ceiling per rule; lower it in the same change that removes debt."""
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    ceilings = baseline["_ceilings"]
    for rule in RULES:
        count = sum(len(v) for v in baseline.get(rule, {}).values())
        assert count <= ceilings[rule], (rule, count, ceilings[rule])


if __name__ == "__main__":  # regenerate: python dev/tests/test_package_layering.py
    data: dict = scan()
    data["_ceilings"] = {rule: sum(len(m) for m in hits.values()) for rule, hits in data.items()}
    BASELINE.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(data["_ceilings"]))
