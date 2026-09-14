"""A capability that may legitimately be absent.

Fail-closed is the right default: a typo'd slot name must be a boot
error, not a node that quietly never runs. But some capabilities are
genuinely optional — Mochi without its animation module has nothing to
show and should refuse to start, while Mochi without a voice is just a
character that does not speak. That is v5.0, and it shipped.
"""

from __future__ import annotations

import pytest

from jaeger_os.app import JaegerApp, load_manifest

_MANIFEST = '''
[app]
name = "opt-test"
requires_framework = ">=0.1"
mode = "fused"
event_loop = "none"
config = ""
control = false

[bus]
backend = "inproc"

[[node]]
id = "voice"
slot = "test_missing_tts"
{optional}
'''


def _write(tmp_path, optional: bool):
    (tmp_path / "jaeger.toml").write_text(
        _MANIFEST.format(optional="optional = true" if optional else ""))
    return tmp_path


def test_a_missing_required_slot_still_refuses_to_boot(tmp_path):
    """The default. A slot nothing fills is usually a typo, and a typo
    that produces a silently absent node is far worse than a crash."""
    app = JaegerApp(_write(tmp_path, optional=False) / "jaeger.toml")
    with pytest.raises(ValueError, match="slot 'test_missing_tts'"):
        app.boot()
    app.shutdown()


def test_a_missing_optional_slot_boots_without_it(tmp_path):
    app = JaegerApp(_write(tmp_path, optional=True) / "jaeger.toml")
    try:
        app.boot()
        assert "voice" not in (app.supervisor._handles or {})
    finally:
        app.shutdown()


def test_skipping_is_logged_not_silent(tmp_path, capfd):
    """An operator who installed a voice and does not hear one needs to
    know the app looked and found nothing."""
    app = JaegerApp(_write(tmp_path, optional=True) / "jaeger.toml")
    try:
        app.boot()
        out = capfd.readouterr()
        combined = out.out + out.err
        assert "test_missing_tts" in combined and "optional" in combined
    finally:
        app.shutdown()


def test_optional_is_off_by_default(tmp_path):
    (tmp_path / "jaeger.toml").write_text(_MANIFEST.format(optional=""))
    spec = load_manifest(tmp_path)
    assert spec.nodes[0].optional is False


def test_optional_is_a_known_key(tmp_path):
    (tmp_path / "jaeger.toml").write_text(
        _MANIFEST.format(optional="optional = true"))
    assert load_manifest(tmp_path).nodes[0].optional is True


# ── the install hint ─────────────────────────────────────────────

_HINTED = _MANIFEST.replace(
    "{optional}", 'optional = true\npackage = "jaeger-kokoro-tts"')


def test_package_is_a_hint_not_a_binding(tmp_path):
    """Naming a package must not privilege it.

    The slot still takes whichever installed module claims it. If this
    ever became a binding it would quietly turn a documentation field
    into dependency resolution, and two apps naming different packages
    for one slot would disagree about what 'tts' means.
    """
    (tmp_path / "jaeger.toml").write_text(_HINTED)
    spec = load_manifest(tmp_path)
    assert spec.nodes[0].package == "jaeger-kokoro-tts"
    assert spec.nodes[0].factory == ""      # binding unchanged
    assert spec.nodes[0].module == ""


def test_the_hint_reaches_the_operator(tmp_path, capfd):
    """An empty slot with no hint is a dead end — the whole point."""
    (tmp_path / "jaeger.toml").write_text(_HINTED)
    app = JaegerApp(tmp_path / "jaeger.toml")
    try:
        app.boot()
        combined = "".join(capfd.readouterr())
        assert "pip install jaeger-kokoro-tts" in combined
    finally:
        app.shutdown()


def test_package_is_empty_by_default(tmp_path):
    (tmp_path / "jaeger.toml").write_text(_MANIFEST.format(optional=""))
    assert load_manifest(tmp_path).nodes[0].package == ""
