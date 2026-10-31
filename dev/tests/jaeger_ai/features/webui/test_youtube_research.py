"""YouTube research pipeline — MOCKED unit tests (no network, no yt-dlp/ffmpeg/whisper/LLM calls).
The real end-to-end run lives in dev/tests/jaeger_ai/features/webui/real_youtube_e2e.py and is never run by pytest."""
from __future__ import annotations

import importlib.util
import json
import pathlib
import subprocess

import pytest

API = pathlib.Path(__file__).resolve().parents[5] / "jaeger_ai/features/webui/api"
VTT = """WEBVTT
Kind: captions
Language: en

00:00:00.000 --> 00:00:02.000
<c>Stop</c> scrolling. Here is the trick

00:00:02.000 --> 00:00:04.000
Stop scrolling. Here is the trick

00:00:04.000 --> 00:00:08.000
subscribe for more &amp; hit the bell
"""
ANALYSIS = {"summary": "s", "hook": {"first_15s": "Stop scrolling", "technique": "pattern interrupt", "strength": 4}, "structure": {"segments": [], "pattern": "hook-demo-cta"},
            "pacing": {"words_per_minute": 170, "notes": "fast"}, "editing": {"style": "jump cuts", "devices": []}, "tone": {"voice": "punchy", "persona": "friend", "vocabulary": []},
            "visuals": {"shot_types": ["talking head"], "on_screen_text": "captions", "notes": ""}, "calls_to_action": [{"at_s": 6, "text": "subscribe"}], "title_pattern": "How I X"}
GUIDE = {"voice_and_tone": "punchy", "hooks": {"pattern": "pattern interrupt", "templates": ["Stop scrolling — {claim}"]}, "structure_template": [{"section": "Hook", "share_pct": 10, "purpose": "grab"}],
         "pacing": {"target_wpm": 170, "notes": ""}, "editing": ["jump cuts"], "visuals": ["captions"], "titles_and_thumbnails": {"title_formulas": ["How I X"], "thumbnail_notes": "face + 3 words"},
         "calls_to_action": ["subscribe"], "dos": ["be quick"], "donts": ["ramble"], "example_lines": ["Stop scrolling."]}
DRAFT = {"titles": ["a", "b", "c", "d", "e"], "hook": "Stop scrolling.", "script": [{"section": "Hook", "est_seconds": 10, "voiceover": "hi"}],
         "shot_list": [{"shot": 1, "section": "Hook", "visual": "face", "on_screen_text": "STOP", "est_seconds": 3}], "thumbnail_ideas": [{"concept": "c", "text": "t", "composition": "x"}],
         "call_to_action": "subscribe", "description": "d"}


class Fake:
    """Stands in for yt-dlp / ffmpeg / whisper-cli and records every command."""
    def __init__(self, captions=("aaaaaaaaaaa",), fail_meta=()):
        self.cmds, self.captions, self.fail_meta = [], set(captions), set(fail_meta)

    def __call__(self, cmd, timeout):
        self.cmds.append(cmd)
        ok = lambda out="": subprocess.CompletedProcess(cmd, 0, out, "")
        tool = cmd[0]
        if tool == "yt-dlp" and "--flat-playlist" in cmd:
            return ok(json.dumps({"title": "My Playlist", "channel": "Matt", "entries": [
                {"id": "aaaaaaaaaaa", "title": "One", "duration": 60}, {"id": "bbbbbbbbbbb", "title": "Two", "duration": 120}, {"id": "ccccccccccc", "title": "[Private video]"}]}))
        url = cmd[-1]; vid = url.split("v=")[-1] if "v=" in url else None
        if tool == "yt-dlp" and "-J" in cmd:
            if vid in self.fail_meta:
                return subprocess.CompletedProcess(cmd, 1, "", "ERROR: Video unavailable")
            return ok(json.dumps({"id": vid, "title": vid, "duration": 60, "channel": "Matt", "description": "desc", "subtitles": {"en": []} if vid in self.captions else {}, "automatic_captions": {}}))
        if tool == "yt-dlp" and "--write-subs" in cmd:
            out = pathlib.Path(cmd[cmd.index("-o") + 1]).parent
            if vid in self.captions:
                (out / "subs.en.vtt").write_text(VTT)
            return ok()
        if tool == "yt-dlp" and "-f" in cmd:
            tmpl = cmd[cmd.index("-o") + 1]
            pathlib.Path(tmpl.replace("%(ext)s", "m4a" if "bestaudio" in cmd[cmd.index("-f") + 1] else "mp4")).write_bytes(b"media")
            return ok()
        if tool == "ffmpeg":
            pathlib.Path(cmd[-1]).write_bytes(b"\xff\xd8jpg")
            return ok()
        if tool == "whisper-cli":
            pathlib.Path(cmd[cmd.index("-of") + 1] + ".txt").write_text("whispered words here")
            return ok()
        raise AssertionError(f"unexpected command {cmd}")


