"""WebUI unified-UI endpoints: studio assets/board, documents, model-name validation, providers."""
from __future__ import annotations

import base64
import json
import importlib.util
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[5] / "jaeger_ai/features/webui/api/unified_api.py"
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=")


@pytest.fixture()
def api(tmp_path, monkeypatch):
    monkeypatch.setenv("JAEGER_STATE_HOME", str(tmp_path))
    spec = importlib.util.spec_from_file_location("_unified_api", ROOT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_asset_lifecycle(api, tmp_path):
    a = api.add_asset(PNG, "image/png", "dot", "imported", tags=[" x ", "x", "y"])
    assert a["tags"] == ["x", "y"] and (tmp_path / "studio/assets" / a["file"]).read_bytes() == PNG
    assert api.update_asset(a["id"], {"tags": ["z"], "name": "renamed"})["name"] == "renamed"
    api.write_board({"items": [{"id": "b1", "kind": "asset", "asset_id": a["id"], "x": 1, "y": 2, "w": 100, "h": 80}, {"id": "n1", "kind": "note", "text": "hi", "x": 0, "y": 0, "w": 10, "h": 10}]})
    api.delete_asset(a["id"])
    assert api.list_assets() == [] and [i["id"] for i in api.read_board()["items"]] == ["n1"]


def test_rejects_bad_assets(api):
    with pytest.raises(api.ApiError):
        api.add_asset(b"x", "text/html", "evil", "imported")
    with pytest.raises(api.ApiError):
        api.get_asset("../etc")


def test_documents_with_conflict_check(api):
    d = api.save_doc(None, {"title": "Plan", "body": "# Hi"})
    assert api.get_doc(d["id"])["body"] == "# Hi"
    saved = api.save_doc(d["id"], {"title": "Plan", "body": "# Hi 2", "expected_updated_at": d["updated_at"]})
    with pytest.raises(api.ApiError) as e:
        api.save_doc(d["id"], {"title": "Plan", "body": "stale", "expected_updated_at": d["updated_at"]})
    assert e.value.status == 409
    assert api.list_docs()[0]["chars"] == len(saved["body"])
    api.delete_doc(d["id"])
    assert api.list_docs() == []


def test_model_names_are_validated(api):
    for bad in ["", "a b", "x;rm -rf", "../../x"]:
        with pytest.raises(api.ApiError):
            api.pull({"name": bad})


def test_generate_refuses_unavailable_provider(api, monkeypatch):
    monkeypatch.setattr(api, "providers", lambda: [{"id": "p", "available": False, "note": "set up"}])
    with pytest.raises(api.ApiError) as e:
        api.generate({"provider": "p", "prompt": "cat"})
    assert e.value.status == 409 and e.value.payload["note"] == "set up"


class _Resp:
    def __init__(self, lines):
        self.lines = [json.dumps(x).encode() + b"\n" for x in lines]

    def __enter__(self):
        return iter(self.lines)

    def __exit__(self, *a):
        return False


def test_compare_stream_emits_deltas_and_real_metrics(api):
    lines = [{"message": {"content": "Hel"}}, {"message": {"content": "lo"}},
             {"done": True, "eval_count": 20, "eval_duration": 2_000_000_000, "prompt_eval_count": 7, "load_duration": 500_000_000}]
    evs = list(api.compare_stream_events({"model": "qwen3:4b", "prompt": "hi"}, opener=lambda req, timeout: _Resp(lines)))
    assert [e["type"] for e in evs] == ["start", "delta", "delta", "done"]
    done = evs[-1]
    assert done["tokens_per_s"] == 10.0 and done["eval_count"] == 20 and done["prompt_eval_count"] == 7 and done["load_s"] == 0.5
    assert done["cost_usd"] == 0.0 and done["ttft_s"] is not None


def test_compare_stream_cloud_cost_unknown_and_errors(api):
    evs = list(api.compare_stream_events({"model": "glm-5.3:cloud", "prompt": "hi"}, opener=lambda req, timeout: _Resp([{"done": True}])))
    assert evs[-1]["cost_usd"] is None and evs[-1]["tokens_per_s"] is None
    evs = list(api.compare_stream_events({"model": "x:1", "prompt": "hi"}, opener=lambda req, timeout: _Resp([{"error": "model not found"}])))
    assert evs[-1]["type"] == "error" and "model not found" in evs[-1]["error"]
    with pytest.raises(api.ApiError):
        next(api.compare_stream_events({"model": "a b", "prompt": "hi"}))


def test_compare_history_and_votes(api, tmp_path):
    run = api.save_run({"prompt": "p", "results": [{"model": "a:1", "response": "x", "elapsed_s": 1, "junk": 1}, {"model": "b:2", "response": "y"}]})
    assert "junk" not in run["results"][0] and api.list_runs()[0]["id"] == run["id"]
    assert api.update_run(run["id"], {"winner": "b:2"})["winner"] == "b:2"
    assert api.update_run(run["id"], {"winner": "tie"})["winner"] == "tie"
    with pytest.raises(api.ApiError):
        api.update_run(run["id"], {"winner": "c:3"})
    with pytest.raises(api.ApiError):
        api.save_run({"prompt": "p", "results": [{"model": "m:1"}] * 5})
    api.delete_run(run["id"])
    assert api.list_runs() == [] and (tmp_path / "compare/history.json").exists()


def test_compare_routes_cli_models_and_history_accepts_them(api, monkeypatch):
    class Fake:
        SPECS = {"codex": {}}

        @staticmethod
        def known(pid):
            return pid in ("codex", "vscode")
        @staticmethod
        def stream(pid, model, prompt):
            yield {"type": "start", "model": f"cli:{pid}:{model}"}
            yield {"type": "done", "model": f"cli:{pid}:{model}"}
    monkeypatch.setattr(api, "_cli", lambda: Fake)
    assert [e["type"] for e in api.compare_stream_events({"model": "cli:codex:gpt-6-luna", "prompt": "hi"})] == ["start", "done"]
    with pytest.raises(api.ApiError):
        list(api.compare_stream_events({"model": "cli:evil:x", "prompt": "hi"}))
    run = api.save_run({"prompt": "p", "results": [{"model": "cli:codex:gpt-6-luna", "response": "a"}, {"model": "qwen3:4b", "response": "b"}]})
    assert api.update_run(run["id"], {"winner": "cli:codex:gpt-6-luna"})["winner"] == "cli:codex:gpt-6-luna"


def test_pipeline_stage_history_attachments(api, tmp_path):
    tid = "task:abc-123"
    assert api.list_pipeline()["stages"] == ["intake", "research", "studio", "production", "review", "done"]
    with pytest.raises(api.ApiError):
        api.set_stage(tid, {"stage": "shipping"})
    rec = api.set_stage(tid, {"stage": "intake"})
    assert rec["revision"] == 1 and rec["history"][0]["to"] == "intake"
    rec = api.set_stage(tid, {"stage": "research", "expected_revision": 1})
    with pytest.raises(api.ApiError) as e:
        api.set_stage(tid, {"stage": "studio", "expected_revision": 1})
    assert e.value.status == 409
    assert api.set_stage(tid, {"stage": "research"})["revision"] == 2  # same stage: no new history
    n = api.add_attachment(tid, {"kind": "note", "text": "check the spec"})
    assert n["stage"] == "research"
    api.add_attachment(tid, {"kind": "source", "ref": "https://example.com/spec", "label": "Spec"})
    with pytest.raises(api.ApiError):
        api.add_attachment(tid, {"kind": "source", "ref": "javascript:alert(1)"})
    with pytest.raises(api.ApiError):
        api.add_attachment(tid, {"kind": "source", "ref": "https://example.com/spec"})
    a = api.add_attachment(tid, {"kind": "asset", "ref": "asset-1", "label": "hero.png"})
    api.remove_attachment(tid, a["id"])
    saved = api.list_pipeline()["items"][tid]
    assert [x["kind"] for x in saved["attachments"]] == ["note", "source"] and saved["stage"] == "research"
    assert (tmp_path / "pipeline/tasks.json").exists()
    with pytest.raises(api.ApiError):
        api.set_stage("../etc", {"stage": "intake"})


def test_attaching_to_a_new_task_starts_it_at_intake(api):
    api.add_attachment("t2", {"kind": "note", "text": "brief"})
    rec = api.list_pipeline()["items"]["t2"]
    assert rec["stage"] == "intake" and rec["history"][0]["to"] == "intake"
