"""Production readiness tests for Ollama retries, trusted workspace paths,
auto-LSP post-edit diagnostics, and FFmpeg/YouTube media studio tools."""

from __future__ import annotations

import json
import shutil
import subprocess
import threading
from types import SimpleNamespace
from pathlib import Path

import httpx
import pytest


def test_ollama_metadata_skips_cloud_and_fails_soft_on_502(monkeypatch):
    from jaeger_agent.adapters.ollama import OllamaAdapter

    called = []

    def fake_post(*args, **kwargs):
        called.append(args[0])
        req = httpx.Request("POST", args[0])
        resp = httpx.Response(502, request=req, text="Bad Gateway")
        raise httpx.HTTPStatusError("502 Bad Gateway", request=req, response=resp)

    monkeypatch.setattr(httpx, "post", fake_post)

    cloud_adapter = OllamaAdapter(
        model="mistral-large-4:cloud",
        base_url="http://127.0.0.1:11434/v1",
        provider="ollama",
    )
    assert cloud_adapter._metadata() == {}
    assert called == []  # :cloud skips /api/show completely

    local_adapter = OllamaAdapter(
        model="qwen3.5:9b",
        base_url="http://127.0.0.1:11434/v1",
        provider="ollama",
    )
    assert local_adapter._metadata() == {}  # fails soft instead of raising 502
    assert len(called) == 1


def test_ollama_call_once_retries_zero_event_503_then_succeeds(monkeypatch):
    from jaeger_agent.adapters import ollama as ollama_mod
    from jaeger_agent.adapters.ollama import OllamaAdapter

    monkeypatch.setattr(ollama_mod, "_ZERO_EVENT_RETRY_DELAYS", (0.01, 0.01))
    attempts = {"n": 0}

    class _FakeResp:
        def __init__(self, status: int, lines: list[str] | None = None):
            self.status_code = status
            self._lines = lines or []
            self.request = httpx.Request("POST", "http://127.0.0.1:11434/api/chat")

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def raise_for_status(self):
            if self.status_code >= 400:
                raise httpx.HTTPStatusError(
                    f"{self.status_code}",
                    request=self.request,
                    response=httpx.Response(self.status_code, request=self.request),
                )

        def iter_lines(self):
            yield from self._lines

        def close(self):
            pass

    class _FakeClient:
        def __init__(self, *a, **kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def stream(self, method, url, json=None):
            attempts["n"] += 1
            if attempts["n"] < 2:
                return _FakeResp(503)
            return _FakeResp(
                200,
                [
                    json_dumps({"message": {"content": "hello"}, "done": False}),
                    json_dumps({"model": "mistral-large-4:cloud", "done": True, "done_reason": "stop"}),
                ],
            )

        def close(self):
            pass

    def json_dumps(obj):
        return json.dumps(obj)

    monkeypatch.setattr(httpx, "Client", _FakeClient)
    adapter = OllamaAdapter(
        model="mistral-large-4:cloud",
        base_url="http://127.0.0.1:11434/v1",
        provider="ollama",
    )
    out = adapter._call_once(
        {"messages": [{"role": "user", "content": "hi"}], "max_tokens": 256},
        threading.Event(),
    )
    assert attempts["n"] == 2
    assert out["choices"][0]["message"]["content"] == "hello"


def test_trusted_paths_allow_owner_folder_but_keep_secrets_locked(tmp_path):
    from jaeger_agent.core import workspace as ws

    inst = tmp_path / "inst"
    (inst / "skills").mkdir(parents=True)
    (inst / "workspace").mkdir(parents=True)
    docs = tmp_path / "OwnerDocs"
    docs.mkdir()
    cfg = inst / "config.yaml"
    cfg.write_text(
        f"workspace:\n  trusted_paths:\n    - {docs}\n    - /\n    - ~\n",
        encoding="utf-8",
    )
    layout = SimpleNamespace(
        root=inst,
        skills_dir=inst / "skills",
        workspace_dir=inst / "workspace",
        config_path=cfg,
    )
    trusted = ws.configured_trusted_paths(layout)
    assert trusted == [docs.resolve()]
    # Raw filesystem root and home dir must NEVER be admitted!
    assert Path("/").resolve() not in trusted
    assert Path.home().resolve() not in trusted


def test_file_write_auto_attaches_lsp_diagnostics_on_invalid_json(tmp_path):
    from jaeger_agent.core import workspace as ws
    from jaeger_agent.tools.files import file_write

    inst = tmp_path / "inst"
    (inst / "skills").mkdir(parents=True)
    (inst / "workspace").mkdir(parents=True)
    (inst / "logs").mkdir(parents=True)
    layout = SimpleNamespace(
        root=inst,
        skills_dir=inst / "skills",
        workspace_dir=inst / "workspace",
        logs_dir=inst / "logs",
        audit_log_path=inst / "logs" / "audit.log",
        memory_dir=inst / "memory",
        config_path=inst / "config.yaml",
    )
    prev_layout = ws._layout
    try:
        ws._layout = layout
        res = file_write("workspace/broken.json", '{"a": 1, }')
        assert res["written"] is True
        assert res.get("lsp_ok") is False
        assert res.get("lsp_diagnostics")
    finally:
        ws._layout = prev_layout


@pytest.mark.skipif(not shutil.which("ffmpeg") and not Path("/opt/homebrew/bin/ffmpeg").is_file(), reason="ffmpeg not installed")
def test_media_studio_probe_and_render_video_end_to_end(tmp_path):
    from jaeger_agent.core import workspace as ws
    from jaeger_agent.tools.media_studio import _which_media, probe_media, render_video, youtube_studio

    ffmpeg = _which_media("ffmpeg")
    assert ffmpeg is not None

    inst = tmp_path / "inst"
    (inst / "skills").mkdir(parents=True)
    (inst / "workspace").mkdir(parents=True)
    (inst / "logs").mkdir(parents=True)
    layout = SimpleNamespace(
        root=inst,
        skills_dir=inst / "skills",
        workspace_dir=inst / "workspace",
        logs_dir=inst / "logs",
        audit_log_path=inst / "logs" / "audit.log",
        memory_dir=inst / "memory",
        config_path=inst / "config.yaml",
    )
    prev_layout = ws._layout
    try:
        ws._layout = layout
        # Generate a 2-second test video with colorbars + sine audio.
        src = inst / "workspace" / "sample.mp4"
        subprocess.run(
            [
                ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                "-f", "lavfi", "-i", "testsrc=duration=2:size=640x360:rate=24",
                "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(src),
            ],
            check=True,
        )
        probed = probe_media(str(src))
        assert probed["ok"] is True
        assert probed["video"]["width"] == 640
        assert probed["audio"]["codec"] == "aac"

        trimmed = render_video("trim", [str(src)], "workspace/clip.mp4", start="0", duration="1")
        assert trimmed["ok"] is True
        assert Path(trimmed["output_path"]).is_file()

        thumb = render_video("thumbnail", [str(src)], "workspace/thumb.png", start="0.5")
        assert thumb["ok"] is True
        assert thumb["media"]["video"]["width"] == 1280
        assert thumb["media"]["video"]["height"] == 720

        yt = youtube_studio(action="status")
        assert yt["ok"] is True
        assert yt["tools"]["ffmpeg"] is not None
    finally:
        ws._layout = prev_layout
