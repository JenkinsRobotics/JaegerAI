"""The WebUI serves only the /api routes something still calls."""
import importlib.util
from pathlib import Path

_PATH = Path(__file__).resolve().parents[5] / "jaeger_ai/features/webui/api/kept_routes.py"
spec = importlib.util.spec_from_file_location("_kept_routes", _PATH)
kept = importlib.util.module_from_spec(spec)
spec.loader.exec_module(kept)


def test_ui_routes_are_kept():
    for path in ("/api/models", "/api/terminal/start", "/api/git/status", "/api/handoffs/abc/messages",
                 "/api/connect-apps/vscode/state", "/api/jaeger/sessions/x/turns", "/api/auth/status",
                 "/api/file/raw", "/api/remote/connection-info", "/api/settings"):
        assert kept.is_kept(path), path


def test_hermes_routes_are_retired():
    for path in ("/api/sessions", "/api/chat/start", "/api/profiles", "/api/kanban/board",
                 "/api/updates/check", "/api/crons", "/api/onboarding/status"):
        assert not kept.is_kept(path), path


def test_non_api_paths_are_untouched():
    for path in ("/", "/v1/sessions", "/login", "/session/static/x.js", "/manifest.json"):
        assert kept.is_kept(path)
