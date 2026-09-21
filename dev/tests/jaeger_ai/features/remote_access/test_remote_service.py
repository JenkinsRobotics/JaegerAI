from __future__ import annotations

import json
from pathlib import Path

from jaeger_ai.features.remote_access import store
from jaeger_ai.features.remote_access.policy import RemoteAccessPolicy
from jaeger_ai.features.remote_access.service import (
    consume_pairing_token,
    disable,
    enable,
    issue_pairing_token,
    policy_from_store,
)


def test_enable_persists_fail_closed_policy(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("JAEGER_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("JAEGER_INSTANCE_DIR", str(tmp_path / "inst"))
    (tmp_path / "inst" / "run").mkdir(parents=True)
    monkeypatch.setattr(
        "jaeger_ai.features.remote_access.service.tailscale_status",
        lambda: {
            "ok": True, "installed": True, "logged_in": True,
            "dns_name": "host.tailnet.ts.net", "ipv4": "100.64.1.2",
        },
    )
    res = enable(start_webui=False, serve=False)
    assert res["ok"]
    assert res["origin"].startswith("https://")
    assert "pair" in res["pair_url"]
    state = store.load()
    assert state["enabled"] is True
    assert state["token"]
    policy = policy_from_store()
    assert policy.remote_enabled
    assert policy.authorize("192.168.1.9", {"Authorization": f"Bearer {state['token']}"}).status == 403
    assert policy.authorize("100.64.1.2", {"Authorization": f"Bearer {state['token']}"}).allowed
    assert policy.authorize("100.64.1.2", {}).status == 401
    disable(stop_serve=False)
    assert store.load()["enabled"] is False


def test_pairing_token_is_single_use(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("JAEGER_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("JAEGER_INSTANCE_DIR", str(tmp_path / "inst"))
    (tmp_path / "inst" / "run").mkdir(parents=True)
    store.save({"enabled": True, "token": "secret", "dns_name": "x.ts.net", "https_port": 8443})
    pair = issue_pairing_token()
    assert consume_pairing_token(pair["token"])
    assert not consume_pairing_token(pair["token"])
    assert not consume_pairing_token("nope")


def test_loopback_peer_is_documented_serve_topology() -> None:
    policy = RemoteAccessPolicy(token="secret", remote_enabled=True)
    loop = policy.authorize("127.0.0.1", {})
    assert loop.allowed
    assert loop.reason == "loopback"


def test_remote_verb_help() -> None:
    from jaeger_ai.cli.verbs.remote_verb import _cmd_remote_argv
    assert _cmd_remote_argv(["--help"]) == 0
    from jaeger_ai.cli.verbs.dispatch import SUBCOMMANDS
    assert "remote" in SUBCOMMANDS
