"""Standalone extension documents must not inject their globals into chat."""

import json
from pathlib import Path

import pytest


@pytest.mark.parametrize("extension", ["ares-finance", "ares-creator", "ares-minecraft", "ares-worldview"])
def test_dashboard_assets_belong_to_their_own_document(extension):
    root = Path(__file__).resolve().parents[6] / "extensions" / extension
    manifest = json.loads((root / "manifest.json").read_text())
    # These keys explicitly mean scripts/styles injected into the HOST page.
    assert manifest.get("scripts", []) == []
    assert manifest.get("stylesheets", []) == []
    assert "dashboard_tab" in manifest["capabilities"]
    entry = root / manifest["tab"]["entry"]
    html = entry.read_text()
    assert 'src="app.js"' in html
    assert 'href="style.css"' in html
    assert (entry.parent / "app.js").is_file()
    assert (entry.parent / "style.css").is_file()
