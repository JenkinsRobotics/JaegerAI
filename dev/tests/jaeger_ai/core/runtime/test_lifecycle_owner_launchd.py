import json
import time

from jaeger_ai.core.runtime import lifecycle_lease as ll


def _stale(tmp_path):
    p = tmp_path / "lifecycle-lease.json"
    p.write_text(json.dumps({"owner": "menubar", "beat_at": time.time() - 600}))
    return ll.LifecycleLease(p, grace_seconds=15, suspend_after=5)


def test_stale_client_lease_shuts_down_by_default(tmp_path, monkeypatch):
    monkeypatch.delenv("JAEGER_LIFECYCLE_OWNER", raising=False)
    d = _stale(tmp_path).decide()
    assert d.shutdown and not d.privileged_work_allowed


def test_launchd_owned_process_ignores_vanished_client_lease(tmp_path, monkeypatch):
    monkeypatch.setenv("JAEGER_LIFECYCLE_OWNER", "launchd")
    monkeypatch.setattr(ll.os, "getppid", lambda: 1)
    lease = _stale(tmp_path)
    d = lease.decide()
    assert d.privileged_work_allowed and not d.shutdown
    lease.path.write_text("not json")
    assert not lease.decide().shutdown


def test_inherited_owner_flag_without_launchd_parent_is_not_honored(tmp_path, monkeypatch):
    monkeypatch.setenv("JAEGER_LIFECYCLE_OWNER", "launchd")
    monkeypatch.setattr(ll.os, "getppid", lambda: 4242)
    assert _stale(tmp_path).decide().shutdown
