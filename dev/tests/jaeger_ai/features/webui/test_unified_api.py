"""WebUI unified-UI endpoints: studio assets/board, documents, model-name validation, providers."""
from __future__ import annotations

import base64
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
