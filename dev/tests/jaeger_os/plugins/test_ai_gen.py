"""ai_gen plugin — fal.ai cloud image/video generation.

Covers the contract the port promised: friendly unconfigured error (never
a crash), correct queue-submit payload/URL shape, the submit → poll →
fetch-result → download flow against a mocked HTTP layer, and sandboxed
output-path resolution under <instance>/skills/.
"""

from __future__ import annotations

import pytest

from jaeger_os.agent import tools
from jaeger_os.core.instance.instance import InstanceLayout
from jaeger_os.plugins import ai_gen


@pytest.fixture()
def bound_instance(tmp_path):
    layout = InstanceLayout(root=tmp_path / "inst")
    layout.root.mkdir(parents=True, exist_ok=True)
    layout.ensure_dirs()
    tools.bind(layout)
    return layout


@pytest.fixture()
def fake_http(monkeypatch):
    """Mock the plugin's HTTP seams: records the submit call, walks a
    configurable status sequence, serves the result, fakes the download."""
    state = {
        "posts": [],
        "gets": [],
        "statuses": ["COMPLETED"],
        "result": {"images": [{"url": "https://cdn.fal.example/out.png"}]},
        "downloads": [],
    }

    def _post(url, payload, key):
        state["posts"].append((url, payload, key))
        return {
            "request_id": "req-1",
            "status_url": "https://queue.fal.run/x/requests/req-1/status",
            "response_url": "https://queue.fal.run/x/requests/req-1",
        }

    def _get(url, key):
        state["gets"].append(url)
        if url.endswith("/status"):
            return {"status": state["statuses"].pop(0)
                    if state["statuses"] else "COMPLETED"}
        return state["result"]

    def _download(url, target):
        state["downloads"].append((url, target))
        target.write_bytes(b"fake-media-bytes")

    monkeypatch.setattr(ai_gen, "_http_post", _post)
    monkeypatch.setattr(ai_gen, "_http_get", _get)
    monkeypatch.setattr(ai_gen, "_http_download", _download)
    monkeypatch.setattr(ai_gen, "POLL_INTERVAL_S", 0.0)
    monkeypatch.setattr(ai_gen, "_fal_key", lambda: "test-key")
    return state


# ── unconfigured → friendly error, never a crash ─────────────────────

def test_unconfigured_returns_friendly_error(bound_instance, monkeypatch):
    monkeypatch.setattr(ai_gen, "_fal_key", lambda: "")
    for fn in (ai_gen.generate_image_fal, ai_gen.generate_video_fal):
        res = fn("a red fox")
        assert res["ok"] is False
        assert "FAL_KEY" in res["error"]
        assert "fal.ai" in res["error"]
        assert "set_credential" in res["error"]


def test_fal_key_env_fallback(monkeypatch):
    monkeypatch.setattr(
        "jaeger_os.core.context.get_layout",
        lambda: (_ for _ in ()).throw(RuntimeError("unbound")))
    monkeypatch.delenv("fal_key", raising=False)
    monkeypatch.setenv("FAL_KEY", "env-key-123")
    assert ai_gen._fal_key() == "env-key-123"
    monkeypatch.delenv("FAL_KEY", raising=False)
    assert ai_gen._fal_key() == ""


# ── request payload + model normalization ────────────────────────────

def test_image_request_payload_shape(bound_instance, fake_http):
    res = ai_gen.generate_image_fal("a red fox in snow")
    assert res["ok"] is True, res
    url, payload, key = fake_http["posts"][0]
    # "flux/schnell" default gets the fal-ai/ vendor prefix.
    assert url == "https://queue.fal.run/fal-ai/flux/schnell"
    assert payload == {"prompt": "a red fox in snow"}
    assert key == "test-key"
    assert res["model"] == "fal-ai/flux/schnell"


def test_video_default_model_and_result_shape(bound_instance, fake_http):
    fake_http["result"] = {"video": {"url": "https://cdn.fal.example/out.mp4"}}
    res = ai_gen.generate_video_fal("a fox trotting through snowfall")
    assert res["ok"] is True, res
    url, payload, _ = fake_http["posts"][0]
    assert url == f"https://queue.fal.run/{ai_gen.DEFAULT_VIDEO_MODEL}"
    assert payload == {"prompt": "a fox trotting through snowfall"}
    assert res["absolute_path"].endswith(".mp4")
    assert fake_http["downloads"][0][0] == "https://cdn.fal.example/out.mp4"


# ── queue → poll → result → download flow ────────────────────────────

def test_queue_poll_flow_walks_statuses_then_downloads(bound_instance, fake_http):
    fake_http["statuses"] = ["IN_QUEUE", "IN_PROGRESS", "COMPLETED"]
    res = ai_gen.generate_image_fal("prompt", output_path="art/fox.png")
    assert res["ok"] is True, res
    status_gets = [u for u in fake_http["gets"] if u.endswith("/status")]
    assert len(status_gets) == 3                      # polled until COMPLETED
    assert fake_http["gets"][-1].endswith("/req-1")   # then fetched the result
    dl_url, dl_target = fake_http["downloads"][0]
    assert dl_url == "https://cdn.fal.example/out.png"
    assert dl_target.read_bytes() == b"fake-media-bytes"


def test_failed_status_surfaces_as_error(bound_instance, fake_http):
    fake_http["statuses"] = ["FAILED"]
    res = ai_gen.generate_image_fal("prompt")
    assert res["ok"] is False
    assert "failed" in res["error"].lower()
    assert not fake_http["downloads"]


def test_timeout_is_a_hard_wall(bound_instance, fake_http, monkeypatch):
    fake_http["statuses"] = ["IN_PROGRESS"] * 50
    monkeypatch.setattr(ai_gen, "IMAGE_TIMEOUT_S", 0.0)
    res = ai_gen.generate_image_fal("prompt")
    assert res["ok"] is False
    assert "timed out" in res["error"]


# ── output-path resolution (sandboxed under skills/) ─────────────────

def test_output_path_resolves_under_skills(bound_instance, fake_http):
    res = ai_gen.generate_image_fal("prompt", output_path="art/fox.png")
    assert res["ok"] is True, res
    expected = bound_instance.skills_dir / "art" / "fox.png"
    assert res["absolute_path"] == str(expected)
    assert expected.is_file()
    # Default (empty output_path) → timestamped name under skills/, right ext.
    res2 = ai_gen.generate_image_fal("prompt")
    assert res2["absolute_path"].startswith(str(bound_instance.skills_dir))
    assert res2["absolute_path"].endswith(".png")


def test_output_path_escape_is_rejected(bound_instance, fake_http):
    res = ai_gen.generate_image_fal("prompt", output_path="../../evil.png")
    assert res["ok"] is False
    assert not fake_http["posts"]          # rejected before any network call
