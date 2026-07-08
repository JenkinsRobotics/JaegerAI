"""module.yaml loader + discovery (0.8 M1 Task 2 — the module seam).

Mirrors ``dev/tests/jaeger_os/hardware/test_framework.py``'s package-
loader coverage: happy path against the REAL kokoro_tts module.yaml,
then one refusal per validation rule (unknown key, empty slot,
missing factory, malformed factory string) — each naming the
offending file, never silently degrading.
"""

from __future__ import annotations

import pathlib

import pytest

from jaeger_os.core.modules import ModuleSpec, discover_modules, load_module


_REPO_ROOT = pathlib.Path(__file__).resolve().parents[4]
_KOKORO_DIR = _REPO_ROOT / "jaeger_os" / "nodes" / "kokoro_tts"
_NODES_ROOT = _REPO_ROOT / "jaeger_os" / "nodes"


_GOOD_YAML = """
module: widget
slot: widgets
version: 2.0.0
consumes: [/act/widget]
produces: [/sense/widget]
tools: [use_widget]
factory: pkg.mod:make_widget
config: widget
"""


def _write_module(tmp_path, name="widget", text=_GOOD_YAML):
    d = tmp_path / name
    d.mkdir(exist_ok=True)
    (d / "module.yaml").write_text(text, encoding="utf-8")
    return d


# ── load_module against the REAL kokoro_tts module.yaml ────────────


def test_load_module_real_kokoro_tts():
    spec = load_module(_KOKORO_DIR)
    assert spec.module == "kokoro_tts"
    assert spec.slot == "tts"
    assert spec.version == "1.0.0"
    assert spec.consumes == ["/act/speech", "/act/speech_stop"]
    assert spec.produces == ["/sense/spoken", "/sense/tts_chunk"]
    assert spec.tools == ["text_to_speech"]
    assert spec.factory == "jaeger_os.nodes.kokoro_tts:make_tts_node"
    assert spec.config == "kokoro_tts"
    assert spec.requires_libraries == ["kokoro", "sounddevice", "numpy"]


def test_load_module_happy_path(tmp_path):
    spec = load_module(_write_module(tmp_path))
    assert isinstance(spec, ModuleSpec)
    assert spec.module == "widget"
    assert spec.slot == "widgets"
    assert spec.tools == ["use_widget"]
    assert spec.requires_libraries == []


def test_load_module_parses_requires_libraries(tmp_path):
    text = _GOOD_YAML + "requires_libraries: [foo, bar]\n"
    spec = load_module(_write_module(tmp_path, text=text))
    assert spec.requires_libraries == ["foo", "bar"]


def test_load_module_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_module(tmp_path / "nope")


def test_load_module_refuses_unknown_field(tmp_path):
    bad = _GOOD_YAML.replace("version:", "vershun:")
    with pytest.raises(ValueError, match="module.yaml"):
        load_module(_write_module(tmp_path, text=bad))


def test_load_module_refuses_empty_slot(tmp_path):
    bad = _GOOD_YAML.replace("slot: widgets", "slot: ''")
    with pytest.raises(ValueError, match="slot"):
        load_module(_write_module(tmp_path, text=bad))


def test_load_module_refuses_missing_factory(tmp_path):
    bad = _GOOD_YAML.replace("factory: pkg.mod:make_widget", "")
    with pytest.raises(ValueError):
        load_module(_write_module(tmp_path, text=bad))


def test_load_module_refuses_malformed_factory(tmp_path):
    bad = _GOOD_YAML.replace(
        "factory: pkg.mod:make_widget", "factory: pkg.mod.make_widget",
    )
    with pytest.raises(ValueError, match="pkg.mod:attr"):
        load_module(_write_module(tmp_path, text=bad))


# ── discover_modules ────────────────────────────────────────────────


def test_discover_modules_default_root_finds_kokoro_tts():
    found = discover_modules()
    assert "tts" in found
    names = {spec.module for spec in found["tts"]}
    assert "kokoro_tts" in names


def test_discover_modules_keys_by_slot(tmp_path):
    _write_module(tmp_path, "widget_a", _GOOD_YAML)
    other = _GOOD_YAML.replace("module: widget", "module: widget2").replace(
        "slot: widgets", "slot: other_slot",
    )
    _write_module(tmp_path, "widget_b", other)
    found = discover_modules(tmp_path)
    assert set(found) == {"widgets", "other_slot"}
    assert [spec.module for spec in found["widgets"]] == ["widget"]
    assert [spec.module for spec in found["other_slot"]] == ["widget2"]


def test_discover_modules_skips_dirs_without_module_yaml(tmp_path):
    (tmp_path / "not_a_module").mkdir()
    (tmp_path / "not_a_module" / "readme.txt").write_text("hi")
    _write_module(tmp_path, "widget_a", _GOOD_YAML)
    found = discover_modules(tmp_path)
    assert set(found) == {"widgets"}


def test_discover_modules_raises_loudly_on_broken_module(tmp_path):
    _write_module(tmp_path, "good", _GOOD_YAML)
    bad = _GOOD_YAML.replace("version:", "vershun:")
    broken_dir = _write_module(tmp_path, "broken", bad)
    with pytest.raises(ValueError, match=str(broken_dir / "module.yaml")):
        discover_modules(tmp_path)


def test_discover_modules_missing_root_returns_empty(tmp_path):
    assert discover_modules(tmp_path / "does_not_exist") == {}


def test_discover_modules_uses_real_nodes_dir_by_default_arg():
    """Sanity check the computed default matches the repo layout."""
    assert discover_modules(_NODES_ROOT) == discover_modules()
