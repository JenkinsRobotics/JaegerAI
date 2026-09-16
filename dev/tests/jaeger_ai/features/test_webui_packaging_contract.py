from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
FEATURE = ROOT / "jaeger_ai/features/webui"


def test_first_party_webui_source_is_complete() -> None:
    required = (
        "server.py",
        "api/routes.py",
        "api/models.py",
        "api/jaeger_agents.py",
        "api/jaeger_sessions.py",
        "api/jaeger_conversation.py",
        "api/jaeger_ollama.py",
        "static/index.html",
        "static/boot.js",
        "static/messages.js",
        "HERMES_WEBUI_LICENSE",
    )
    missing = [relative for relative in required if not (FEATURE / relative).is_file()]
    assert not missing, f"first-party WebUI source is incomplete: {missing}"


def test_webui_launcher_uses_first_party_feature() -> None:
    launcher = (ROOT / "scripts/run-jaeger-webui.sh").read_text(encoding="utf-8")
    assert 'webui_root="$repo_root/jaeger_ai/features/webui"' in launcher
    assert "vendor/hermes-webui" not in launcher
    assert "git submodule" not in launcher


def test_webui_is_included_in_non_editable_packages() -> None:
    packaging = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert '"features/webui/static/**/*"' in packaging
    assert '"features/webui/HERMES_WEBUI_LICENSE"' in packaging


def test_repository_has_no_webui_submodule_contract() -> None:
    assert not (ROOT / ".gitmodules").exists()
    assert not (ROOT / "vendor/hermes-webui").exists()
