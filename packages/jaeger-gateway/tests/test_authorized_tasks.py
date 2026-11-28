"""Acceptance tests for Gateway-owned Authorized Task Handling.

Verifies all 5 acceptance criteria plus defensive credential auditing and independent
Direct Chat / Owner Autonomy settings:
  1. Find `credentials-backup.txt` in a granted folder without opening it or calling a cloud model.
  2. Connect to a PC via saved `~/.ssh/config` while `remote_hosts.json` is empty; confirm hostname.
  3. Provide official recovery paths with explicit `preserves_data` and exact prerequisites when locked out.
  4. Simulate a cloud model refusal on filename lookup -> Gateway built-in search still succeeds in chat.
  5. Denied grant, unknown host key, and document/webpage-embedded instructions cannot widen access.
"""

from __future__ import annotations

import builtins
from pathlib import Path
import subprocess

import pytest

from jaeger_gateway import (
    AuthorizedGrantStore,
    AuthorizedTaskEngine,
    ModularGatewayRuntime,
)
from jaeger_models import ReplayModel
from jaeger_tools import RemoteHostRegistry


def test_acceptance_1_find_credentials_backup_without_opening_or_cloud_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    docs = tmp_path / "Documents"
    docs.mkdir()
    secret_file = docs / "credentials-backup.txt"
    secret_file.write_text("TOP_SECRET_VALUE_MUST_NEVER_BE_READ=12345\n", encoding="utf-8")

    grants = AuthorizedGrantStore(tmp_path / "state", default_workspace=tmp_path / "ws")
    grants.grant_folder(docs, operations=("find_metadata",), origin="owner")
    engine = AuthorizedTaskEngine(
        grants=grants,
        remote_hosts=RemoteHostRegistry(tmp_path / "state" / "remote_hosts.json"),
        workspace=tmp_path / "ws",
    )

    # Hard proof: fail the test if anything tries to open() credentials-backup.txt!
    real_open = builtins.open

    def guarded_open(file, *args, **kwargs):
        if "credentials-backup.txt" in str(file):
            raise AssertionError("find_file MUST NOT open or read file contents!")
        return real_open(file, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", guarded_open)

    rec = engine.find_file("credentials-backup.txt", origin="owner")
    assert rec.status == "verified_success"
    assert rec.layer == "gateway"
    assert rec.used_cloud_model is False
    assert rec.verified_result["content_opened"] is False
    assert rec.verified_result["sent_to_cloud"] is False
    assert rec.verified_result["count"] == 1
    assert rec.verified_result["matches"][0]["path"] == str(secret_file)


def test_acceptance_2_connect_device_reuses_ssh_profile_from_empty_list_and_flags_ambiguity(
    tmp_path: Path,
) -> None:
    ssh_cfg = tmp_path / "ssh_config"
    ssh_cfg.write_text(
        "\n".join([
            "Host rack-pc-lan",
            "  HostName 192.0.2.19",
            "  User demo-owner",
            "  IdentityFile ~/.ssh/id_ed25519",
            "",
            "Host macbook-pro",
            "  HostName 192.0.2.21",
            "  User demo-owner",
            "",
            "Host mac-studio",
            "  HostName 100.64.0.20",
            "  User demo-owner",
        ]),
        encoding="utf-8",
    )
    reg = RemoteHostRegistry(tmp_path / "state" / "remote_hosts.json")
    assert reg.list_public() == []

    engine = AuthorizedTaskEngine(
        grants=AuthorizedGrantStore(tmp_path / "state", default_workspace=tmp_path),
        remote_hosts=reg,
        workspace=tmp_path,
        ssh_config_path=ssh_cfg,
        tailscale_bin="/nonexistent/tailscale",
    )

    def ok_ssh_runner(argv, **kwargs):
        if "rack-pc-lan" in argv:
            return subprocess.CompletedProcess(argv, 0, stdout="RackPCExample\n", stderr="")
        return subprocess.CompletedProcess(argv, 255, stdout="", stderr="Connection refused")

    rec = engine.connect_device("my rack pc", runner=ok_ssh_runner)
    assert rec.status == "verified_success"
    assert rec.layer == "gateway"
    assert rec.used_cloud_model is False
    assert rec.verified_result["remote_hostname"] == "RackPCExample"
    assert rec.verified_result["via"] == "ssh_config:rack-pc-lan"
    assert len(reg.list_public()) == 1

    # Multiple distinct devices matching "mac" -> asks owner which one!
    amb = engine.connect_device("mac", runner=ok_ssh_runner)
    assert amb.status == "ambiguous_selection"
    aliases = [c["alias"] for c in amb.verified_result["candidates"]]
    assert set(aliases) == {"macbook-pro", "mac-studio"}


def test_acceptance_3_recover_access_distinguishes_data_preserving_vs_erasing_and_prerequisites(
    tmp_path: Path,
) -> None:
    engine = AuthorizedTaskEngine(
        grants=AuthorizedGrantStore(tmp_path / "state", default_workspace=tmp_path),
        remote_hosts=RemoteHostRegistry(tmp_path / "state" / "remote_hosts.json"),
        workspace=tmp_path,
        ssh_config_path=tmp_path / "missing_ssh_config",
        tailscale_bin="/nonexistent/tailscale",
    )

    rec = engine.recover_access("my MacBook Pro", scenario="forgot_passcode", os_hint="macos")
    assert rec.status == "blocked_prerequisite"
    assert rec.layer == "device_lock"
    assert rec.used_cloud_model is False
    options = rec.verified_result["recovery_options"]
    assert any(o["preserves_data"] is True and "FileVault" in o["method"] for o in options)
    assert any(o["preserves_data"] is False and "Erase Mac" in o["method"] for o in options)
    assert all(bool(o["prerequisite"]) for o in options)
    assert "Recovery Key" in rec.unblock_step or "Apple Account" in rec.unblock_step


def test_acceptance_4_simulated_cloud_refusal_falls_back_to_local_builtin_search_in_chat(
    tmp_path: Path,
) -> None:
    ws = tmp_path / "repo"
    ws.mkdir()
    docs = tmp_path / "Documents"
    docs.mkdir()
    target_file = docs / "credentials-backup.txt"
    target_file.write_text("SECRET_SHOULD_NOT_BE_SENT_TO_CLOUD=999\n", encoding="utf-8")

    # Simulate a cloud model that falsely declines a filename lookup as credential harvesting!
    refusing_cloud_model = ReplayModel(
        [
            {
                "content": (
                    "I cannot assist with searching for credentials-backup.txt because locating credential "
                    "files resembles credential harvesting and is against my safety guidelines."
                )
            }
        ],
        model_id="cloud/refusal-sim",
    )
    rt = ModularGatewayRuntime(
        state_dir=tmp_path / "state",
        workspace=ws,
    )
    rt.model = refusing_cloud_model
    rt.authorized_grants.grant_folder(docs, operations=("find_metadata",), origin="owner")
    sess = rt.store.create_session(title="Authorized Chat Test", workspace=str(ws))

    # Run a full Gateway chat turn!
    gen1 = rt.hub.open_generation(sess["session_id"])
    turn = rt._execute_turn(sess["session_id"], "Find credentials-backup.txt", gen1, rt.hub)
    assert turn["verdict"] == "complete"
    assert turn["authorized_task"]["status"] == "verified_success"
    assert turn["authorized_task"]["provider_decision"] == "declined"
    assert turn["authorized_task"]["verified_result"]["content_opened"] is False
    assert turn["authorized_task"]["verified_result"]["sent_to_cloud"] is False
    assert str(target_file) in turn["content"]
    assert "Provider decision" in turn["content"]
    assert "SECRET_SHOULD_NOT_BE_SENT_TO_CLOUD" not in turn["content"]

    # Direct model-free slash command in chat also works without touching any model!
    gen2 = rt.hub.open_generation(sess["session_id"])
    direct_turn = rt._execute_turn(sess["session_id"], "/find credentials-backup.txt", gen2, rt.hub)
    assert direct_turn["verdict"] == "complete"
    assert direct_turn["authorized_task"]["provider_decision"] == "not_called"
    assert direct_turn["authorized_task"]["used_cloud_model"] is False
    assert str(target_file) in direct_turn["content"]


def test_acceptance_5_denied_grant_unknown_host_key_and_untrusted_document_origin_fail_closed(
    tmp_path: Path,
) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    ungranted = tmp_path / "PrivateVault"
    ungranted.mkdir()
    (ungranted / "credentials-backup.txt").write_text("do not read\n", encoding="utf-8")

    grants = AuthorizedGrantStore(tmp_path / "state", default_workspace=ws)
    reg = RemoteHostRegistry(tmp_path / "state" / "remote_hosts.json")
    ssh_cfg = tmp_path / "ssh_config"
    ssh_cfg.write_text("Host lab-box\n  HostName 10.0.0.55\n  User admin\n", encoding="utf-8")

    engine = AuthorizedTaskEngine(
        grants=grants,
        remote_hosts=reg,
        workspace=ws,
        ssh_config_path=ssh_cfg,
        tailscale_bin="/nonexistent/tailscale",
    )

    # 1. Ungranted folder -> denied_grant at jaeger_policy layer
    denied = engine.find_file("credentials-backup.txt", root=ungranted, origin="owner")
    assert denied.status == "denied_grant"
    assert denied.layer == "jaeger_policy"

    # 2. Unknown/changed SSH host key -> blocked_prerequisite at os_permission layer (NEVER false success!)
    def bad_host_key_runner(argv, **kwargs):
        return subprocess.CompletedProcess(
            argv,
            255,
            stdout="",
            stderr="Host key verification failed.\r\n",
        )

    bad_key = engine.connect_device("lab-box", runner=bad_host_key_runner)
    assert bad_key.status == "blocked_prerequisite"
    assert bad_key.layer == "os_permission"
    assert bad_key.blocker == "unknown_or_changed_host_key"
    assert reg.list_public() == []

    # 3. Document/webpage/tool_output origin CANNOT grant folders, toggle settings, or run workflows!
    for bad_origin in ("document", "webpage", "tool_output"):
        with pytest.raises(PermissionError):
            grants.grant_folder(ungranted, operations=("find_metadata",), origin=bad_origin)
        with pytest.raises(PermissionError):
            grants.update_settings(owner_autonomy=True, origin=bad_origin)
        blocked_wf = engine.find_file("credentials-backup.txt", origin=bad_origin)
        assert blocked_wf.status == "denied_grant"
        assert blocked_wf.layer == "jaeger_policy"

    # 4. Secret directories (~/.ssh) cannot be granted even by owner
    with pytest.raises(PermissionError):
        grants.grant_folder(Path.home() / ".ssh", operations=("find_metadata",), origin="owner")


def test_defensive_credential_audit_masks_secrets_and_separate_settings_persist(tmp_path: Path) -> None:
    ws = tmp_path / "project"
    ws.mkdir()
    raw_token = "sk-proj-abc1234567890XYZ987654321"
    (ws / "leaked.py").write_text(f'API_KEY = "{raw_token}"\n', encoding="utf-8")

    grants = AuthorizedGrantStore(tmp_path / "state", default_workspace=ws)
    engine = AuthorizedTaskEngine(
        grants=grants,
        remote_hosts=RemoteHostRegistry(tmp_path / "state" / "remote_hosts.json"),
        workspace=ws,
    )

    rec = engine.credential_audit(root=ws, origin="owner")
    assert rec.status == "verified_success"
    assert rec.verified_result["finding_count"] == 1
    assert rec.verified_result["raw_secrets_exported"] is False
    masked = rec.verified_result["findings"][0]["masked_value"]
    assert raw_token not in masked and "****" in masked
    assert len(rec.verified_result["remediation_steps"]) >= 2

    # Direct Chat and Owner Autonomy are stored and toggled independently
    s1 = grants.update_settings(direct_chat=True, owner_autonomy=False, origin="owner")
    assert s1.direct_chat is True and s1.owner_autonomy is False
    s2 = grants.update_settings(direct_chat=False, origin="owner")
    assert s2.direct_chat is False and s2.owner_autonomy is False
