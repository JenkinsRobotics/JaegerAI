"""GET /v1/machine/logs (whitelisted, redacted, read-only) and the /v1/usage alias."""
from __future__ import annotations

import importlib.util
import pathlib
from types import SimpleNamespace

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[5] / "jaeger_ai/features/webui/api/machine_api.py"


def _load():
    spec = importlib.util.spec_from_file_location("_machine_api_t", ROOT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def m(tmp_path, monkeypatch):
    monkeypatch.setenv("JAEGER_STATE_DIR", str(tmp_path))
    (tmp_path / "logs").mkdir()
    (tmp_path / "logs" / "gateway.log").write_text(
        "2026 INFO started\n2026 ERROR boom api_key=sk-abcdefghijklmnop1234\nAuthorization: Bearer abc.def.ghi\n2026 WARNING slow\n")
    (tmp_path / "secret.txt").write_text("nope")
    return _load()


def test_tail_redacts_and_filters(m):
    t = m.tail("gateway", lines=10)
    text = "\n".join(x["text"] for x in t["lines"])
    assert "sk-abcdefghijklmnop1234" not in text and "abc.def.ghi" not in text and "[redacted]" in text
    assert [x["level"] for x in m.tail("gateway", level="error")["lines"]] == ["error"]
    assert len(m.tail("gateway", q="slow")["lines"]) == 1
    assert len(m.tail("gateway", lines=1)["lines"]) == 1


def test_only_whitelisted_sources(m):
    with pytest.raises(KeyError):
        m.tail("../secret.txt")
    assert {s["id"] for s in m.sources()} >= {"gateway", "jobs", "webui"}
    assert m.tail("jobs")["exists"] is False


def test_route_is_get_only_and_404s_unknown_source(m):
    out = {}
    def j(_h, body, status=200):
        out["status"], out["body"] = status, body
    parsed = lambda path, q="": SimpleNamespace(path=path, query=q)
    assert m.handles("/v1/machine/logs") and m.handles("/v1/usage") and not m.handles("/v1/machine")
    m.route(None, parsed("/v1/machine/logs", "source=nope"), "GET", None, j); assert out["status"] == 404
    m.route(None, parsed("/v1/machine/logs", "source=gateway&lines=2"), "GET", None, j); assert out["status"] == 200 and len(out["body"]["lines"]) == 2
    m.route(None, parsed("/v1/machine/logs"), "POST", None, j); assert out["status"] == 405


def test_provider_error_url_credentials_are_not_visible_in_logs(m, tmp_path):
    (tmp_path / "logs" / "gateway.log").write_text(
        "ERROR provider unavailable https://dummy-user:dummy-password@provider.invalid/v1\n")
    text = m.tail("gateway")["lines"][0]["text"]
    assert "dummy-password" not in text
    assert "provider unavailable" in text and "provider.invalid" in text
