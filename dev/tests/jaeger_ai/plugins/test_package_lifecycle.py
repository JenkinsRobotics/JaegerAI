"""Actual offline pip effects in an owned disposable environment; no plugin import."""

from pathlib import Path
import base64
import hashlib
import zipfile
import venv
import pytest
from jaeger_ai.plugins.packages import PackageOwner, wheel_info
from jaeger_ai.plugins import startup
from jaeger_ai.core.gateway.session_store import GatewaySessionStore


def wheel(root, version, *, unsafe=None):
    name = f"owned_plugin-{version}-py3-none-any.whl"
    path = root / name
    metadata = f"owned_plugin-{version}.dist-info"
    content = {
        "owned_plugin.py": f"VERSION={version!r}\nfrom pathlib import Path\nPath({str(root / 'ACTIVATED')!r}).write_text('forbidden activation')\ndef register(ctx): pass\n",
        metadata
        + "/METADATA": f"Metadata-Version: 2.1\nName: owned-plugin\nVersion: {version}\n",
        metadata
        + "/WHEEL": "Wheel-Version: 1.0\nGenerator: owned fixture\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
        metadata
        + "/entry_points.txt": "[jaeger_ai.plugins]\nowned = owned_plugin:register\n",
    }
    if unsafe:
        content[unsafe] = "unsafe fixture data"
    content[metadata + "/RECORD"] = (
        "".join(
            f"{p},sha256={base64.urlsafe_b64encode(hashlib.sha256(v.encode()).digest()).decode().rstrip('=')},{len(v.encode())}\n"
            for p, v in content.items()
        )
        + metadata
        + "/RECORD,,\n"
    )
    with zipfile.ZipFile(path, "w") as archive:
        for p, value in content.items():
            archive.writestr(p, value)
    return path


def reserve(owner, oid):
    assert owner.store.reserve_scoped_control_operation(
        oid, {"owned_fixture": oid}, "plugin-packages:" + owner.environment
    )


