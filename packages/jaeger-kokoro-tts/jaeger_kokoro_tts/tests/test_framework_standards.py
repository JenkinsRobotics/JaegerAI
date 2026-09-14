"""Framework-standard module gates.

Every JaegerOS module must pass these — they are the properties that
make a folder a MODULE rather than a package that happens to import the
framework. Kept identical across module repos on purpose; the canonical
copy lives in Jaeger-Template.

The one they exist for: a manifest may only name topics that are real
contract topics. Without this gate a typo, or a topic left behind by a
contract migration, produces a node that subscribes successfully and
then silently never receives anything.
"""

from __future__ import annotations

import ast
import importlib
import importlib.util
import pathlib

import pytest
import yaml

PACKAGE = pathlib.Path(__file__).resolve().parents[1]
MANIFEST = yaml.safe_load((PACKAGE / "module.yaml").read_text())

#: Tier discipline. An engine module pins the FRAMEWORK and never the
#: AI product, so a robot body can run it with no Mind installed.
FORBIDDEN = {"jaeger_ai": "JaegerAI — a module pins JaegerOS only"}


def _source_files() -> list[pathlib.Path]:
    return [p for p in PACKAGE.rglob("*.py") if "tests" not in p.parts]


# ── the manifest is real ─────────────────────────────────────────

def test_manifest_validates_against_installed_jaeger_os() -> None:
    from jaeger_os.core.modules import load_module

    spec = load_module(PACKAGE)          # takes the DIR, not the file
    assert spec.module == MANIFEST["module"]
    assert spec.slot == MANIFEST["slot"]


def test_manifest_declares_stable_identity() -> None:
    assert MANIFEST["id"] == "org.jenkinsrobotics.tts.kokoro"
    assert MANIFEST["name"] == "JaegerKokoroTTS"
    assert MANIFEST["type"] == "module"
    assert MANIFEST["implementation"] == "kokoro"


def test_manifest_factory_resolves() -> None:
    """A factory that does not import is a module that cannot boot."""
    dotted, _, attr = MANIFEST["factory"].partition(":")
    mod = importlib.import_module(dotted)
    assert callable(getattr(mod, attr)), f"{MANIFEST['factory']} not callable"


def test_kind_is_declared_and_legal() -> None:
    from jaeger_os.contract.modules import MODULE_KINDS

    kind = MANIFEST.get("kind", "")
    assert kind, "module.yaml must declare `kind` (the ownership axis)"
    assert kind in MODULE_KINDS, f"{kind!r} not in {sorted(MODULE_KINDS)}"


# ── topics ───────────────────────────────────────────────────────

def _declared_topics() -> set[str]:
    return set(MANIFEST.get("consumes") or []) | set(MANIFEST.get("produces") or [])


def test_declared_topics_exist_in_the_contract() -> None:
    """The gate this file exists for. A topic that is not in the
    contract binds a node to something nothing publishes, and the
    failure is silent — subscribe succeeds, delivery never happens."""
    from jaeger_os.transport import topics

    unknown = _declared_topics() - set(topics.ALL_TOPICS)
    assert not unknown, f"not in the contract: {sorted(unknown)}"


def test_every_declared_topic_obeys_the_path_grammar() -> None:
    """Checked separately from the contract membership above: a flat
    legacy topic still passes `canonical()` unchanged, so a name left
    un-migrated can satisfy one check and not the other."""
    from jaeger_os.contract.paths import instance_of, parse

    for topic in _declared_topics():
        parse(topic)
        assert instance_of(topic) == "", (
            f"{topic} names an instance; a manifest declares CANONICAL "
            f"topics and the runtime binds instances to them")


def test_declared_topics_match_what_the_source_uses() -> None:
    """The manifest is the one copy of this truth (CONVENTIONS law 1).
    Every contract constant the source touches must be declared."""
    from jaeger_os.transport import topics

    declared = _declared_topics()
    used: set[str] = set()
    for path in _source_files():
        for node in ast.walk(ast.parse(path.read_text())):
            if (isinstance(node, ast.Attribute)
                    and isinstance(node.value, ast.Name)
                    and node.value.id == "topics"
                    and node.attr.isupper()):
                value = getattr(topics, node.attr, None)
                if isinstance(value, str) and value.startswith("/"):
                    used.add(value)
    undeclared = used - declared
    assert not undeclared, (
        f"source uses topics the manifest does not declare: "
        f"{sorted(undeclared)}")


# ── tier discipline ──────────────────────────────────────────────

@pytest.mark.parametrize("forbidden,why", sorted(FORBIDDEN.items()))
def test_never_imports(forbidden: str, why: str) -> None:
    """Structural, not aspirational: parse every import statement."""
    for path in _source_files():
        for node in ast.walk(ast.parse(path.read_text())):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for name in names:
                assert not name.split(".")[0] == forbidden, (
                    f"{path.relative_to(PACKAGE)} imports {name} — {why}")


def test_declared_libraries_are_importable() -> None:
    """`requires_libraries` is what the availability gate probes before
    reporting this module's tools usable. A name that cannot be found
    makes the module invisible for a reason nothing reports."""
    declared = MANIFEST.get("requires_libraries", [])
    missing = [l for l in declared if importlib.util.find_spec(l) is None]
    if missing:
        # A partial install cannot tell a WRONG name from an ABSENT
        # one, and guessing would make this either a false alarm in
        # every dev venv or a rubber stamp in CI. So it reports and
        # steps aside; the gate bites in a full install, which is where
        # the availability probe it mirrors actually runs.
        pytest.skip(f"not installed here, cannot verify: {missing}")
    # An EMPTY list is legitimate — a stdlib-only module (imessage
    # drives AppleScript and imports nothing third-party) declares none.

def test_a_driver_declares_whether_its_device_is_reachable() -> None:
    """`kind: driver` must override `Node.link_ok()`.

    The failure it prevents produces no symptom: a driver whose link
    dies keeps ticking and reports RUNNING forever, because the tick
    loop is fine. Nothing else in the system can tell that the device
    is gone.

    Only drivers are held to this — a processing or engine module owns
    no device, and the default `link_ok() -> None` is correct for them.
    """
    if MANIFEST.get("kind") != "driver":
        pytest.skip("not a driver-kind module")

    import importlib

    from jaeger_os.nodes.base import Node

    dotted, _, attr = MANIFEST["factory"].partition(":")
    factory = getattr(importlib.import_module(dotted), attr)
    node_cls = getattr(factory, "__node_class__", None)
    if node_cls is None:
        pytest.skip("factory does not advertise its node class "
                    "(set factory.__node_class__ to enable this gate)")
    assert node_cls.link_ok is not Node.link_ok, (
        f"{node_cls.__name__} is kind: driver and does not override "
        f"link_ok() — a dead device link would report healthy forever")
