"""CLI backend discovery — PATH probe with a fake ``which``."""

from __future__ import annotations

from jaeger_ai.core.models.model_resolver import list_registered_models
from jaeger_ai.features.cli_backends.discovery import (
    KNOWN_BACKENDS,
    probe_backend,
    resolve_backend,
    which_cli,
)
from jaeger_ai.features.cli_backends.service import (
    list_all,
    list_installed,
    to_model_rows,
)


def _fake_which(installed: dict[str, str]):
    def which(name: str, path: str | None = None) -> str | None:
        del path
        return installed.get(name)
    return which


def test_known_catalog_covers_the_five_brains_and_ollama():
    ids = {spec.id for spec in KNOWN_BACKENDS}
    assert ids == {"claude", "codex", "grok", "gemini", "hermes", "ollama"}
    catalogued = {spec.id for spec in KNOWN_BACKENDS if spec.catalog}
    assert catalogued == {"claude", "codex", "grok", "gemini", "hermes"}
    assert resolve_backend("cli:claude").id == "claude"
    assert resolve_backend("codex-cli").id == "codex"


def test_list_installed_uses_which_and_extra_dirs(monkeypatch):
    monkeypatch.setattr(
        "jaeger_ai.features.cli_backends.discovery.shutil.which",
        _fake_which({
            "claude": "/opt/homebrew/bin/claude",
            "codex": "/opt/homebrew/bin/codex",
            "grok": "/Users/matthewjenkins/.grok/bin/grok",
            "gemini": "/opt/homebrew/bin/gemini",
            "hermes": "/Users/matthewjenkins/bin/hermes",
            "ollama": "/usr/local/bin/ollama",
        }),
    )
    installed = {row.id: row for row in list_installed()}
    assert set(installed) == {"claude", "codex", "grok", "gemini", "hermes", "ollama"}
    assert installed["claude"].executable == "/opt/homebrew/bin/claude"
    assert installed["grok"].executable.endswith("/grok")
    rows = to_model_rows()
    names = [r["name"] for r in rows]
    assert names == [
        "cli:claude", "cli:codex", "cli:grok", "cli:gemini", "cli:hermes",
    ]
    claude = rows[0]
    assert claude["provider"] == "claude-cli"
    assert claude["status"] == "installed on PATH"
    assert claude["kind"] == "external"
    assert claude["location"] == "local-cli"
    assert claude["route_provider"] == "cli"
    # ollama is installed but not a competing brain row
    assert all(r["name"] != "cli:ollama" for r in rows)


def test_missing_binary_is_not_catalogued(monkeypatch):
    monkeypatch.setattr(
        "jaeger_ai.features.cli_backends.discovery.shutil.which",
        _fake_which({"claude": "/opt/homebrew/bin/claude"}),
    )
    assert [r.id for r in list_installed()] == ["claude"]
    assert [r["name"] for r in to_model_rows()] == ["cli:claude"]
    missing = [r for r in list_all() if not r.installed]
    assert {r.id for r in missing} == {"codex", "grok", "gemini", "hermes", "ollama"}


def test_list_registered_models_includes_a_fake_installed_cli(monkeypatch):
    monkeypatch.setattr(
        "jaeger_ai.features.cli_backends.discovery.shutil.which",
        _fake_which({"claude": "/tmp/fake-claude"}),
    )
    # Avoid live Ollama / xAI probes from the rest of the catalog.
    monkeypatch.setattr(
        "jaeger_ai.core.models.model_discovery.discover_ollama",
        lambda: {"online": False, "models": []},
    )
    monkeypatch.setattr(
        "jaeger_ai.core.models.model_resolver._resolve_provider_key",
        lambda _provider: "",
    )
    rows = list_registered_models(include_serving=False)
    claude = next(r for r in rows if r.get("name") == "cli:claude")
    assert claude["provider"] == "claude-cli"
    assert claude["status"] == "installed on PATH"
    assert claude["kind"] == "external"
    assert claude["location"] == "local-cli"
    assert claude["executable"] == "/tmp/fake-claude"


def test_which_cli_forwards_path_to_shutil(monkeypatch, tmp_path):
    seen: list[str | None] = []

    def fake_which(name: str, path: str | None = None) -> str | None:
        seen.append(path)
        if name == "grok" and path and str(tmp_path) in path:
            return str(tmp_path / "grok")
        return None

    monkeypatch.setattr(
        "jaeger_ai.features.cli_backends.discovery.shutil.which",
        fake_which,
    )
    monkeypatch.setattr(
        "jaeger_ai.features.cli_backends.discovery.extra_path_dirs",
        lambda: [tmp_path],
    )
    found = which_cli("grok")
    assert found == str(tmp_path / "grok")
    assert seen[0] is None  # PATH first
    assert any(s and str(tmp_path) in s for s in seen)


def test_probe_backend_tries_executable_aliases(monkeypatch):
    monkeypatch.setattr(
        "jaeger_ai.features.cli_backends.discovery.shutil.which",
        _fake_which({"hermes-agent": "/usr/bin/hermes-agent"}),
    )
    spec = resolve_backend("hermes")
    assert probe_backend(spec) == "/usr/bin/hermes-agent"