def test_actual_offline_install_update_restore_remove_and_retained_receipts(
    tmp_path, monkeypatch
):
    prefix = tmp_path / "environment"
    venv.EnvBuilder(with_pip=True, symlinks=True).create(prefix)
    owner = PackageOwner(
        GatewaySessionStore(tmp_path / "gateway.sqlite3"), prefix=prefix
    )
    first = wheel(tmp_path, "1.0")
    second = wheel(tmp_path, "2.0")
    before = owner.preview(first)
    assert before["expected_fingerprint"] == "absent"
    reserve(owner, "owned-install")
    installed = owner.change(
        "owned-install",
        action="install",
        path=first,
        expected_fingerprint=before["expected_fingerprint"],
        expected_policy_revision=before["policy_revision"],
        expected_sha=before["sha256"],
    )
    assert installed["ok"] and installed["result"]["state"] == "installed_disabled"
    assert owner.progress("owned-install")["source"] == "selected/" + first.name
    assert (owner.directory("owned-install") / "selected" / first.name).is_file()
    snapshot = owner.probe()
    v1 = owner.current(snapshot, "owned-plugin")
    (Path(snapshot["purelib"]) / "owned_plugin.py").chmod(0o600)
    original = owner.files(snapshot, v1)
    assert v1["version"] == "1.0" and not (tmp_path / "ACTIVATED").exists()
    policy = startup.read(owner.store, environment=owner.environment)
    assert policy["entries"][before["entries"][0]["slot_id"]] == "disabled"
    plan = owner.preview(second)
    reserve(owner, "owned-update")
    updated = owner.change(
        "owned-update",
        action="install",
        path=second,
        expected_fingerprint=plan["expected_fingerprint"],
        expected_policy_revision=plan["policy_revision"],
        expected_sha=plan["sha256"],
    )
    assert (
        updated["ok"]
        and owner.current(owner.probe(), "owned-plugin")["version"] == "2.0"
    )
    assert (
        owner.progress("owned-update")["backup"]
        and not (tmp_path / "ACTIVATED").exists()
    )
    path, _, plan = owner.restore_preview("owned-update")
    assert path.name == first.name
    reserve(owner, "owned-restore")
    restored = owner.restore(
        "owned-restore",
        "owned-update",
        expected_fingerprint=plan["expected_fingerprint"],
        expected_policy_revision=plan["policy_revision"],
    )
    assert restored["ok"] and restored["result"]["restored_from"] == "owned-update"
    snapshot = owner.probe()
    assert owner.files(snapshot, owner.current(snapshot, "owned-plugin")) == original
    reserve(owner, "owned-remove")
    removed = owner.change(
        "owned-remove",
        action="remove",
        package="owned-plugin",
        expected_fingerprint=owner.fingerprint(
            snapshot, owner.current(snapshot, "owned-plugin")
        ),
        expected_policy_revision=startup.read(
            owner.store, environment=owner.environment
        )["revision"],
    )
    assert removed["ok"] and owner.current(owner.probe(), "owned-plugin") is None
    _, _, plan = owner.restore_preview("owned-remove")
    reserve(owner, "owned-undo-remove")
    assert owner.restore(
        "owned-undo-remove",
        "owned-remove",
        expected_fingerprint=plan["expected_fingerprint"],
        expected_policy_revision=plan["policy_revision"],
    )["ok"]
    assert owner.current(owner.probe(), "owned-plugin")["version"] == "1.0"
    assert (
        owner.inspect("owned-update") == updated
        and not (tmp_path / "ACTIVATED").exists()
    )
    assert len(owner.history()["operations"]) == 5 and owner.store.list_requests() == []
    # Actual installer completes, then a local fixture simulates partial/corrupt
    # output plus lost acknowledgment. Do not replay the admitted installer.
    plan = owner.preview(second)
    reserve(owner, "owned-unknown-update")
    actual = owner._pip
    calls = []

    def interrupted(args, on_started):
        calls.append(args)
        actual(args, on_started)
        base = Path(owner.probe()["purelib"])
        (base / "owned_plugin.py").write_text("PARTIAL_OWNED_FIXTURE = True")
        raise RuntimeError("owned fixture interrupted before receipt")

    monkeypatch.setattr(owner, "_pip", interrupted)
    with pytest.raises(RuntimeError, match="owned fixture interrupted"):
        owner.change(
            "owned-unknown-update",
            action="install",
            path=second,
            expected_sha=plan["sha256"],
            expected_fingerprint=plan["expected_fingerprint"],
            expected_policy_revision=plan["policy_revision"],
        )
    assert (
        owner.inspect("owned-unknown-update")["execution_unknown"] and len(calls) == 1
    )
    with pytest.raises(ValueError, match="unresolved"):
        reserve(owner, "owned-forbidden-retry")
    _, _, recovery = owner.restore_preview("owned-unknown-update")
    assert owner.reserve_restore(
        "owned-compensating-restore",
        {"owned_fixture": "explicit compensation"},
        "owned-unknown-update",
    )
    monkeypatch.setattr(owner, "_pip", actual)
    restored = owner.restore(
        "owned-compensating-restore",
        "owned-unknown-update",
        expected_fingerprint=recovery["expected_fingerprint"],
        expected_policy_revision=recovery["policy_revision"],
    )
    assert (
        restored["ok"]
        and owner.files(owner.probe(), owner.current(owner.probe(), "owned-plugin"))
        == original
    )
    assert owner.store.control_operation("owned-unknown-update")["receipt"] is None
    assert (
        owner.inspect("owned-unknown-update")["execution_unknown"] and len(calls) == 1
    )
    assert not (tmp_path / "ACTIVATED").exists()


def test_wheel_validation_blocks_startup_hooks_and_host_namespace(tmp_path):
    for unsafe in (
        "evil.pth",
        "sitecustomize.py",
        "../escaped.py",
        "jaeger_ai/evil.py",
    ):
        with pytest.raises(ValueError, match="Unsupported or unsafe"):
            wheel_info(wheel(tmp_path, "1.0", unsafe=unsafe))


