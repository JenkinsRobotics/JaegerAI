"""OSV malware check for package installs (audit gap #12).

Before pip-installing a package, ``check_pypi_package`` asks the OSV
database whether it carries a MAL-* (known-malware) advisory. The
network calls here are mocked — the tests lock in the parsing, the
malware verdict, and the fail-open behaviour.
"""

from __future__ import annotations

import json

import jaeger_os.core.safety.osv_check as osv
from jaeger_os.core.safety.osv_check import check_pypi_package, pypi_base_name


# ── name parsing ─────────────────────────────────────────────────────


def test_pypi_base_name_strips_version_and_extras() -> None:
    assert pypi_base_name("requests") == "requests"
    assert pypi_base_name("httpx>=0.27") == "httpx"
    assert pypi_base_name("Django==4.2") == "django"
    assert pypi_base_name("uvicorn[standard]") == "uvicorn"
    assert pypi_base_name("  Flask ; python_version>'3'  ") == "flask"


# ── malware verdict (mocked OSV) ─────────────────────────────────────


class _FakeResp:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def __enter__(self) -> "_FakeResp":
        return self

    def __exit__(self, *a: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")


def _mock_osv(monkeypatch, payload: dict) -> None:
    monkeypatch.setattr(
        osv.urllib.request, "urlopen",
        lambda *a, **k: _FakeResp(payload))


def test_flags_a_known_malware_package(monkeypatch) -> None:
    _mock_osv(monkeypatch, {"vulns": [{"id": "MAL-2024-9999"}]})
    msg = check_pypi_package("evilpkg")
    assert msg is not None
    assert "MAL-2024-9999" in msg and "evilpkg" in msg


def test_clean_package_returns_none(monkeypatch) -> None:
    _mock_osv(monkeypatch, {"vulns": []})
    assert check_pypi_package("requests") is None


def test_regular_cve_is_not_treated_as_malware(monkeypatch) -> None:
    # A normal CVE (not MAL-*) must not block an install.
    _mock_osv(monkeypatch, {"vulns": [{"id": "GHSA-xxxx-yyyy"}]})
    assert check_pypi_package("somepkg") is None


def test_fails_open_on_network_error(monkeypatch) -> None:
    def _boom(*a: object, **k: object) -> None:
        raise OSError("no network")
    monkeypatch.setattr(osv.urllib.request, "urlopen", _boom)
    # OSV unreachable must never block a legitimate install.
    assert check_pypi_package("requests") is None
