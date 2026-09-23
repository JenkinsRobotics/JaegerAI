"""Acceptance collection must reject unsafe targets before contacting services."""

import runpy
import urllib.request
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[4]
SUITE = REPO / "dev/tests/acceptance/test_webui_runtime_truth.py"


@pytest.fixture
def isolated_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("JAEGER_ACCEPTANCE", "1")
    monkeypatch.setenv("JAEGER_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("JAEGER_WEBUI_URL", "http://127.0.0.1:18790")
    monkeypatch.setenv("JAEGER_GATEWAY_URL", "http://127.0.0.1:18810")

    def no_network(*args, **kwargs):
        pytest.fail("acceptance preflight must not contact a service")

    monkeypatch.setattr(urllib.request, "urlopen", no_network)


@pytest.mark.parametrize("key", ["JAEGER_WEBUI_URL", "JAEGER_GATEWAY_URL"])
@pytest.mark.parametrize("url", [
    "", "http://127.0.0.1:8810", "http://localhost:8790",
    "https://127.0.0.1:18810", "http://example.com:18810",
    "http://localhost", "http://user:password@localhost:18810",
    "http://localhost:18810/api", "http://localhost:18810?target=live",
    "http://localhost:18810#live",
])
def test_acceptance_rejects_unsafe_endpoints(isolated_environment, monkeypatch, key, url):
    monkeypatch.setenv(key, url)
    with pytest.raises(RuntimeError, match=f"{key} must specify an isolated"):
        runpy.run_path(str(SUITE))


@pytest.mark.parametrize("root", [REPO, REPO / "scratch", Path.home() / ".jaeger"])
def test_acceptance_rejects_protected_state(isolated_environment, monkeypatch, root):
    monkeypatch.setenv("JAEGER_STATE_DIR", str(root))
    with pytest.raises(RuntimeError, match="outside the repository and operator state"):
        runpy.run_path(str(SUITE))


def test_acceptance_resolves_state_symlinks(isolated_environment, monkeypatch, tmp_path):
    alias = tmp_path / "checkout-alias"
    alias.symlink_to(REPO, target_is_directory=True)
    monkeypatch.setenv("JAEGER_STATE_DIR", str(alias / "scratch"))
    with pytest.raises(RuntimeError, match="outside the repository and operator state"):
        runpy.run_path(str(SUITE))


def test_acceptance_has_no_operator_service_restart():
    assert "launchctl" not in SUITE.read_text(encoding="utf-8")
