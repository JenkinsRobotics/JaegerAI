"""Structural conventions, enforced rather than documented and hoped for.

The 2026-09-14 audit found the tree had drifted from `STRUCTURE.md` in ways no
test could see: sixteen feature folders with no README, twelve compatibility
shims nothing needed any more, and seven files duplicated across the tree — four
of which had silently diverged from the copy that actually ran, so editing the
documented file changed nothing and reported no error.

Every rule below is one of those failure modes. They exist so the next drift
fails CI instead of costing someone an afternoon.
"""
from __future__ import annotations

import pathlib
import re

import pytest

REPO = pathlib.Path(__file__).resolve().parents[3]
FEATURES = REPO / "jaeger_ai" / "features"
ASSETS = REPO / "jaeger_ai" / "assets"


def _feature_dirs() -> list[pathlib.Path]:
    return sorted(
        d for d in FEATURES.iterdir()
        if d.is_dir() and not d.name.startswith((".", "__"))
    )


@pytest.mark.parametrize("feature", _feature_dirs(), ids=lambda d: d.name)
def test_every_feature_folder_has_a_readme(feature: pathlib.Path) -> None:
    """A non-coder must be able to open any feature folder and learn what it is.

    ``STRUCTURE.md`` promises this of every feature; before the audit only 7 of
    23 delivered it.
    """
    readme = feature / "README.md"
    assert readme.is_file(), (
        f"{feature.name}/ has no README.md. Every feature folder needs one — "
        f"what it does, how to turn it on, which file to edit, how to tell it "
        f"works. Four honest sentences is enough."
    )
    body = readme.read_text(encoding="utf-8").strip()
    assert len(body) > 200, (
        f"{feature.name}/README.md is a stub ({len(body)} chars). Describe the "
        f"feature from its code, not from the folder name."
    )


def test_no_compatibility_shims_remain() -> None:
    """A moved module gets its importers repointed, not a re-export left behind.

    Each shim doubles the number of places a reader must look for the same
    code. Twelve had accumulated across ``features/hermes_webui/``,
    ``interfaces/hermes_webui_adapter/``, ``core/runtime/dispatch*.py`` and the
    ``roundtable_*`` modules before they were removed.
    """
    offenders = []
    for path in (REPO / "jaeger_ai").rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        head = path.read_text(encoding="utf-8", errors="ignore")[:400].lower()
        # Both spellings, with and without the "ibility". The first version of
        # this test matched only "backwards-compatibility shim" and so missed
        # four shims under core/models/ that say "backward-compatibility".
        if re.search(r"back(?:ward|wards)-compat(?:ibility)? shim", head):
            offenders.append(str(path.relative_to(REPO)))
    assert not offenders, (
        "Compatibility shims found:\n  " + "\n  ".join(offenders) +
        "\nRepoint the importers and delete the old module in the same change."
    )


def test_browser_extension_scripts_have_exactly_one_copy() -> None:
    """``jaeger_ai/assets/`` is the WebUI's single extension mount.

    Feature-local ``static/`` copies of these scripts are not loaded by
    anything. Two of them had drifted 165 and 12 lines from the live file, so
    editing the feature copy silently did nothing.
    """
    duplicates = []
    for script in sorted(ASSETS.glob("*.js")) + sorted(ASSETS.glob("*.json")):
        others = [
            p for p in (REPO / "jaeger_ai").rglob(script.name)
            if p != script and "__pycache__" not in p.parts
        ]
        duplicates += [f"{script.name}: also at {p.relative_to(REPO)}" for p in others]
    assert not duplicates, (
        "Extension scripts duplicated outside jaeger_ai/assets/:\n  "
        + "\n  ".join(duplicates)
        + "\nassets/ is the only directory the WebUI loads; delete the copy."
    )


def test_operator_scripts_are_not_duplicated_inside_features() -> None:
    """One home per script. ``scripts/`` holds the operator entry points.

    ``features/webui/scripts/`` once held four near-copies; two had diverged
    from the versions that actually run, and the feature's own README pointed
    readers at the dead ones.
    """
    stray = [
        str(d.relative_to(REPO))
        for d in FEATURES.glob("*/scripts")
        if d.is_dir()
    ]
    assert not stray, (
        "Feature-local scripts/ directories found:\n  " + "\n  ".join(stray) +
        "\nOperator scripts live in scripts/ — reference them, don't copy them."
    )


def test_interfaces_holds_only_client_surfaces() -> None:
    """``interfaces/`` is how someone connects, never what runs a turn.

    Per-framework turn execution sat in ``interfaces/hermes_profile_adapters/``
    while the Gateway, Roundtable and the Dispatcher all imported it — none of
    which are user interfaces. It now lives in ``core/frameworks/``.
    """
    interfaces = REPO / "jaeger_ai" / "interfaces"
    allowed = {
        "swift", "tui", "pyside6", "messaging", "avatar", "avatar_chat",
        "avatar_player", "gateway",
    }
    unexpected = sorted(
        d.name for d in interfaces.iterdir()
        if d.is_dir() and not d.name.startswith((".", "__")) and d.name not in allowed
    )
    assert not unexpected, (
        f"Unrecognised package(s) under interfaces/: {unexpected}. "
        f"If it runs agent work rather than connecting a client, it belongs in "
        f"core/ (shared) or features/ (optional). If it really is a new client "
        f"surface, add it to this test's allow-list."
    )


def test_nothing_constructs_an_unpinned_bridge_client() -> None:
    """Every bridge client names its instance; none may follow the UI pointer.

    A bare ``BridgeClient()`` resolves ``~/.jaeger/active_instance``, which
    records which delegate a person last selected — choosing "Everyday"
    rewrites it, because ``AgentRegistry.set_active()`` writes a sticky
    instance for native agents.

    Roundtable's Jaeger seat did exactly this and sent its turn to
    ``instances/everyday/run/bridge.sock``. No listener, the member failed with
    no error recorded, and the whole debate aborted with "a member outcome is
    unknown" while the other two members were fine — so it read as Roundtable
    being broken rather than one seat dialling the wrong number.

    Use ``jaeger_bridge()`` for Jaeger's own instance, or pass one explicitly.
    """
    import ast

    offenders: list[str] = []
    for path in (REPO / "jaeger_ai").rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "BridgeClient"
                    and not node.args and not node.keywords):
                offenders.append(f"{path.relative_to(REPO)}:{node.lineno}")
    assert not offenders, (
        "unpinned BridgeClient() found:\n  " + "\n  ".join(offenders) +
        "\nUse jaeger_bridge() for Jaeger's own instance, or pass the instance "
        "name. A bare client follows whichever delegate the UI last selected."
    )
