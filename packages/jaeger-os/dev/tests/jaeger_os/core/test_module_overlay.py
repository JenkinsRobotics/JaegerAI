"""Project-local modules shadow installed ones — ROS's workspace overlay.

Installed modules are the default and stay out of sight; the day you
need to change one you copy it into ``<project>/modules/`` and yours
wins. Delete the folder and the installed one is back.

The rule this encodes: nothing you are ACTIVELY WORKING ON should be
hidden. Hundreds of packages in site-packages you never open is fine.
The one you are editing living somewhere you cannot see is not.
"""

from __future__ import annotations

import logging
import pathlib

import pytest

from jaeger_os.core.modules import (
    PROJECT_MODULES_DIRNAME, discover_modules, project_module_root,
)

_MANIFEST = """\
module: {name}
slot: {slot}
version: {version}
kind: engine
consumes: []
produces: []
tools: []
factory: "{name}:make_node"
config: ""
requires_libraries: []
"""


def _module(root: pathlib.Path, name: str, slot: str, version="1.0.0"):
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "module.yaml").write_text(
        _MANIFEST.format(name=name, slot=slot, version=version))
    return d


@pytest.fixture
def project(tmp_path):
    (tmp_path / PROJECT_MODULES_DIRNAME).mkdir()
    return tmp_path


# ── finding the root ─────────────────────────────────────────────

def test_a_project_with_no_modules_dir_has_no_local_root(tmp_path):
    assert project_module_root(tmp_path) is None


def test_the_modules_dir_is_the_local_root(project):
    assert project_module_root(project) == project / "modules"


def test_no_project_dir_means_no_overlay(tmp_path):
    """Discovery outside a project must behave exactly as before."""
    assert project_module_root(None) is None


# ── the overlay ──────────────────────────────────────────────────

def test_a_local_module_shadows_an_installed_one(project, tmp_path, caplog):
    """The whole feature. Same slot, two modules, local wins."""
    installed = tmp_path / "site-packages"
    _module(installed, "vendor_anim", "animation", version="0.2.0")
    _module(project / "modules", "my_anim", "animation", version="9.9.9")

    with caplog.at_level(logging.INFO):
        found = discover_modules(
            roots=(installed, project / "modules"), project_dir=project)

    specs = found["animation"]
    assert len(specs) == 1, "both copies survived — the app cannot choose"
    assert specs[0].module == "my_anim"
    assert specs[0].local is True


def test_shadowing_is_never_silent(project, tmp_path, caplog):
    """An override that takes effect without saying so is exactly the
    hidden behaviour this feature exists to remove."""
    installed = tmp_path / "site-packages"
    _module(installed, "vendor_anim", "animation")
    _module(project / "modules", "my_anim", "animation")

    with caplog.at_level(logging.INFO):
        discover_modules(roots=(installed, project / "modules"),
                         project_dir=project)

    logged = caplog.text
    assert "shadows" in logged
    assert "vendor_anim" in logged, "the log must name what was displaced"
    assert "animation" in logged, "and which slot"


def test_shadowing_is_per_slot_not_per_name(project, tmp_path):
    """The slot is what the app binds, so that is what an override has
    to replace. A local module with a different NAME still takes the
    slot — otherwise you would have to guess the vendor's package name
    to override it."""
    installed = tmp_path / "site-packages"
    _module(installed, "kokoro_tts", "tts")
    _module(project / "modules", "piper_tts", "tts")

    found = discover_modules(roots=(installed, project / "modules"),
                             project_dir=project)
    assert [s.module for s in found["tts"]] == ["piper_tts"]


def test_other_slots_are_untouched(project, tmp_path):
    """Overriding the face must not disturb the voice."""
    installed = tmp_path / "site-packages"
    _module(installed, "vendor_anim", "animation")
    _module(installed, "kokoro_tts", "tts")
    _module(project / "modules", "my_anim", "animation")

    found = discover_modules(roots=(installed, project / "modules"),
                             project_dir=project)
    assert [s.module for s in found["animation"]] == ["my_anim"]
    assert [s.module for s in found["tts"]] == ["kokoro_tts"]


def test_removing_the_local_copy_restores_the_installed_one(project, tmp_path):
    """Delete the folder and you are back to stock — no reinstall, no
    manifest edit. That reversibility is what makes overriding cheap
    enough to actually do."""
    installed = tmp_path / "site-packages"
    _module(installed, "vendor_anim", "animation")
    local = _module(project / "modules", "my_anim", "animation")

    roots = (installed, project / "modules")
    assert discover_modules(roots=roots, project_dir=project)["animation"][0].module \
        == "my_anim"

    import shutil
    shutil.rmtree(local)
    assert discover_modules(roots=roots, project_dir=project)["animation"][0].module \
        == "vendor_anim"


# ── provenance ───────────────────────────────────────────────────

def test_every_module_records_where_it_came_from(project, tmp_path):
    """"Which copy am I actually running?" must be answerable without
    reasoning about sys.path."""
    installed = tmp_path / "site-packages"
    _module(installed, "kokoro_tts", "tts")
    _module(project / "modules", "my_anim", "animation")

    found = discover_modules(roots=(installed, project / "modules"),
                             project_dir=project)
    tts = found["tts"][0]
    anim = found["animation"][0]
    assert tts.source_dir is not None and tts.local is False
    assert anim.source_dir is not None and anim.local is True
    assert anim.source_dir.name == "my_anim"


def test_an_installed_only_project_reports_nothing_local(project, tmp_path):
    installed = tmp_path / "site-packages"
    _module(installed, "kokoro_tts", "tts")
    found = discover_modules(roots=(installed,), project_dir=project)
    assert found["tts"][0].local is False
