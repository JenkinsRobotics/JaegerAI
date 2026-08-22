"""The CI dependency rule — the nervous-system law, enforced not promised.

dev/docs/vision/THREE_TIER_STRUCTURE.md, law 2: lower layers never wait
on higher ones. Concretely:

  * ``jaeger_os.contract`` imports nothing from the rest of ``jaeger_os``
    (already enforced by dev/tests/jaeger_os/contract/test_no_inward_imports.py
    — re-asserted here as one line so a reader of *this* file sees the
    whole rule in one place).
  * ``jaeger_os.transport`` / ``jaeger_os.nodes`` / ``jaeger_os.hardware``
    / ``jaeger_os.app`` (the runtime tier) never import
    ``jaeger_os.agent`` (the Mind). The e-stop lives below the Mind —
    a runtime module that imports agent/ could not be trusted to keep
    working if the Mind never boots, which breaks the whole point of
    the tiering (JP01 must run headless).

Static AST scan, same technique as the contract test: no import side
effects, no need to actually import every module with its optional
hardware/model dependencies.

``main.py`` and ``jaeger_os/cli/`` are PROJECT/bringup tier — they
assemble the Mind + the runtime into a running instance, so they are
*expected* to import agent/. They are deliberately not scanned here.

0.9 step 2 audit (dev/docs/vision/THREE_TIER_STRUCTURE.md's split
ladder) found five real violations, all fixed by inversion rather than
allowlisted:

  * ``hardware/capabilities.py`` + ``hardware/packages/jp01/boot.py``
    imported ``agent.schemas.{tool_registry,tool_schema}`` to register
    hardware capabilities as tools. Fix: the tool contract
    (``ToolDef`` + the process-wide registry + arg coercion) moved to
    ``jaeger_os.core.tools`` — it was never agent-owned, agent is its
    primary *reader*, not its owner.
  * ``nodes/runtime.py`` imported ``agent.tools.speak._resolve_voice``
    to pick a Kokoro voice at node-boot time. Fix: the resolution
    logic (pure instance-config lookup, no tool-calling concern) moved
    to ``jaeger_os.core.voice.voice_resolution``.
  * ``nodes/animation/auto_state.py`` + ``nodes/animation_dev/auto_state.py``
    imported ``agent.tools.avatar._DEFAULT_EXPRESSIONS`` /
    ``_FRAMEWORK_AVATAR_DEFAULTS`` to publish AnimationCommands that
    match an explicit ``set_avatar_state`` call. Fix: the static
    emotion->asset table moved to each animation package's own
    ``expression_defaults.py``; the agent tool now imports FROM the
    node (the correct direction), not the other way around.

ALLOWLIST is empty on purpose — that's the gate. Only add an entry
with an inline justification comment if a violation is genuinely hard
to invert (see dev/docs/vision/THREE_TIER_STRUCTURE.md's "isolate +
document rather than hack" guidance); every entry here is a debt, not
a shrug.
"""

from __future__ import annotations

import ast
import pathlib

import jaeger_os

REPO_ROOT = pathlib.Path(jaeger_os.__file__).resolve().parent

# The runtime tier — enforced. transport/nodes/hardware/app must never
# import jaeger_os.agent (or any of its submodules).
ENFORCED_DIRS = ("transport", "nodes", "hardware", "app")

# Grandfathered exceptions, keyed by path relative to jaeger_os/.
# Each entry MUST carry a justification comment. Empty by design —
# the audit that introduced this test found zero cases hard enough to
# warrant one; every real violation was inverted instead.
ALLOWLIST: dict[str, tuple[str, ...]] = {
    # "nodes/example.py": ("from jaeger_os.agent.x import y",),  # why
}


def _iter_py_files(dir_name: str) -> list[pathlib.Path]:
    return sorted((REPO_ROOT / dir_name).rglob("*.py"))


def _agent_imports(path: pathlib.Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    offenders: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                name = alias.name
                if name == "jaeger_os.agent" or name.startswith("jaeger_os.agent."):
                    offenders.append(f"import {name}")
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                # Relative imports inside jaeger_os.agent itself can't
                # reach these directories; relative imports inside
                # these directories can't reach jaeger_os.agent either
                # (no relative path walks from transport/nodes/hardware/
                # app into agent). Nothing to check.
                continue
            module = node.module or ""
            if module == "jaeger_os.agent" or module.startswith("jaeger_os.agent."):
                offenders.append(f"from {module} import ...")
    return offenders


def test_enforced_dirs_exist_and_are_nonempty():
    for d in ENFORCED_DIRS:
        files = _iter_py_files(d)
        assert files, f"expected {d}/ to contain python files, found none"


def test_runtime_tier_never_imports_agent():
    violations: dict[str, list[str]] = {}
    for d in ENFORCED_DIRS:
        for path in _iter_py_files(d):
            rel = str(path.relative_to(REPO_ROOT))
            offenders = _agent_imports(path)
            if not offenders:
                continue
            allowed = ALLOWLIST.get(rel, ())
            leftover = [o for o in offenders if o not in allowed]
            if leftover:
                violations[rel] = leftover
    assert not violations, (
        "runtime tier (transport/nodes/hardware/app) must never import "
        "jaeger_os.agent (nervous-system rule, THREE_TIER_STRUCTURE.md "
        f"law 2): {violations}"
    )


def test_contract_still_imports_nothing():
    """One-line re-assertion that the step-1 rule still holds — the
    full test lives in
    dev/tests/jaeger_os/contract/test_no_inward_imports.py; this is a
    trip-wire so a reader of the layering suite sees both halves of
    the law pass together."""
    import jaeger_os.contract as _contract

    contract_dir = pathlib.Path(_contract.__file__).resolve().parent
    violations: dict[str, list[str]] = {}
    for path in sorted(contract_dir.glob("*.py")):
        offenders = []
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
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
                if node.level:
                    continue
                module = node.module or ""
                if module == "jaeger_os" or (
                    module.startswith("jaeger_os.")
                    and not module.startswith("jaeger_os.contract")
                ):
                    offenders.append(f"from {module} import ...")
        if offenders:
            violations[path.name] = offenders
    assert not violations, f"jaeger_os/contract regression: {violations}"
