"""Regressions reproduced by the complete tool qualification audit."""
import json
from pathlib import Path
import pytest


def test_mcp_keeps_every_content_block_and_structured_result():
    from mcp.types import CallToolResult, TextContent, EmbeddedResource, TextResourceContents, ImageContent, AudioContent, ResourceLink
    from jaeger_ai.plugins.mcp.client import _result_to_dict
    raw = CallToolResult(content=[
        TextContent(type="text", text="Read file"),
        EmbeddedResource(type="resource", resource=TextResourceContents(uri="file:///README.md", text="Actual README contents", mimeType="text/markdown")),
        ImageContent(type="image", data="aGVsbG8=", mimeType="image/png"),
        AudioContent(type="audio", data="aGVsbG8=", mimeType="audio/wav"),
        ResourceLink(type="resource_link", uri="https://example.com/output", name="output"),
    ], structuredContent={"rows": [1, 2]}, isError=False)
    out = _result_to_dict(raw)
    assert out["content"] == raw.model_dump(mode="json", by_alias=True, exclude_none=True)["content"]
    assert out["structuredContent"] == {"rows": [1, 2]}
    assert out["text"] == "Read file\nActual README contents"
    json.dumps(out)


def test_notebook_insert_replace_delete_are_successful_and_persisted(tmp_path):
    from jaeger_agent import tools
    from jaeger_agent.tools.files import notebook_edit
    from jaeger_agent.core.workspace import project_scope
    from jaeger_ai.core.instance.instance import InstanceLayout
    layout = InstanceLayout(root=tmp_path / "instance")
    layout.ensure_dirs()
    tools.bind(layout)
    with project_scope(None):
        for mode, source, expected in [("insert", "x = 1", ["x = 1\n"]), ("replace", "x = 2", ["x = 2\n"]), ("delete", "", None)]:
            result = notebook_edit("sample.ipynb", source, edit_mode=mode)
            assert result["ok"], result
            cells = json.loads((layout.skills_dir / "sample.ipynb").read_text())["cells"]
            assert len(cells) == (0 if expected is None else 1)
            if expected:
                assert cells[0]["source"] == expected


def test_use_skill_accepts_new_instance_playbook_after_registration(tmp_path):
    from jaeger_agent import tools
    from jaeger_ai.core.instance.instance import InstanceLayout
    from jaeger_tools.tool_registry import get_tools
    layout = InstanceLayout(root=tmp_path / "instance")
    layout.ensure_dirs()
    tools.bind(layout)
    tool = next(t for t in get_tools() if t.name == "use_skill")
    name = "fresh-qualification-recipe"
    before = tool.args_model.model_json_schema()
    assert name not in before["properties"]["name"].get("enum", [])
    folder = layout.skills_dir / name
    folder.mkdir()
    (folder / "SKILL.md").write_text("---\nname: fresh-qualification-recipe\ndescription: Verify a newly installed procedure.\n---\nRead the violet fixture marker.\n")
    assert name in tool.args_model.model_json_schema()["properties"]["name"]["enum"]
    assert "violet fixture marker" in tool.dispatch({"name": name})


def test_bridge_workspace_uses_admitted_project(tmp_path):
    from jaeger_agent.core.workspace import project_scope
    from jaeger_ai.core.runtime.code_bridge_tool import _workspace
    with project_scope(tmp_path):
        assert _workspace() == tmp_path


def test_benchmark_resolves_the_active_gateway_client(monkeypatch):
    from types import SimpleNamespace
    from contextlib import nullcontext
    from jaeger_agent.tools import bench
    from jaeger_ai.core.models.model_resolver import serving_model_scope
    import jaeger_ai.core.bench as runner
    import jaeger_ai.main as main
    active = SimpleNamespace(kind="external", model_name="fixture-cloud")
    monkeypatch.setitem(main._pipeline, "client", None)
    monkeypatch.setattr(bench, "_bench_permission_scope", nullcontext)
    seen = []
    monkeypatch.setattr(runner, "run_bench", lambda client, **kwargs: seen.append(client) or [])
    with serving_model_scope(active, None):
        bench.run_benchmark.__wrapped__(ids="time_now", limit=1, save=False)
    assert seen == [active]