@pytest.mark.asyncio
async def test_authenticated_http_staging_review_actual_pip_and_no_replay(
    tmp_path, monkeypatch
):
    import base64
    from aiohttp.test_utils import TestClient, TestServer
    from jaeger_ai.core.gateway.server import JaegerGatewayApp
    from jaeger_ai.core.gateway.caller_auth import client_headers
    from jaeger_ai.plugins import package_routes

    prefix = tmp_path / "http-environment"
    venv.EnvBuilder(with_pip=True, symlinks=True).create(prefix)
    store = GatewaySessionStore(tmp_path / "gateway.sqlite3")
    store.ensure_session("owned-package-home")
    gateway = JaegerGatewayApp(store=store)
    manager = PackageOwner(store, prefix=prefix)
    monkeypatch.setattr(package_routes, "owner", lambda g: manager)
    artifact = wheel(tmp_path, "1.0")
    calls = []
    pip = manager._pip

    def counted(args, on_started):
        assert all(
            value == "disabled"
            for value in startup.read(store, environment=manager.environment)[
                "entries"
            ].values()
        )
        calls.append(args)
        return pip(args, on_started)

    monkeypatch.setattr(manager, "_pip", counted)
    async with TestClient(
        TestServer(gateway.app), headers=client_headers("webui")
    ) as http:
        uploaded = await http.post(
            "/v1/sessions/owned-package-home/attachments/upload",
            json={
                "name": artifact.name,
                "mime": "application/octet-stream",
                "data_base64": base64.b64encode(artifact.read_bytes()).decode(),
            },
            headers={"Idempotency-Key": "owned-wheel-upload"},
        )
        assert uploaded.status == 201
        attachment = await uploaded.json()
        response = await http.post(
            "/v1/runtime/plugins/packages/preview",
            json={
                "action": "install",
                "session_id": "owned-package-home",
                "upload_key": "owned-wheel-upload",
            },
        )
        assert response.status == 200
        plan = await response.json()
        assert plan["attachment_id"] == attachment["attachment_id"] and calls == []
        body = {
            "operation_id": "owned-http-install",
            "action": "install",
            "session_id": "owned-package-home",
            "attachment_id": attachment["attachment_id"],
            "sha256": plan["sha256"],
            "expected_fingerprint": plan["expected_fingerprint"],
            "expected_policy_revision": plan["policy_revision"],
        }
        rejected = await http.post(
            "/v1/runtime/plugins/packages/change",
            json={**body, "operation_id": "owned-wrong-digest", "sha256": "0" * 64},
        )
        assert (
            rejected.status == 409 and not (await rejected.json())["ok"] and calls == []
        )
        response = await http.post("/v1/runtime/plugins/packages/change", json=body)
        assert response.status == 200
        receipt = await response.json()
        assert receipt["ok"] and receipt["result"]["activation_performed"] is False
        assert (
            len(calls) == 1
            and "--no-index" in calls[0]
            and "--no-deps" in calls[0]
            and Path(calls[0][-1]).name == artifact.name
        )
        assert (
            await (
                await http.post("/v1/runtime/plugins/packages/change", json=body)
            ).json()
            == receipt
            and len(calls) == 1
        )
        assert (
            await http.post(
                "/v1/runtime/plugins/packages/change", json={**body, "sha256": "1" * 64}
            )
        ).status == 400
        saved = await (
            await http.get(
                "/v1/runtime/plugins/package-operations/" + body["operation_id"]
            )
        ).json()
        assert saved["receipt"] == receipt
        assert (
            manager.current(manager.probe(), "owned-plugin")["version"] == "1.0"
            and not (tmp_path / "ACTIVATED").exists()
        )
        manager.guard = lambda: "stopped"
        response = await http.post(
            "/v1/runtime/plugins/packages/change",
            json={**body, "operation_id": "owned-stopped"},
        )
        assert response.status == 409 and len(calls) == 1
        assert (
            store.list_requests() == []
            and store.list_messages("owned-package-home")["messages"] == []
        )
    async with TestClient(
        TestServer(gateway.app), headers=client_headers("jaegerd")
    ) as http:
        assert (
            await http.post("/v1/runtime/plugins/packages/change", json=body)
        ).status == 403
    async with TestClient(
        TestServer(gateway.app), headers=client_headers("a2a")
    ) as http:
        assert (await http.get("/v1/runtime/plugins/packages")).status == 403