@pytest.fixture()
def yt(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("_yt_test", API / "youtube_research.py")
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    wm = tmp_path / "home/.whisper/ggml-base.en.bin"; wm.parent.mkdir(parents=True); wm.write_bytes(b"x")
    monkeypatch.setattr(m.Path, "home", staticmethod(lambda: tmp_path / "home"))
    calls = {"llm": [], "vision": 0, "stage": [], "attach": [], "docs": {}}
    def llm(model, prompt):
        calls["llm"].append(prompt)
        if "STYLE GUIDE so a writer" in prompt: return "```json\n" + json.dumps(GUIDE) + "\n```"
        if "draft a new YouTube video" in prompt: return "Here you go: " + json.dumps(DRAFT)
        return json.dumps(ANALYSIS)
    def vision(model, prompt, b64):
        calls["vision"] += 1; return "talking head, white text"
    def save_doc(did, body):
        did = did or f"doc{len(calls['docs']):06d}"; calls["docs"][did] = body; return {"id": did, **body}
    recs = {}
    m.bind(state_root=lambda: tmp_path, llm=llm, vision=vision, ollama_models=lambda: ["gemma4:12b", "minicpm-v:latest"],
           set_stage=lambda tid, b: (calls["stage"].append((tid, b["stage"])), recs.__setitem__(tid, {"stage": b["stage"]})),
           attach=lambda tid, b: calls["attach"].append((tid, b["kind"], b["ref"])), get_record=lambda tid: recs.get(tid), save_doc=save_doc,
           which=lambda n: f"/usr/bin/{n}", run=Fake())
    m._calls = calls; m._tmp = tmp_path
    return m


URL = "https://www.youtube.com/playlist?list=PLabcdefghij12345"


def run_sync(yt, body=None, **kw):
    yt.start = (lambda orig: (lambda tid, **k: orig(tid, wait=True, **k)))(yt.start)
    return yt.ingest(body or {"playlist_url": URL, **kw})


def test_rejects_non_youtube_and_listless_urls(yt):
    for bad in ["http://www.youtube.com/playlist?list=PLabcdefghij12345", "https://evil.com/playlist?list=PLabcdefghij12345", "https://www.youtube.com/watch?v=aaaaaaaaaaa", "file:///etc/passwd"]:
        with pytest.raises(yt.YtError):
            yt.playlist_id(bad)
    assert yt.playlist_id("https://www.youtube.com/watch?v=aaaaaaaaaaa&list=PLabcdefghij12345") == "PLabcdefghij12345"


def test_parse_vtt_dedupes_rollup_and_strips_tags():
    spec = importlib.util.spec_from_file_location("_yt_vtt", API / "youtube_research.py")
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    segs = m.parse_vtt(VTT)
    assert [s["text"] for s in segs] == ["Stop scrolling. Here is the trick", "subscribe for more & hit the bell"] and segs[1]["start"] == 4.0


def test_full_job_captions_whisper_frames_analysis_style_guide(yt):
    s = run_sync(yt)
    j = yt.status("yt:PLabcdefghij12345")
    assert j["state"] == "done" and [v["id"] for v in j["videos"]] == ["aaaaaaaaaaa", "bbbbbbbbbbb"]  # private video dropped
    d = yt._tmp / "research/youtube/yt_PLabcdefghij12345"
    t1 = json.loads((d / "aaaaaaaaaaa/transcript.json").read_text()); t2 = json.loads((d / "bbbbbbbbbbb/transcript.json").read_text())
    assert t1["source"] == "youtube_captions" and t2["source"].startswith("whisper.cpp") and t2["text"] == "whispered words here"
    assert not list((d / "bbbbbbbbbbb").glob("audio*"))  # audio cleaned up
    assert len(json.loads((d / "aaaaaaaaaaa/frames.json").read_text())) == yt.N_FRAMES and not list((d / "aaaaaaaaaaa").glob("lowres.*"))
    assert yt._calls["vision"] == 2 * yt.N_FRAMES
    a = json.loads((d / "aaaaaaaaaaa/analysis.json").read_text())
    assert a["hook"]["technique"] == "pattern interrupt" and a["pacing"]["measured_words_per_minute"] == round(len(t1["text"].split()) / 1, 1)
    g = yt.style_guide("yt:PLabcdefghij12345")
    assert g["json"]["voice_and_tone"] == "punchy" and "## Sources" in g["markdown"] and g["document_id"]
    assert ("yt:PLabcdefghij12345", "research") in yt._calls["stage"]
    kinds = [k for _, k, _ in yt._calls["attach"]]
    assert kinds == ["source", "document"]
    assert j["progress"] == {"steps_finished": 10, "steps_total": 10, "videos_analysed": 2, "videos_with_errors": 0, "videos": 2}


def test_rerun_is_idempotent_and_force_redoes_only_that_step(yt):
    run_sync(yt)
    n_cmds, n_llm = len(yt._deps["run"].cmds), len(yt._calls["llm"])
    yt.ingest({"playlist_url": URL})  # same playlist → same job, nothing redone
    assert len(yt._deps["run"].cmds) == n_cmds and len(yt._calls["llm"]) == n_llm
    yt.start("yt:PLabcdefghij12345", force=["analysis"])
    assert len(yt._deps["run"].cmds) == n_cmds and len(yt._calls["llm"]) == n_llm + 2  # 2 analyses; guide reused


def test_errors_are_recorded_per_video_and_resume_after_fix(yt):
    yt._deps["run"].fail_meta = {"bbbbbbbbbbb"}
    run_sync(yt)
    j = yt.status("yt:PLabcdefghij12345")
    b = next(v for v in j["videos"] if v["id"] == "bbbbbbbbbbb")
    assert b["steps"]["meta"]["status"] == "error" and "unavailable" in b["steps"]["meta"]["error"] and b["steps"]["analysis"]["status"] == "blocked"
    assert j["state"] == "done_with_errors" and j["style_guide"]["status"] == "done" and j["progress"]["videos_with_errors"] == 1
    yt._deps["run"].fail_meta = set()
    yt.start("yt:PLabcdefghij12345", force=["style_guide"])
    j = yt.status("yt:PLabcdefghij12345")
    assert j["state"] == "done" and j["progress"]["videos_analysed"] == 2


def test_no_captions_and_no_whisper_is_an_error_not_a_fake_transcript(yt):
    yt._deps["which"] = lambda n: None if n == "whisper-cli" else f"/usr/bin/{n}"
    run_sync(yt)
    b = next(v for v in yt.status("yt:PLabcdefghij12345")["videos"] if v["id"] == "bbbbbbbbbbb")
    assert b["steps"]["transcript"]["status"] == "error" and "whisper" in b["steps"]["transcript"]["error"]
    assert not (yt._tmp / "research/youtube/yt_PLabcdefghij12345/bbbbbbbbbbb/transcript.json").exists()


def test_no_vision_model_skips_frame_notes(yt):
    yt._deps["ollama_models"] = lambda: ["gemma4:12b"]
    run_sync(yt)
    a = next(v for v in yt.status("yt:PLabcdefghij12345")["videos"] if v["id"] == "aaaaaaaaaaa")
    assert a["steps"]["frame_notes"]["status"] == "skipped" and a["steps"]["analysis"]["status"] == "done"


def test_bad_llm_json_retries_then_errors(yt):
    yt._deps["llm"] = lambda m, p: "I cannot do that"
    run_sync(yt)
    a = next(v for v in yt.status("yt:PLabcdefghij12345")["videos"] if v["id"] == "aaaaaaaaaaa")
    assert a["steps"]["analysis"]["status"] == "error" and "JSON" in a["steps"]["analysis"]["error"]


def test_draft_saves_and_attaches_deliverable_never_publishes(yt):
    run_sync(yt)
    with pytest.raises(yt.YtError):
        yt.draft("yt:PLabcdefghij12345", {"topic": ""})
    r = yt.draft("yt:PLabcdefghij12345", {"topic": "Home espresso on a budget"})
    assert r["draft"]["_meta"]["published"] is False and "## Shot list" in r["markdown"] and "Not published" in r["markdown"]
    assert ("yt:PLabcdefghij12345", "deliverable", f"document:{r['document_id']}") in yt._calls["attach"]
    assert yt.status("yt:PLabcdefghij12345")["drafts"][0]["topic"] == "Home espresso on a budget"
    assert all("upload" not in " ".join(c) for c in yt._deps["run"].cmds)


def test_frame_file_rejects_traversal(yt):
    run_sync(yt)
    assert yt.frame_file("yt:PLabcdefghij12345", "aaaaaaaaaaa", "f00.jpg").is_file()
    for bad in [("aaaaaaaaaaa", "../job.json"), ("../../etc/xx", "f00.jpg")]:
        with pytest.raises(yt.YtError):
            yt.frame_file("yt:PLabcdefghij12345", *bad)


def test_webui_route_wiring(tmp_path, monkeypatch):
    monkeypatch.setenv("JAEGER_STATE_HOME", str(tmp_path))
    spec = importlib.util.spec_from_file_location("_unified_api_yt", API / "unified_api.py")
    api = importlib.util.module_from_spec(spec); spec.loader.exec_module(api)
    out = {}
    class P: path = "/v1/research/youtube/nope"
    with pytest.raises(Exception):
        api._yt_route(None, "/v1/research/youtube/yt:none", "GET", {}, lambda h, d, status=200: out.update(d))
    assert api.route(None, type("P", (), {"path": "/v1/research/youtube/yt:none"})(), "GET", lambda h: {}, lambda h, d, status=200: out.update(d, _s=status))
    assert out["_s"] == 404
