import pytest
from jaeger_ai.features.webui.api import ollama_cloud as cloud


@pytest.fixture(autouse=True)
def clean_cache(monkeypatch):
    monkeypatch.setattr(cloud, "_cache", None)
    monkeypatch.setattr(cloud, "_expires", 0)


def test_discovery_keeps_all_models_and_reads_architecture_limit(monkeypatch):
    def request(path, body=None):
        if path == "tags":
            return {"models": [{"name": "new-model"}, {"name": "tagged:123"}, {"name": "new-model"}]}
        if body["model"] == "tagged:123":
            raise OSError("metadata temporarily unavailable")
        return {"capabilities": ["completion", "vision"], "model_info": {"general.architecture": "new", "new.context_length": 1048576, "other.context_length": 8192}}
    monkeypatch.setattr(cloud, "_request", request)
    result = cloud.catalog()
    assert not result["stale"]
    assert len(result["models"]) == 2
    assert result["models"][0]["context_length"] == 1048576
    assert result["models"][0]["local_name"] == "new-model:cloud"
    assert result["models"][1]["context_length"] is None
    assert result["models"][1]["local_name"] == "tagged:123-cloud"


def test_cache_refresh_and_failure_preserve_last_catalog(monkeypatch):
    monkeypatch.setattr(cloud, "_request", lambda *args: {"models": [{"name": "one"}]} if args[0] == "tags" else {})
    first = cloud.catalog()
    first["models"].clear()
    def offline(*args):
        raise OSError("offline")
    monkeypatch.setattr(cloud, "_request", offline)
    assert len(cloud.catalog()["models"]) == 1
    stale = cloud.catalog(refresh=True)
    assert stale["stale"] and stale["error"]
    assert len(stale["models"]) == 1


@pytest.mark.parametrize("value", [0, -1, True, "128000", None])
def test_unknown_limits_are_not_guessed(value):
    assert cloud.context_limit({"general.architecture": "x", "x.context_length": value}) is None