def test_current_process_loaded_plugin_cannot_be_hot_replaced(tmp_path, monkeypatch):
    import sys
    from jaeger_ai.plugins import registry

    store = GatewaySessionStore(tmp_path / "gateway.sqlite3")
    owner = PackageOwner(store, prefix=sys.prefix)
    row = {
        "name": "owned-plugin",
        "version": "1.0",
        "files": [],
        "requires": [],
        "entries": [{"group": "jaeger_ai.plugins"}],
    }
    monkeypatch.setattr(registry, "_LOADED", {"owned": {"package": "owned-plugin"}})
    with pytest.raises(ValueError, match="Loaded plugin code is retained"):
        owner.admissible({"distributions": [row]}, "owned-plugin")
    assert store.list_requests() == []


def test_package_history_pages_without_losing_retained_backups(tmp_path):
    store = GatewaySessionStore(tmp_path / "gateway.sqlite3")
    owner = PackageOwner(store, prefix=tmp_path / "unused-environment")
    for index in range(34):
        oid = "owned-history-" + str(index)
        store.reserve_control_operation(oid, {"fixture": oid})
        owner.checkpoint(
            oid,
            {
                "operation_id": oid,
                "created_at": 100.0,
                "action": "update",
                "package": "owned-plugin",
                "version": str(index),
                "phase": "installer_exited",
                "backup": "owned.whl",
            },
        )
    first = owner.history()
    second = owner.history(first["next_before"])
    assert len(first["operations"]) == 30 and len(second["operations"]) == 4
    assert {row["operation_id"] for row in first["operations"]}.isdisjoint(
        {row["operation_id"] for row in second["operations"]}
    )
    assert all(
        row["backup_available"] for row in first["operations"] + second["operations"]
    )
    with pytest.raises(ValueError, match="cursor"):
        owner.history("invalid cursor")
    assert (
        not owner.artifacts.exists()
    )  # Listing does not start/initialize an environment.


def test_owned_installer_is_terminated_on_stop_and_launch_record_failure(tmp_path):
    import os
    import shlex

    store = GatewaySessionStore(tmp_path / "gateway.sqlite3")
    ready = tmp_path / "owned-ready"
    helper = tmp_path / "owned-installer"
    helper.write_text(
        "#!/bin/sh\nprintf ready > "
        + shlex.quote(str(ready))
        + "\nexec /bin/sleep 30\n"
    )
    helper.chmod(0o700)
    manager = PackageOwner(
        store,
        prefix=tmp_path / "unused-environment",
        guard=lambda: "stopped" if ready.exists() else None,
    )
    manager.python = helper
    pids = []
    with pytest.raises(RuntimeError, match="Owned installer stopped"):
        manager._pip([], pids.append)
    with pytest.raises(ProcessLookupError):
        os.kill(pids[-1], 0)
    manager.guard = lambda: None

    def failed(pid):
        pids.append(pid)
        raise RuntimeError("owned receipt fixture unavailable")

    with pytest.raises(RuntimeError, match="launch record failed"):
        manager._pip([], failed)
    with pytest.raises(ProcessLookupError):
        os.kill(pids[-1], 0)
    assert store.list_requests() == []


def test_installed_version_cannot_escape_recovery_artifact_directory(tmp_path):
    store = GatewaySessionStore(tmp_path / "gateway.sqlite3")
    manager = PackageOwner(store, prefix=tmp_path / "unused-environment")
    base = tmp_path / "site"
    base.mkdir()
    source = base / "owned.py"
    source.write_text("owned fixture")
    snapshot = {"purelib": str(base)}
    row = {
        "name": "owned-plugin",
        "version": "../../unrelated",
        "files": [{"path": str(source), "relative": "owned.py"}],
    }
    folder = tmp_path / "recovery"
    folder.mkdir()
    with pytest.raises(ValueError, match="Invalid installed package version"):
        manager.backup(snapshot, row, folder)
    assert list(folder.iterdir()) == [] and not (tmp_path / "unrelated").exists()
