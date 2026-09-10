import importlib.util
import io
import json
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[4] / "integrations/hermes_webui/jaeger_ollama.py"
spec = importlib.util.spec_from_file_location("jaeger_ollama", SOURCE)
ollama = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ollama)


def config():
    return {"model": {"provider": "ollama", "default": "glm-5.3-flash:cloud", "base_url": "http://rack/v1"},
            "ollama_hosts": {"rack": {"label": "Rack PC", "base_url": "http://rack/v1"},
                             "mac": {"label": "Mac", "base_url": "http://mac/v1"}}}


def test_routes_preserve_tags_and_host():
    assert ollama.resolve("@ollama-rack:glm-5.3-flash:cloud", config()) == (
        "glm-5.3-flash:cloud", "ollama", "http://rack/v1")
    assert ollama.resolve("@ollama-mac:qwen3:8b", config()) == ("qwen3:8b", "ollama", "http://mac/v1")
    assert ollama.resolve("@custom:glm-5.3-flash:cloud", config())[0] == "glm-5.3-flash:cloud"


def test_independent_inventories_and_failure(monkeypatch):
    def probe(url, **kwargs):
        if "mac" in url:
            raise ConnectionRefusedError()
        return io.BytesIO(json.dumps({"models": [
            {"name": "glm-5.3-flash:cloud", "remote_host": "https://ollama.com"},
            {"name": "qwen3:8b"}, {"name": "mxbai-embed-large:latest"}]}).encode())
    monkeypatch.setattr(ollama.urllib.request, "urlopen", probe)
    data = ollama.catalog(config(), refresh=True)
    assert data["active_provider"] == "ollama-rack"
    rack, mac = data["groups"]
    assert len(rack["models"]) == 2
    assert "Cloud" in rack["models"][0]["label"]
    assert "Local" in rack["models"][1]["label"]
    assert mac["models"] == [] and mac["status"] == "unavailable"
