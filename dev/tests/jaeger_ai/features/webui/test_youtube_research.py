"""YouTube research pipeline v2 - MOCKED unit tests (no network, no yt-dlp/ffmpeg/whisper/LLM/VLM calls).
The real end-to-end run lives in real_youtube_e2e.py and is never collected by pytest."""
from __future__ import annotations

import importlib.util
import json
import pathlib
import subprocess

import pytest

API = pathlib.Path(__file__).resolve().parents[5] / "jaeger_ai/features/webui/api"
VTT = """WEBVTT
Kind: captions

00:00:00.000 --> 00:00:02.000
<c>Stop</c> scrolling. Here is the trick

00:00:02.000 --> 00:00:04.000
Stop scrolling. Here is the trick

00:00:04.000 --> 00:00:08.000
subscribe for more &amp; hit the bell
"""
A = {"summary": "s", "topics": ["robots"], "key_ideas": ["k"], "hook": {"first_15s": "Stop", "technique": "interrupt", "strength": 4},
     "structure": {"segments": [], "pattern": "hook-demo-cta"}, "pacing": {"notes": "fast"}, "editing": {"style": "jump cuts", "devices": []},
     "tone": {"voice": "punchy", "persona": "friend", "vocabulary": []}, "visuals": {"shot_types": ["talking head"], "on_screen_text": "", "notes": ""},
     "calls_to_action": [{"at": "0:06", "text": "subscribe"}], "title_pattern": "How I X"}
B = {"scores": {"channel_context": 4, "self_interest": 3, "style_copy": 5}, "flags": {"substance": True, "hype": False, "actionable": True, "needs_visual_review": False},
     "confidence": 0.8, "channel_idea": "idea", "tools_detected": ["ffmpeg"], "key_insights": ["i"],
     "areas": {"production": [{"technique": "Jump cut every sentence", "detail": "d", "why_it_matters": "w", "apply_for_jr": "a", "quote": "Stop scrolling", "timestamp": "0:00"}]}}
GUIDE = {"voice_and_tone": "punchy", "dos": ["be quick"]}
DRAFT = {"titles": ["Short title", "x" * 70], "hook": "h", "script": [{"section": "Hook", "est_seconds": 10, "voiceover": "insane"}, {"section": "Build", "est_seconds": 50}],
         "tags": ["A", "b"]}
SCENE = "frame:0 pts_time:3.5\nframe:1 pts_time:7.25\nframe:2 pts_time:12.0\n"
EBU = "silence_start: 1.0\nsilence_end: 1.8 | silence_duration: 0.8\nSummary:\n  I: -14.2 LUFS\n  LRA: 5.1 LU\n  Peak: -1.0 dBFS\n"


class Fake:
    def __init__(self, captions=("aaaaaaaaaaa",), fail_meta=()):
        self.cmds, self.captions, self.fail_meta = [], set(captions), set(fail_meta)

    def __call__(self, cmd, timeout):
        self.cmds.append(cmd)
        ok = lambda out="", err="": subprocess.CompletedProcess(cmd, 0, out, err)
        tool = cmd[0]
        if tool == "yt-dlp" and "--flat-playlist" in cmd:
            return ok(json.dumps({"title": "My Playlist", "channel": "Matt", "entries": [
                {"id": "aaaaaaaaaaa", "title": "One", "duration": 60}, {"id": "bbbbbbbbbbb", "title": "Two", "duration": 120}, {"id": "ccccccccccc", "title": "[Private video]"}]}))
        url = cmd[-1]
        vid = url.split("v=")[-1] if "v=" in url else None
        if tool == "yt-dlp" and "-J" in cmd:
            if vid in self.fail_meta:
                return subprocess.CompletedProcess(cmd, 1, "", "ERROR: Video unavailable")
            return ok(json.dumps({"id": vid, "title": vid, "duration": 60, "channel": "Matt", "subtitles": {"en": []} if vid in self.captions else {}}))
        if tool == "yt-dlp" and "--write-subs" in cmd:
            if vid in self.captions:
                (pathlib.Path(cmd[cmd.index("-o") + 1]).parent / "subs.en.vtt").write_text(VTT)
            return ok()
        if tool == "yt-dlp" and "-f" in cmd:
            ext = "m4a" if "bestaudio" in cmd[cmd.index("-f") + 1] else "mp4"
            pathlib.Path(cmd[cmd.index("-o") + 1].replace("%(ext)s", ext)).write_bytes(b"media")
            return ok()
        if tool == "ffmpeg":
            if "-vf" in cmd and "select=" in cmd[cmd.index("-vf") + 1]:
                return ok(SCENE)
            if "-af" in cmd:
                return ok("", EBU)
            pathlib.Path(cmd[-1]).write_bytes(b"\xff\xd8jpg")
            return ok()
        if tool == "whisper-cli":
            of = cmd[cmd.index("-of") + 1]
            pathlib.Path(of + ".json").write_text(json.dumps({"transcription": [{"offsets": {"from": 0, "to": 2000}, "text": " whispered words",
                                                                                "tokens": [{"text": " whispered", "offsets": {"from": 0, "to": 900}, "p": 0.9}, {"text": " words", "offsets": {"from": 900, "to": 2000}, "p": 0.8}]}]}))
            return ok()
        raise AssertionError(f"unexpected command {cmd}")


