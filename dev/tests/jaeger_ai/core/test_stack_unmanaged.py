"""Services that are up but not owned by launchd must not read as Stopped.

The menu bar renders ``jaeger stack status --json``; with the gateway started
by hand it reported every live service as Stopped and flagged the stack."""

from __future__ import annotations

import subprocess

from jaeger_ai.core.runtime import stack


def _not_loaded(args):
    return subprocess.CompletedProcess(args, 113, stdout="", stderr="not found")


def _gateway():
    return stack.SERVICE_BY_ID["gateway"]


def test_live_unmanaged_service_reports_ready(monkeypatch):
    monkeypatch.setattr(stack, "_launchctl", _not_loaded)
    monkeypatch.setattr(stack, "probe_service_health", lambda s: True)
    st = stack.inspect_service(_gateway(), head_commit="abc")
    assert st["ready"] is True
    assert st["managed"] is False
    assert st["state"] == "Ready (unmanaged)"
    assert st["raw_state"] == "unmanaged"
    assert st["stale"] is False


def test_dead_unmanaged_service_still_stopped(monkeypatch):
    monkeypatch.setattr(stack, "_launchctl", _not_loaded)
    monkeypatch.setattr(stack, "probe_service_health", lambda s: False)
    st = stack.inspect_service(_gateway(), head_commit="abc")
    assert st["ready"] is False
    assert st["state"] == "Stopped"


def test_launchd_running_service_is_managed(monkeypatch):
    out = "state = running\n\tpid = 4242\n\tJAEGER_GIT_COMMIT => abc\n"
    monkeypatch.setattr(stack, "_launchctl",
                        lambda a: subprocess.CompletedProcess(a, 0, stdout=out, stderr=""))
    monkeypatch.setattr(stack, "probe_service_health", lambda s: True)
    st = stack.inspect_service(_gateway(), head_commit="abc")
    assert st["managed"] is True and st["state"] == "Ready" and st["pid"] == 4242


def test_stack_up_skips_service_already_serving_outside_launchd(monkeypatch):
    calls: list[list[str]] = []

    def fake_launchctl(args):
        calls.append(args)
        return _not_loaded(args)

    monkeypatch.setattr(stack, "_launchctl", fake_launchctl)
    monkeypatch.setattr(stack, "probe_service_health", lambda s: True)
    monkeypatch.setattr(stack, "migrate_legacy_launchagents", lambda: [])
    monkeypatch.setattr(stack, "sync_plists", lambda *a, **k: [])
    monkeypatch.setattr(stack, "_current_git_commit", lambda: "abc")
    res = stack.stack_up([_gateway()], wait_timeout=0.1)
    assert res["skipped_unmanaged"] == ["gateway"]
    assert not any(a and a[0] in ("bootstrap", "kickstart", "bootout") for a in calls)
    assert res["ok"] is True
