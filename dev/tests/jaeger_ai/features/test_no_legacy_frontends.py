"""Retired frontend source and automatic fallback must stay disconnected."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]


def test_old_frontends_are_absent():
    for rel in ('interfaces/swift', 'interfaces/pyside6', 'interfaces/avatar_chat', 'interfaces/avatar_player', 'features/webui/static/index.html'):
        assert not (ROOT / 'jaeger_ai' / rel).exists(), rel


def test_backend_routes_have_no_old_shell_renderer():
    source = (ROOT / 'jaeger_ai/features/webui/api/routes.py').read_text()
    assert '_render_index_shell_base' not in source
    assert 'inject_extension_tags(html)' not in source