class FakeRM:
    def __init__(self):
        self.acq, self.released = [], []
    def acquire(self, kind, job="-", priority=5, model=None):
        import contextlib
        self.acq.append((kind, model))
        return contextlib.nullcontext({})
    def release_models(self, ms):
        self.released.append(list(ms))
    def job_usage(self, job):
        return {"wait_s": 0}


@pytest.fixture()
def yt(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("_yt_test", API / "youtube_research.py")
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    wm = tmp_path / "home/.whisper/ggml-base.en.bin"; wm.parent.mkdir(parents=True); wm.write_bytes(b"x")
    monkeypatch.setattr(m.Path, "home", staticmethod(lambda: tmp_path / "home"))
    calls = {"llm": [], "vision": [], "stage": [], "attach": [], "docs": {}}

    def llm(model, prompt):
        calls["llm"].append(prompt)
        if "STYLE GUIDE." in prompt: return "```json\n" + json.dumps(GUIDE) + "\n```"
        if "draft a new YouTube video" in prompt: return "Here: " + json.dumps(DRAFT)
        if "Score and mine" in prompt: return json.dumps(B)
        return json.dumps(A)

    def vision(model, prompt, imgs):
        calls["vision"].append((model, len(imgs))); return "hard cut to B-roll"

    def save_doc(did, body):
        did = did or f"doc{len(calls['docs']):06d}"; calls["docs"][did] = body; return {"id": did, **body}
    recs = {}
    rm = FakeRM()
    m.bind(state_root=lambda: tmp_path, llm=llm, vision=vision, ollama_models=lambda: ["gemma4:12b", "qwen3-vl:8b"],
           set_stage=lambda tid, b: (calls["stage"].append((tid, b["stage"])), recs.__setitem__(tid, {"stage": b["stage"]})),
           attach=lambda tid, b: calls["attach"].append((tid, b["kind"], b["ref"])), get_record=lambda tid: recs.get(tid), save_doc=save_doc,
           which=lambda n: f"/usr/bin/{n}", run=Fake(), research_python=None, api_key=lambda: None, hermes_sources=lambda: [], rm=rm)
    m._calls, m._tmp, m._rm = calls, tmp_path, rm
    return m


URL = "https://www.youtube.com/playlist?list=PLabcdefghij12345"
TID = "yt:PLabcdefghij12345"


def run_sync(yt, body=None, **kw):
    yt.start = (lambda orig: (lambda tid, **k: orig(tid, **{**k, "wait": True})))(yt.start)
    return yt.ingest(body or {"playlist_url": URL, **kw})


def vd(yt, vid):
    return yt._tmp / "research/youtube/yt_PLabcdefghij12345" / vid


def test_rejects_bad_urls(yt):
    for bad in ["http://www.youtube.com/playlist?list=PLabcdefghij12345", "https://evil.com/playlist?list=PLabcdefghij12345", "https://www.youtube.com/watch?v=aaaaaaaaaaa"]:
        with pytest.raises(yt.YtError):
            yt.playlist_id(bad)


def test_parse_vtt_dedupes_rollup(yt):
    segs = yt.parse_vtt(VTT)
    assert [s["text"] for s in segs] == ["Stop scrolling. Here is the trick", "subscribe for more & hit the bell"]


def test_full_v2_job(yt):
    run_sync(yt)
    j = yt.status(TID)
    assert [v["id"] for v in j["videos"]] == ["aaaaaaaaaaa", "bbbbbbbbbbb"]
    assert j["state"] == "done", j
    a = vd(yt, "aaaaaaaaaaa")
    assert json.loads((a / "transcript.json").read_text())["source"] == "youtube_captions"
    b = vd(yt, "bbbbbbbbbbb")
    tb = json.loads((b / "transcript.json").read_text())
    assert tb["source"].startswith("whisper.cpp") and "fallback_reason" in tb and json.loads((b / "words.json").read_text())[0]["w"] == "whispered"
    cuts = json.loads((a / "cuts.json").read_text())
    assert cuts["cuts"] == [3.5, 7.25, 12.0] and cuts["cuts_per_minute"] == 3.0
    au = json.loads((a / "audio.json").read_text())["ffmpeg"]
    assert au["integrated_lufs"] == -14.2 and au["silence_count"] == 1
    assert json.loads((a / "ocr.json").read_text())["skipped"] == "research venv missing"
    assert all(n == 3 for _, n in yt._calls["vision"]) and yt._calls["vision"][0][0] == "qwen3-vl:8b"
    tl = json.loads((a / "timeline.json").read_text())
    assert {e["type"] for e in tl["events"]} >= {"speech", "cut", "shot", "silence"} and tl["per_minute"][0]["cuts"] == 3
    an = json.loads((a / "analysis.json").read_text())
    assert an["scores"]["style_copy"] == 5 and an["measured"]["cuts"] == 3 and an["_meta"]["provenance"] == "jaeger-youtube-research-v2"
    assert not (a / "audio22k.wav").exists() and not list(a.glob("lowres.*"))
    kb = yt._tmp / "research/kb"
    assert (kb / "index.md").is_file() and (kb / "video_index/aaaaaaaaaaa.md").is_file()
    tech = (kb / "production/jump-cut-every-sentence.md").read_text()
    assert "Stop scrolling" in tech and "[Watch on YouTube](https://www.youtube.com/watch?v=aaaaaaaaaaa)" in tech
    assert set(json.loads((kb / "processed_ids.json").read_text())) == {"aaaaaaaaaaa", "bbbbbbbbbbb"}
    assert (TID, "research") in yt._calls["stage"] and not j["drafts"]
    assert ("vlm", "qwen3-vl:8b") in yt._rm.acq and ("llm", "gemma4:12b") in yt._rm.acq and yt._rm.released


def test_phases_order_vlm_before_any_llm(yt):
    order = []
    v0, l0 = yt._deps["vision"], yt._deps["llm"]
    yt.bind(vision=lambda *a: (order.append("v"), v0(*a))[1], llm=lambda *a: (order.append("l"), l0(*a))[1])
    run_sync(yt)
    assert "l" in order and order.index("l") > max(i for i, x in enumerate(order) if x == "v")


def test_no_transcript_is_error_not_fake(yt):
    yt.bind(which=lambda n: None if n == "whisper-cli" else f"/usr/bin/{n}")
    run_sync(yt)
    v = next(v for v in yt.status(TID)["videos"] if v["id"] == "bbbbbbbbbbb")
    assert v["steps"]["transcript"]["status"] == "error" and v["steps"]["analysis"]["status"] == "blocked"
    assert not (vd(yt, "bbbbbbbbbbb") / "transcript.json").exists()


def test_resume_and_force(yt):
    run_sync(yt)
    n = len(yt._calls["llm"])
    yt.start(TID)
    assert len(yt._calls["llm"]) == n  # nothing redone: steps reuse files, style guide up to date
    yt.start(TID, force=["analysis"])
    assert len(yt._calls["llm"]) > n


def test_bad_json_retries_then_errors(yt):
    yt.bind(llm=lambda m, p: "not json")
    run_sync(yt)
    v = yt.status(TID)["videos"][0]
    assert v["steps"]["analysis"]["status"] == "error"


def test_import_hermes_note(yt, tmp_path):
    src = tmp_path / "hermes"; (src / "video_index").mkdir(parents=True)
    (src / "processed_ids.json").write_text(json.dumps(["aaaaaaaaaaa", "zzzzzzzzzzz"]))
    (src / "video_index/aaaaaaaaaaa.md").write_text("# One\n\n**Source:** [Watch on YouTube](https://youtube.com/watch?v=aaaaaaaaaaa)\n**Channel:** M\n**Transcript Source:** whisper\n\n## Transcript\n\nhi<00:00:00.320><c> there</c><00:00:07.000><c> friend</c>\n")
    yt.bind(hermes_sources=lambda: [src])
    yt.ingest({"playlist_url": URL, "start": False})
    st = yt.status(TID)["imported"]
    assert st["overlap"] == ["aaaaaaaaaaa"] and st["transcripts_reused"] == 1 and st["remaining"] == 1
    t = json.loads((vd(yt, "aaaaaaaaaaa") / "transcript.json").read_text())
    assert t["provenance"] == "imported-from-hermes" and len(t["segments"]) == 2
    assert "zzzzzzzzzzz" in json.loads((yt._tmp / "research/kb/processed_ids.json").read_text())


def test_enforce_seo_and_draft_only_on_request(yt):
    run_sync(yt)
    assert not yt.status(TID)["drafts"]
    out = yt.draft(TID, {"topic": "robot arm"})["draft"]
    assert out["titles"] == ["Short title"] and out["chapters"] == ["0:00 Hook", "0:10 Build"] and out["tags"] == ["a", "b"]
    assert any("hype" in x for x in out["seo_check"]) and out["_meta"]["published"] is False


def test_api_listing_and_fallback(yt):
    pages = {"playlists": {"items": [{"snippet": {"title": "Ares", "channelTitle": "M"}, "contentDetails": {"itemCount": 2}}]},
             "playlistItems": {"items": [{"snippet": {"title": "One", "position": 0}, "contentDetails": {"videoId": "aaaaaaaaaaa"}}]},
             "videos": {"items": [{"id": "aaaaaaaaaaa", "contentDetails": {"duration": "PT1M5S"}}]}}
    yt.bind(api_key=lambda: "k", http=lambda u: pages[u.split("/v3/")[1].split("?")[0]])
    r = yt.list_playlist("PLabcdefghij12345", 40)
    assert r["listing"] == "youtube_data_api" and r["entries"][0]["duration"] == 65
    yt.bind(http=lambda u: (_ for _ in ()).throw(OSError("x")))
    assert yt.list_playlist("PLabcdefghij12345", 40)["listing"] == "yt-dlp"


def test_poll_new_adds_only_unseen(yt):
    yt.ingest({"playlist_url": URL, "start": False, "max_videos": 1})
    yt.start = lambda tid, **k: None
    yt._update(TID, lambda j: j.update(max_videos=5))
    assert yt.poll_new(TID)["added"] == ["bbbbbbbbbbb"]
    assert not any("remove" in " ".join(c) for c in yt._deps["run"].cmds)


def test_frame_file_rejects_traversal(yt):
    for bad in ["../job.json", "f01.png", "seq/../x.jpg"]:
        with pytest.raises(yt.YtError):
            yt.frame_file(TID, "aaaaaaaaaaa", bad)


def test_slug_word_boundary(yt):
    s = yt.slug("word " * 40)
    assert len(s) <= 80 and not s.endswith("-") and s.endswith("word")
