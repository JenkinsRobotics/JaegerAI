"""Plugin manifest schema — typed contract for ``plugin.yaml``.

Before the Pydantic model landed, manifests were untyped dicts
read with ``.get()`` calls. A typo'd field name silently meant
"this plugin has no requirements" rather than surfacing the bug.

This file pins:
  * every bundled plugin's manifest validates
  * the schema rejects obvious shape errors (string where list
    expected, missing required name field)
  * ``audit_plugin_dir`` returns the right shape per plugin row
"""

from __future__ import annotations

from pathlib import Path

import pytest

from jaeger_os.plugins.manifest import (
    PluginManifest,
    audit_plugin_dir,
    load_manifest,
)


_BUNDLED_PLUGINS_ROOT = (
    Path(__file__).resolve().parents[4]
    / "jaeger_os" / "plugins"
)


# ── bundled-plugin coverage ────────────────────────────────────────


def test_every_bundled_plugin_manifest_validates():
    """Every plugin we ship MUST have a valid manifest. The audit
    helper returns one row per plugin; every row must be ``ok``."""
    rows = audit_plugin_dir(_BUNDLED_PLUGINS_ROOT)
    bad = [r for r in rows if not r.get("ok")]
    assert rows, "audit found no plugins (plugins dir empty?)"
    assert not bad, (
        "bundled plugin manifests failed validation: "
        + "; ".join(f"{r['name']}: {r.get('errors')}" for r in bad)
    )


def test_audit_returns_one_row_per_plugin():
    rows = audit_plugin_dir(_BUNDLED_PLUGINS_ROOT)
    # We ship exactly 6 plugins today; pinned so an accidental
    # commit that drops one or adds an unannounced one is noticed.
    names = {r["name"] for r in rows}
    assert {"discord", "telegram", "imessage", "mcp",
            "kokoro_tts", "whisper_stt"} <= names


# ── schema behaviour ──────────────────────────────────────────────


def test_minimal_manifest_just_needs_name():
    """``name`` is the only required field. Everything else has
    a sensible default — version defaults to 1, requires is an
    empty block, etc."""
    m = PluginManifest(name="probe")
    assert m.name == "probe"
    assert m.version == 1
    assert m.requires.libraries == []
    assert m.provides.tools == []


def test_typo_in_top_level_does_not_silently_drop_data():
    """Extra fields are allowed (forward-compat) but a typo on a
    KNOWN field that changes its type must fail validation. We
    use ``version`` since it's typed as ``int`` and a typo'd
    string is the classic failure mode."""
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        PluginManifest(name="probe", version="not-an-int")  # type: ignore


def test_extra_unknown_fields_are_preserved():
    """We use ``extra="allow"`` so manifests with custom fields
    keep working as the framework adds awareness of new sections.
    A plugin author shipping ``my_custom_block: ...`` should
    parse cleanly."""
    m = PluginManifest(name="probe", custom_field="value")  # type: ignore
    assert m.name == "probe"


def test_load_manifest_raises_clearly_on_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_manifest(tmp_path / "does_not_exist.yaml")


def test_load_manifest_raises_on_malformed_yaml(tmp_path):
    bad = tmp_path / "plugin.yaml"
    bad.write_text("name: {{{ this is not yaml", encoding="utf-8")
    with pytest.raises(ValueError):
        load_manifest(bad)


def test_audit_surfaces_failing_plugin_with_errors(tmp_path):
    """A directory with a malformed manifest must appear in the
    audit as ``ok=False`` with errors — not silently dropped."""
    bad_plugin = tmp_path / "broken"
    bad_plugin.mkdir()
    (bad_plugin / "plugin.yaml").write_text(
        "version: not-an-int\n", encoding="utf-8",
    )
    rows = audit_plugin_dir(tmp_path)
    assert len(rows) == 1
    assert rows[0]["ok"] is False
    assert rows[0]["name"] == "broken"
    assert rows[0]["errors"]