def test_mcp_inventory_reads_gateway_owned_external_catalog():
    from jaeger_ai.interfaces.mcp_server import capability_inventory
    class Gateway:
        def _call(self, method, path):
            assert (method, path) == ("GET", "/v1/runtime/tools")
            return {"mcp_initialized": True, "tools": [
                {"name": "read_file", "source": "gateway"},
                {"name": "mcp__github__get_file_contents", "source": "mcp"},
            ]}
    result = capability_inventory(gateway=Gateway())
    assert result["external_mcp_runtime_initialized"]
    assert result["external_mcp_tools"] == ["mcp__github__get_file_contents"]


@pytest.mark.parametrize("result,expected", [
    ({"isError": True, "content": []}, True),
    ({"isError": False, "content": []}, False),
    ({"ok": False, "error": "failed"}, True),
    ({"written": False, "error": "denied"}, True),
    ({"ok": True, "result": 0}, False),
])
def test_loop_and_bridge_share_result_failure_contract(result, expected):
    from jaeger_tools.tool_schema import tool_result_failed
    assert tool_result_failed(result) is expected


def test_gateway_benchmark_never_restores_live_memory(monkeypatch):
    from types import SimpleNamespace
    from jaeger_agent.tools import bench
    from jaeger_agent import task_port
    from jaeger_ai.core.models.model_resolver import serving_model_scope
    import jaeger_ai.core.bench as runner
    import jaeger_ai.core.bench.isolated as isolated
    monkeypatch.setattr(task_port, "current_task_context", lambda: {"session_id": "fixture"})
    monkeypatch.setattr(runner, "run_bench", lambda *a, **k: pytest.fail("live memory must not be snapshotted"))
    seen = []
    monkeypatch.setattr(isolated, "run_isolated", lambda *a, **k: seen.append(k) or [])
    with serving_model_scope(SimpleNamespace(kind="external"), object()):
        result = bench.run_benchmark.__wrapped__(ids="time_now", limit=1, save=False)
    assert result["isolation"] == "disposable_worker"
    assert seen == [{"tags": None, "ids": ["time_now"], "limit": 1}]


def test_worker_does_not_copy_in_process_models():
    from types import SimpleNamespace
    from jaeger_ai.core.bench.isolated import run_isolated
    with pytest.raises(ValueError, match="HTTP model provider"):
        run_isolated(SimpleNamespace(kind="local"), None, ids=["time_now"])


def test_benchmark_worker_environment_and_grant_are_isolated(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from jaeger_ai.core.bench.isolated import run_isolated
    from jaeger_ai.core.instance.schemas import Config, ExternalModelConfig, ModelConfig
    from jaeger_agent.tool_executor import tool_allowlist
    from jaeger_agent.util import tool_interrupt
    monkeypatch.setenv("JAEGER_STATE_DIR", str(tmp_path / "operator"))
    cfg = Config(instance_name="fixture", model=ModelConfig(model_path="/dev/null"))
    ext = ExternalModelConfig(enabled=True, provider="ollama", model="fixture")
    client = SimpleNamespace(ext=ext, _api_key="fixture-secret")
    seen = []
    def process(cmd, *, env, cwd, timeout):
        root = Path(cwd)
        payload = json.loads((root / "request.json").read_text())
        assert "fixture-secret" not in (root / "request.json").read_text()
        assert env["JAEGER_STATE_DIR"] == str(root / "state")
        assert env["JAEGER_INSTANCE_DIR"].startswith(str(root / "state"))
        assert env["JAEGER_CALLER_TOKEN_DIR"] == str(root / "state/tokens")
        assert env["JAEGER_GATEWAY_URL"] == "http://127.0.0.1:0"
        assert payload["allowed_tools"] == ["get_time"]
        (root / "result.json").write_text('{"rows": []}')
        seen.append(root)
        return SimpleNamespace(returncode=0, stderr="")
    monkeypatch.setattr(tool_interrupt, "run_interruptible", process)
    with tool_allowlist(["get_time"]):
        assert run_isolated(client, cfg, ids=["time_now"], limit=1) == []
    assert seen and not seen[0].exists()
