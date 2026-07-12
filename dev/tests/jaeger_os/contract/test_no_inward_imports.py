"""jaeger_os.contract imports NOTHING from the rest of jaeger_os.

The nervous-system rule (dev/docs/vision/THREE_TIER_STRUCTURE.md, law 2):
lower layers never wait on higher ones. ``contract`` is the lowest layer —
stdlib + msgspec (and, elsewhere in the repo, pydantic for validation-facing
types) only. A single accidental ``from jaeger_os.core import ...`` inside
the contract package would silently reintroduce the exact cross-layer
coupling the 0.9 split exists to retire, so this is enforced by CI, not
promised in a docstring.

Static AST scan (no import side effects, no need to actually import every
module with its optional dependencies) over every ``.py`` file under
``jaeger_os/contract/``: every ``import``/``from ... import`` naming
``jaeger_os`` must resolve to ``jaeger_os.contract`` itself (a submodule
importing a sibling submodule, e.g. ``hardware.package`` importing
``capability``, is fine and expected).
"""

from __future__ import annotations

import ast
import pathlib

import jaeger_os.contract as _contract

CONTRACT_DIR = pathlib.Path(_contract.__file__).resolve().parent


def _iter_contract_source_files() -> list[pathlib.Path]:
    return sorted(CONTRACT_DIR.glob("*.py"))


def _offending_imports(path: pathlib.Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    offenders: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                name = alias.name
                if name == "jaeger_os" or (
                    name.startswith("jaeger_os.")
                    and not name.startswith("jaeger_os.contract")
                ):
                    offenders.append(f"import {name}")
        elif isinstance(node, ast.ImportFrom):
            # Relative imports (node.level > 0) are always intra-contract —
            # there's nothing above jaeger_os.contract to relatively import
            # from without walking off the package.
            if node.level:
                continue
            module = node.module or ""
            if module == "jaeger_os" or (
                module.startswith("jaeger_os.")
                and not module.startswith("jaeger_os.contract")
            ):
                offenders.append(f"from {module} import ...")
    return offenders


def test_contract_package_exists_and_is_nonempty():
    files = _iter_contract_source_files()
    # __init__, topics, protocol, capability, modules, ports, wire (>= 6
    # real modules besides __init__) — a sanity floor so this test can't
    # silently pass against an empty/misplaced directory.
    assert len(files) >= 7, f"expected the full contract package, found {files}"


def test_contract_imports_nothing_from_jaeger_os():
    violations: dict[str, list[str]] = {}
    for path in _iter_contract_source_files():
        offenders = _offending_imports(path)
        if offenders:
            violations[path.name] = offenders
    assert not violations, (
        "jaeger_os/contract/ must import nothing from jaeger_os outside "
        f"itself (nervous-system rule): {violations}"
    )
