"""Durable startup and exact-content approval; only owned callbacks run."""

from types import SimpleNamespace
import importlib.metadata as metadata
import zipfile
import pytest
from jaeger_ai.plugins import registry, startup
from jaeger_ai.core.gateway.session_store import GatewaySessionStore
from dev.tests.jaeger_ai.plugins.test_package_lifecycle import wheel


def owned_entry(tmp_path):
    artifact = wheel(tmp_path, "1.0")
    root = tmp_path / "owned-site"
    root.mkdir()
    with zipfile.ZipFile(artifact) as archive:
        archive.extractall(root)
    dist = metadata.PathDistribution(root / "owned_plugin-1.0.dist-info")
    loads = []

    def register(ctx):
        ctx.register_hook("turn_end", lambda **kw: None)

    return (
        SimpleNamespace(
            name="owned",
            value="owned_plugin:register",
            dist=dist,
            load=lambda: loads.append("owned callback") or register,
        ),
        loads,
        root,
    )


@pytest.mark.asyncio
async def test_startup_policy_atomic_receipt_reload_content_change_and_caller_scope(
    tmp_path, monkeypatch
):
    from aiohttp.test_utils import TestClient, TestServer
    from jaeger_ai.core.gateway.server import JaegerGatewayApp
    from jaeger_ai.core.gateway.caller_auth import client_headers
    import jaeger_ai.core.gateway.session_store as session_store

    registry.reset_for_tests()
    ep, loads, root = owned_entry(tmp_path)
    monkeypatch.setattr(registry, "_entries", lambda group: [ep])
    store = GatewaySessionStore(tmp_path / "gateway.sqlite3")
    monkeypatch.setattr(
        session_store, "default_store_path", lambda **kwargs: store.path
    )
    gateway = JaegerGatewayApp(store=store)
    try:
        assert registry.discover_plugins() == ["owned"]
        row = registry.catalog()["plugins"][0]
        assert row["startup_approvable"] and row["startup_policy"] == "legacy"
        async with TestClient(
            TestServer(gateway.app), headers=client_headers("webui")
        ) as http:
            path = "/v1/runtime/plugins/" + row["id"] + "/startup"
            body = {
                "operation_id": "owned-startup-disable",
                "expected_revision": 0,
                "enabled": False,
            }
            response = await http.post(path, json=body)
            assert response.status == 200
            receipt = await response.json()
            assert receipt["ok"] and receipt["result"]["activation_performed"] is False
            assert store.control_operation(body["operation_id"])["receipt"] == receipt
            assert (await (await http.post(path, json=body)).json()) == receipt
            assert (
                registry.catalog()["plugins"][0]["restart_required"] and len(loads) == 1
            )
            registry.reset_for_tests()
            assert registry.discover_plugins() == [] and len(loads) == 1
            response = await http.post(
                path,
                json={
                    "operation_id": "owned-startup-enable",
                    "expected_revision": 1,
                    "enabled": True,
                },
            )
            assert response.status == 200 and (await response.json())["ok"]
            registry.reset_for_tests()
            assert registry.discover_plugins() == ["owned"] and len(loads) == 2
            # Same package/version and metadata, different actual bytes: approval must not transfer.
            (root / "owned_plugin.py").write_text("changed without updating RECORD")
            changed = registry.catalog()["plugins"][0]
            assert (
                changed["id"] == row["id"]
                and changed["startup_policy"] == "revision_unapproved"
            )
            assert (
                changed["distribution_state"] == "replaced"
                and not changed["startup_approvable"]
            )
            registry.reset_for_tests()
            assert registry.discover_plugins() == [] and len(loads) == 2
            assert not (tmp_path / "ACTIVATED").exists() and store.list_requests() == []
        async with TestClient(
            TestServer(gateway.app), headers=client_headers("jaegerd")
        ) as http:
            assert (await http.post(path, json=body)).status == 403
        async with TestClient(
            TestServer(gateway.app), headers=client_headers("a2a")
        ) as http:
            assert (await http.get("/v1/runtime/plugins")).status == 403
    finally:
        registry.reset_for_tests()


def test_discovery_does_not_initialize_database_and_corrupt_policy_fails_closed(
    tmp_path, monkeypatch
):
    import jaeger_ai.core.gateway.session_store as session_store

    absent = tmp_path / "absent" / "gateway.sqlite3"
    monkeypatch.setattr(session_store, "default_store_path", lambda **kwargs: absent)
    assert (
        startup.read() == {"revision": 0, "entries": {}} and not absent.parent.exists()
    )
    store = GatewaySessionStore(tmp_path / "gateway.sqlite3")
    with store._immediate() as conn:
        conn.execute(
            "INSERT INTO schema_meta(key,value) VALUES(?,?)",
            ("plugin_startup:" + startup.environment_id(), "not JSON"),
        )
    monkeypatch.setattr(
        session_store, "default_store_path", lambda **kwargs: store.path
    )
    ep, loads, _ = owned_entry(tmp_path)
    monkeypatch.setattr(registry, "_entries", lambda group: [ep])
    registry.reset_for_tests()
    try:
        assert (
            registry.discover_plugins() == []
            and loads == []
            and not registry.catalog()["plugins"][0]["startup_known"]
        )
    finally:
        registry.reset_for_tests()
