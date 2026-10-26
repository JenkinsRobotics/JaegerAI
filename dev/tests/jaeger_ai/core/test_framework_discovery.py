"""Framework discovery is presence-only; grants are owner-only and audited."""
import json
from pathlib import Path

import pytest

from jaeger_ai.core.frameworks import discovery as d
from jaeger_ai.core.frameworks.grants import FrameworkGrants
from jaeger_ai.core.gateway import caller_auth


def _home(tmp_path):
    h = tmp_path / "home"
    (h / ".claude/projects/p1").mkdir(parents=True)
    (h / ".claude/projects/p1/s1.jsonl").write_text("{}")
    (h / ".claude/projects/p1/s2.jsonl").write_text("{}")
    (h / ".claude/CLAUDE.md").write_text("x")
    (h / ".codex/sessions/2026/10").mkdir(parents=True)
    (h / ".codex/sessions/2026/10/r.jsonl").write_text("{}")
    (h / ".codex/auth.json").write_text("SECRET")
    return h


def test_detect_reports_presence_and_counts_without_reading(tmp_path, monkeypatch):
    home = _home(tmp_path)
    opened = []
    real_open = Path.open
    monkeypatch.setattr(Path, "open", lambda self, *a, **k: opened.append(self) or real_open(self, *a, **k))
    monkeypatch.setattr(Path, "read_text", lambda self, *a, **k: opened.append(self) or "")
    rows = {r["id"]: r for r in d.detect(home, apps_dir=tmp_path / "Apps")}
    assert rows["claude-code"]["installed"] and rows["claude-code"]["counts"] == {"sessions": 2, "memory": 1}
    assert rows["codex"]["counts"]["sessions"] == 1
    assert not rows["lmstudio"]["installed"]
    assert opened == []
    assert "SECRET" not in json.dumps(rows)


@pytest.mark.parametrize("name", ["auth.json", "oauth_creds.json", "jetski-standalone-oauth-token",
                                  "google_accounts.json", "settings.local.json", "config.toml",
                                  "state_5.sqlite", ".env", "Cookies"])
def test_deny_list(name):
    assert d.is_denied(Path(name))


def test_deny_list_allows_history_files():
    assert not d.is_denied(Path("projects/p1/s1.jsonl"))
    assert d.is_denied(Path("credentials/x.md"))


def test_grants_are_per_framework_capability_and_audited(tmp_path):
    g = FrameworkGrants(tmp_path / "framework_grants.json")
    assert not g.is_granted("codex", "read_sessions")
    g.set("codex", "read_sessions", True, by="owner:webui")
    assert g.is_granted("codex", "read_sessions") and not g.is_granted("codex", "read_memory")
    assert not g.is_granted("claude-code", "read_sessions")
    g.set("codex", "read_sessions", False, by="owner:webui")
    assert not g.is_granted("codex", "read_sessions")
    events = [json.loads(x)["event"] for x in g.audit_path.read_text().splitlines()]
    assert events == ["grant", "revoke"]
    with pytest.raises(ValueError):
        g.set("codex", "write", True, by="x")


def test_only_owner_callers_can_change_grants():
    scope = caller_auth.required_scope("POST", "/v1/frameworks/{id}/grants")
    assert scope == "admin"
    assert "admin" not in caller_auth.CALLERS["jaegerd"].scopes  # the agent cannot grant itself
    assert "admin" not in caller_auth.CALLERS["mcp"].scopes
    assert not caller_auth.prefixed_route_allowed("GET", "/v1/frameworks")
