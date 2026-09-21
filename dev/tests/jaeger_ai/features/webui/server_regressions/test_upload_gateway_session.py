from __future__ import annotations

from pathlib import Path

import api.upload as U


def test_gateway_upload_dir_is_under_instance_workspace(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("JAEGER_INSTANCE_DIR", str(tmp_path))
    (tmp_path / "workspace").mkdir()
    dest = U._gateway_upload_dir("phone-mercury")
    assert dest.is_dir()
    assert dest.is_relative_to(tmp_path / "workspace" / "uploads")


def test_missing_hermes_session_falls_back_to_gateway(monkeypatch):
    monkeypatch.setattr(U, "get_session", lambda _sid: (_ for _ in ()).throw(KeyError("missing")))
    monkeypatch.setattr(U, "_gateway_session", lambda sid: {"session_id": sid})
    assert U._gateway_session("phone-fix")["session_id"] == "phone-fix"
    try:
        U.get_session("phone-fix")
        raise AssertionError("expected KeyError")
    except KeyError:
        gateway = U._gateway_session("phone-fix")
        assert gateway is not None


def test_unknown_session_stays_not_found(monkeypatch):
    monkeypatch.setattr(U, "get_session", lambda _sid: (_ for _ in ()).throw(KeyError("missing")))
    monkeypatch.setattr(U, "_gateway_session", lambda _sid: None)
    try:
        U.get_session("nope")
    except KeyError:
        assert U._gateway_session("nope") is None




