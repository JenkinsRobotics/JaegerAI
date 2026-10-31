"""YouTube Research pipeline (WebUI-owned, server-side jobs).

Flow for one playlist (one pipeline task):
  ingest   playlist URL → yt-dlp flat listing → job.json, pipeline task at stage "research"
  per video (resumable steps, each writes its own file and is skipped when that file exists):
    meta        yt-dlp -J (no download)                         → meta.json
    transcript  YouTube captions (manual, else auto) via yt-dlp  → transcript.json
                fallback: local whisper.cpp (whisper-cli + ggml model) on the audio
    frames      ffmpeg samples N stills from a low-res download  → frames/*.jpg, frames.json
    frame_notes local Ollama vision model describes each still   → frame_notes.json (skipped if none)
    analysis    provider layer (Ollama local/cloud or cli:<p>:<m>) → analysis.json
  style guide   combines every analysis → style_guide.json + .md, a Document, attached to the task
  draft         style guide + topic → script, shot list, titles, thumbnail ideas → drafts/, attached

Nothing is uploaded or published. Files live under <state>/research/youtube/<task>/<video>/.
Dependencies (state root, LLM, pipeline, documents) are injected with bind() so tests can mock them.
"""
from __future__ import annotations

import base64
import json
import re
import shutil
import subprocess
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import parse_qs, urlparse

STEPS = ("meta", "transcript", "frames", "frame_notes", "analysis")
DEFAULT_MODEL = "gemma4:12b"
VISION_MODELS = ("minicpm-v", "llava", "qwen2.5vl", "llama3.2-vision", "gemma3")
N_FRAMES = 6
VIDEO_WORKERS = 2
_LIST = re.compile(r"^[A-Za-z0-9_-]{10,64}$")
_VID = re.compile(r"^[A-Za-z0-9_-]{11}$")

_deps: dict = {}
_locks: dict[str, threading.Lock] = {}
_running: dict[str, dict] = {}
_glock = threading.Lock()
_llm_gate = threading.Semaphore(1)  # one model call at a time (local GPU / CLI quota)


class YtError(Exception):
    def __init__(self, status: int, message: str, **extra):
        super().__init__(message)
        self.status, self.extra = status, extra


def bind(**deps) -> None:
    """state_root() -> Path; llm(model, prompt) -> str; vision(model, prompt, b64) -> str;
    ollama_models() -> [names]; set_stage(tid, body); attach(tid, body); get_record(tid)|None;
    save_doc(id|None, body) -> doc; run(cmd, timeout) -> CompletedProcess (default subprocess)."""
    _deps.update(deps)


def _d(name):
    return _deps[name]


def _run(cmd: list[str], timeout: float = 600) -> subprocess.CompletedProcess:
    r = _deps.get("run")
    if r:
        return r(cmd, timeout)
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)


def _which(name: str) -> str | None:
    w = _deps.get("which")
    return w(name) if w else shutil.which(name)


# ── tools ────────────────────────────────────────────────────────────

def _whisper_model() -> Path | None:
    for p in (Path.home() / ".whisper", Path("/opt/homebrew/share/whisper-cpp")):
        for name in ("ggml-base.en.bin", "ggml-small.en.bin", "ggml-base.bin", "ggml-small.bin", "ggml-medium.en.bin"):
            if (p / name).is_file():
                return p / name
    return None


def tools() -> dict:
    try:
        models = list(_d("ollama_models")())
    except Exception:  # noqa: BLE001
        models = []
    vision = next((m for m in models if m.split(":")[0] in VISION_MODELS), None)
    wm = _whisper_model()
    return {
        "yt_dlp": bool(_which("yt-dlp")), "ffmpeg": bool(_which("ffmpeg")),
        "whisper_cpp": bool(_which("whisper-cli") and wm), "whisper_model": wm.name if wm else None,
        "ollama": bool(models), "vision_model": vision, "default_model": DEFAULT_MODEL if DEFAULT_MODEL in models else (models[0] if models else None),
    }


# ── storage ──────────────────────────────────────────────────────────

def _safe(tid: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", tid)


def _root() -> Path:
    return Path(_d("state_root")()) / "research" / "youtube"


def _tdir(tid: str) -> Path:
    return _root() / _safe(tid)


def _rj(p: Path, default=None):
    try:
        return json.loads(p.read_text("utf-8"))
    except (OSError, ValueError):
        return default


def _wj(p: Path, data) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), "utf-8")
    tmp.replace(p)


def _lock(tid: str) -> threading.Lock:
    with _glock:
        return _locks.setdefault(tid, threading.Lock())


def _job(tid: str) -> dict:
    j = _rj(_tdir(tid) / "job.json")
    if not isinstance(j, dict):
        raise YtError(404, "no YouTube research job for this task")
    return j


def _update(tid: str, fn) -> dict:
    with _lock(tid):
        j = _job(tid)
        fn(j)
        j["updated_at"] = time.time()
        _wj(_tdir(tid) / "job.json", j)
        return j


def _set_step(tid: str, vid: str, step: str, status: str, error: str | None = None, **extra) -> None:
    def f(j):
        for v in j["videos"]:
            if v["id"] == vid:
                v["steps"][step] = {"status": status, "error": error, "at": time.time(), **extra}
    _update(tid, f)


# ── ingest ───────────────────────────────────────────────────────────

def playlist_id(url: str) -> str:
    u = urlparse(str(url).strip())
    if u.scheme != "https" or u.hostname not in ("www.youtube.com", "youtube.com", "m.youtube.com", "music.youtube.com"):
        raise YtError(400, "playlist_url must be an https://www.youtube.com/… URL with a list= parameter")
    lid = (parse_qs(u.query).get("list") or [""])[0]
    if not _LIST.match(lid):
        raise YtError(400, "playlist_url has no valid list= id")
    return lid


def ingest(body: dict) -> dict:
    if not _which("yt-dlp"):
        raise YtError(503, "yt-dlp is not installed")
    lid = playlist_id(body.get("playlist_url", ""))
    url = f"https://www.youtube.com/playlist?list={lid}"
    tid = str(body.get("task_id") or f"yt:{lid}")
    if not re.match(r"^[A-Za-z0-9][A-Za-z0-9:._-]{0,127}$", tid):
        raise YtError(400, "invalid task_id")
    max_videos = max(1, min(int(body.get("max_videos") or 25), 200))
    model = str(body.get("model") or tools()["default_model"] or DEFAULT_MODEL)
    existing = _rj(_tdir(tid) / "job.json")
    if isinstance(existing, dict):  # idempotent: same task → same job; just (re)start it
        if body.get("model"):
            _update(tid, lambda j: j.update(model=model))
        start(tid)
        return status(tid)
    r = _run(["yt-dlp", "--flat-playlist", "-J", "--no-warnings", "--playlist-end", str(max_videos), url], timeout=180)
    if r.returncode != 0:
        raise YtError(502, f"yt-dlp could not read the playlist: {(r.stderr or '').strip()[-300:]}")
    data = json.loads(r.stdout)
    videos = []
    for e in (data.get("entries") or [])[:max_videos]:
        vid = e.get("id")
        if not vid or not _VID.match(vid) or e.get("title") in ("[Private video]", "[Deleted video]"):
            continue
        videos.append({"id": vid, "title": e.get("title"), "duration": e.get("duration"), "channel": e.get("channel") or e.get("uploader"),
                       "url": f"https://www.youtube.com/watch?v={vid}", "steps": {s: {"status": "pending"} for s in STEPS}})
    if not videos:
        raise YtError(422, "the playlist has no public videos")
    job = {"task_id": tid, "playlist_id": lid, "playlist_url": url, "playlist_title": data.get("title"), "channel": data.get("channel") or data.get("uploader"),
           "model": model, "created_at": time.time(), "updated_at": time.time(), "state": "queued", "videos": videos,
           "style_guide": {"status": "pending"}, "drafts": []}
    _wj(_tdir(tid) / "job.json", job)
    rec = _d("get_record")(tid)
    if not rec or rec.get("stage") in (None, "intake"):
        _d("set_stage")(tid, {"stage": "research", "note": "YouTube research ingest"})
    try:
        _d("attach")(tid, {"kind": "source", "ref": url, "label": f"YouTube playlist: {data.get('title') or lid}"})
    except Exception:  # noqa: BLE001 — already attached
        pass
    start(tid)
    return status(tid)


# ── per-video steps ──────────────────────────────────────────────────

def _vdir(tid: str, vid: str) -> Path:
    return _tdir(tid) / vid


def step_meta(tid: str, v: dict) -> dict:
    r = _run(["yt-dlp", "-J", "--skip-download", "--no-warnings", "--no-playlist", v["url"]], timeout=180)
    if r.returncode != 0:
        raise RuntimeError(f"yt-dlp metadata failed: {(r.stderr or '').strip()[-300:]}")
    d = json.loads(r.stdout)
    keep = {k: d.get(k) for k in ("id", "title", "duration", "upload_date", "view_count", "like_count", "comment_count", "channel", "channel_follower_count", "tags", "categories", "chapters", "thumbnail", "language")}
    keep["description"] = (d.get("description") or "")[:5000]
    keep["has_captions"] = bool(d.get("subtitles")); keep["has_auto_captions"] = bool(d.get("automatic_captions"))
    _wj(_vdir(tid, v["id"]) / "meta.json", keep)
    return {}


_TS = re.compile(r"(\d+):(\d{2}):(\d{2})[.,](\d{3})\s+-->")


def parse_vtt(text: str) -> list[dict]:
    """WebVTT → [{start, text}], de-duplicating YouTube auto-caption roll-up lines."""
    segs, cur, seen_last = [], None, ""
    for line in text.splitlines():
        m = _TS.match(line.strip())
        if m:
            h, mi, s, ms = map(int, m.groups()); cur = h * 3600 + mi * 60 + s + ms / 1000; continue
        if cur is None or not line.strip() or line.startswith(("WEBVTT", "Kind:", "Language:", "NOTE")):
            continue
        clean = re.sub(r"<[^>]+>", "", line).replace("&amp;", "&").replace("&gt;", ">").replace("&lt;", "<").replace("&nbsp;", " ").strip()
        if not clean or clean == seen_last:
            continue
        seen_last = clean
        segs.append({"start": round(cur, 2), "text": clean})
    return segs


def step_transcript(tid: str, v: dict) -> dict:
    d = _vdir(tid, v["id"]); d.mkdir(parents=True, exist_ok=True)
    for old in d.glob("subs*.vtt"):
        old.unlink()
    r = _run(["yt-dlp", "--skip-download", "--no-warnings", "--no-playlist", "--write-subs", "--write-auto-subs", "--sub-langs", "en,en-US,en-GB,en.*",
              "--sub-format", "vtt", "-o", str(d / "subs.%(ext)s"), v["url"]], timeout=180)
    vtts = sorted(d.glob("subs*.vtt"), key=lambda p: (".en." not in p.name, len(p.name)))
    if vtts:
        segs = parse_vtt(vtts[0].read_text("utf-8", errors="replace"))
        if segs:
            meta = _rj(d / "meta.json", {}) or {}
            src = "youtube_captions" if meta.get("has_captions") else "youtube_auto_captions"
            _wj(d / "transcript.json", {"source": src, "file": vtts[0].name, "segments": segs, "text": " ".join(s["text"] for s in segs)})
            return {"source": src}
    wm = _whisper_model()
    if not (_which("whisper-cli") and wm and _which("ffmpeg")):
        raise RuntimeError("no English captions on YouTube and local whisper.cpp/ffmpeg unavailable" + (f" (yt-dlp: {(r.stderr or '').strip()[-200:]})" if r.returncode else ""))
    a = _run(["yt-dlp", "-f", "bestaudio/best", "--no-playlist", "--no-warnings", "-o", str(d / "audio.%(ext)s"), v["url"]], timeout=900)
    src_audio = next(iter(sorted(d.glob("audio.*"))), None)
    if a.returncode != 0 or not src_audio:
        raise RuntimeError(f"audio download failed: {(a.stderr or '').strip()[-200:]}")
    wav = d / "audio16k.wav"
    c = _run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src_audio), "-ar", "16000", "-ac", "1", str(wav)], timeout=900)
    if c.returncode != 0:
        raise RuntimeError(f"ffmpeg audio conversion failed: {(c.stderr or '').strip()[-200:]}")
    w = _run(["whisper-cli", "-m", str(wm), "-f", str(wav), "-otxt", "-of", str(d / "whisper"), "-np"], timeout=3600)
    txt = (d / "whisper.txt")
    for p in (src_audio, wav):
        p.unlink(missing_ok=True)
    if w.returncode != 0 or not txt.is_file():
        raise RuntimeError(f"whisper.cpp failed: {(w.stderr or '').strip()[-200:]}")
    text = " ".join(txt.read_text("utf-8", errors="replace").split())
    why = "no English captions" if r.returncode == 0 else f"captions download failed: {(r.stderr or '').strip().splitlines()[-1][:200] if (r.stderr or '').strip() else 'unknown'}"
    _wj(d / "transcript.json", {"source": f"whisper.cpp ({wm.name})", "fallback_reason": why, "segments": [], "text": text})
    return {"source": "whisper.cpp"}


def step_frames(tid: str, v: dict) -> dict:
    if not _which("ffmpeg"):
        return {"skipped": "ffmpeg not installed"}
    d = _vdir(tid, v["id"]); fd = d / "frames"; fd.mkdir(parents=True, exist_ok=True)
    dur = (_rj(d / "meta.json", {}) or {}).get("duration") or v.get("duration") or 0
    if not dur:
        return {"skipped": "unknown duration"}
    r = _run(["yt-dlp", "-f", "worst[ext=mp4][height>=240]/worst[ext=mp4]/worst", "--no-playlist", "--no-warnings", "-o", str(d / "lowres.%(ext)s"), v["url"]], timeout=900)
    vf = next(iter(sorted(d.glob("lowres.*"))), None)
    if r.returncode != 0 or not vf:
        raise RuntimeError(f"low-res download failed: {(r.stderr or '').strip()[-200:]}")
    frames = []
    try:
        for i in range(N_FRAMES):
            t = round(dur * (i + 0.5) / N_FRAMES, 2)
            out = fd / f"f{i:02d}.jpg"
            c = _run(["ffmpeg", "-y", "-loglevel", "error", "-ss", str(t), "-i", str(vf), "-frames:v", "1", "-vf", "scale=480:-2", str(out)], timeout=120)
            if c.returncode == 0 and out.is_file():
                frames.append({"file": f"frames/{out.name}", "t": t})
    finally:
        vf.unlink(missing_ok=True)  # keep stills only
    if not frames:
        raise RuntimeError("ffmpeg produced no frames")
    _wj(d / "frames.json", frames)
    return {"count": len(frames)}


def step_frame_notes(tid: str, v: dict) -> dict:
    d = _vdir(tid, v["id"])
    frames = _rj(d / "frames.json")
    vm = tools()["vision_model"]
    if not frames:
        _wj(d / "frame_notes.json", {"skipped": "no frames", "notes": []}); return {"skipped": "no frames"}
    if not vm:
        _wj(d / "frame_notes.json", {"skipped": "no local vision model in Ollama", "notes": []}); return {"skipped": "no vision model"}
    notes = []
    for f in frames:
        b64 = base64.b64encode((d / f["file"]).read_bytes()).decode()
        with _llm_gate:
            txt = _d("vision")(vm, "Describe this YouTube video frame for a content-style analyst in 1-2 sentences: shot type (talking head, b-roll, screen recording, graphic), on-screen text, setting, colours, branding.", b64)
        notes.append({"t": f["t"], "note": " ".join(str(txt).split())[:600]})
    _wj(d / "frame_notes.json", {"model": vm, "notes": notes})
    return {"model": vm}


def extract_json(text: str):
    t = str(text).strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t)
    try:
        return json.loads(t)
    except ValueError:
        pass
    a, b = t.find("{"), t.rfind("}")
    if a >= 0 and b > a:
        try:
            return json.loads(t[a:b + 1])
        except ValueError:
            pass
    raise ValueError("model did not return JSON")


def _ask_json(model: str, prompt: str) -> dict:
    last = None
    for attempt in range(2):
        with _llm_gate:
            out = _d("llm")(model, prompt if attempt == 0 else prompt + "\n\nReturn ONLY a single valid JSON object. No prose, no code fences.")
        try:
            j = extract_json(out)
            if isinstance(j, dict):
                return j
        except ValueError as e:
            last = e
    raise RuntimeError(f"{model}: {last or 'non-object JSON'}")


def _clip(text: str, n: int) -> str:
    return text if len(text) <= n else text[: int(n * 0.75)] + "\n[…]\n" + text[-int(n * 0.25):]


ANALYSIS_KEYS = ("summary", "hook", "structure", "pacing", "editing", "tone", "visuals", "calls_to_action", "title_pattern")


def analysis_prompt(meta: dict, transcript: dict, frame_notes: dict) -> str:
    segs = transcript.get("segments") or []
    timed = "\n".join(f"[{int(s['start'])//60}:{int(s['start'])%60:02d}] {s['text']}" for s in segs) if segs else transcript.get("text", "")
    frames = "\n".join(f"- {n['t']:.0f}s: {n['note']}" for n in frame_notes.get("notes", [])) or "(no frame notes)"
    chapters = ", ".join(f"{c.get('title')}@{int(c.get('start_time', 0))}s" for c in (meta.get("chapters") or [])[:30]) or "none"
    return f"""You are analysing one YouTube video to learn the creator's content style. Use ONLY the data below; if something is unknown say "unknown".
Return a JSON object with exactly these keys:
 "summary": string (2 sentences),
 "hook": {{"first_15s": string, "technique": string, "strength": 1-5}},
 "structure": {{"segments": [{{"label": string, "start_s": number, "purpose": string}}], "pattern": string}},
 "pacing": {{"words_per_minute": number or null, "notes": string}},
 "editing": {{"style": string, "devices": [string]}},
 "tone": {{"voice": string, "persona": string, "vocabulary": [string]}},
 "visuals": {{"shot_types": [string], "on_screen_text": string, "notes": string}},
 "calls_to_action": [{{"at_s": number or null, "text": string}}],
 "title_pattern": string

TITLE: {meta.get('title')}
CHANNEL: {meta.get('channel')}
DURATION_S: {meta.get('duration')}
CHAPTERS: {chapters}
DESCRIPTION: {_clip(meta.get('description') or '', 1200)}
FRAME NOTES:
{_clip(frames, 1500)}
TRANSCRIPT ({transcript.get('source')}):
{_clip(timed, 11000)}"""


def step_analysis(tid: str, v: dict, model: str) -> dict:
    d = _vdir(tid, v["id"])
    tr = _rj(d / "transcript.json")
    if not tr:
        raise RuntimeError("no transcript")
    meta = _rj(d / "meta.json", {}) or {"title": v.get("title"), "duration": v.get("duration")}
    fn = _rj(d / "frame_notes.json", {}) or {}
    a = _ask_json(model, analysis_prompt(meta, tr, fn))
    words = len(tr.get("text", "").split())
    if meta.get("duration"):
        a.setdefault("pacing", {})
        if isinstance(a["pacing"], dict):
            a["pacing"]["measured_words_per_minute"] = round(words / (meta["duration"] / 60), 1)  # measured, not model-guessed
    a["_meta"] = {"model": model, "video_id": v["id"], "title": meta.get("title"), "transcript_source": tr.get("source"), "frame_notes": bool(fn.get("notes")), "at": time.time()}
    _wj(d / "analysis.json", a)
    return {"model": model}


_OUT = {"meta": "meta.json", "transcript": "transcript.json", "frames": "frames.json", "frame_notes": "frame_notes.json", "analysis": "analysis.json"}


def _video_worker(tid: str, v: dict, model: str, force: set[str], stop: threading.Event) -> None:
    for step in STEPS:
        if stop.is_set():
            return
        out = _vdir(tid, v["id"]) / _OUT[step]
        if out.is_file() and step not in force:
            if v["steps"].get(step, {}).get("status") not in ("done", "skipped"):
                prev = _rj(out, {})
                skipped = isinstance(prev, dict) and prev.get("skipped")
                _set_step(tid, v["id"], step, "skipped" if skipped else "done", reused=True, **({"reason": skipped} if skipped else {}))
            continue
        _set_step(tid, v["id"], step, "running")
        try:
            fn = {"meta": step_meta, "transcript": step_transcript, "frames": step_frames, "frame_notes": step_frame_notes}.get(step)
            info = fn(tid, v) if fn else step_analysis(tid, v, model)
            _set_step(tid, v["id"], step, "skipped" if info.get("skipped") else "done", **({"reason": info["skipped"]} if info.get("skipped") else {k: x for k, x in info.items()}))
        except Exception as exc:  # noqa: BLE001 — recorded per video; later steps that need it are blocked
            _set_step(tid, v["id"], step, "error", str(exc)[:500])
            if step in ("meta", "transcript", "analysis"):
                for rest in STEPS[STEPS.index(step) + 1:]:
                    _set_step(tid, v["id"], rest, "blocked", f"needs {step}")
                return
            # frames/frame_notes failing doesn't stop the analysis
            if step == "frames":
                _wj(_vdir(tid, v["id"]) / "frame_notes.json", {"skipped": "frames failed", "notes": []})


def _job_thread(tid: str, force: set[str], with_style: bool, stop: threading.Event) -> None:
    try:
        _update(tid, lambda j: j.update(state="running", error=None))
        j = _job(tid)
        with ThreadPoolExecutor(max_workers=VIDEO_WORKERS) as ex:
            for f in [ex.submit(_video_worker, tid, v, j["model"], force, stop) for v in j["videos"]]:
                f.result()
        if stop.is_set():
            _update(tid, lambda j: j.update(state="cancelled")); return
        if with_style:
            try:
                build_style_guide(tid, force="style_guide" in force)
            except Exception as exc:  # noqa: BLE001
                _update(tid, lambda j: j["style_guide"].update(status="error", error=str(exc)[:500]))
        j = _job(tid)
        errs = sum(1 for v in j["videos"] if any(s.get("status") == "error" for s in v["steps"].values()))
        _update(tid, lambda j: j.update(state="done" if not errs and j["style_guide"].get("status") == "done" else "done_with_errors"))
    except Exception as exc:  # noqa: BLE001
        _update(tid, lambda j: j.update(state="error", error=str(exc)[:500]))
    finally:
        with _glock:
            _running.pop(tid, None)


def start(tid: str, force: list[str] | None = None, style_guide: bool = True, wait: bool = False) -> dict:
    _job(tid)
    with _glock:
        if tid in _running:
            return {"started": False, "reason": "already running"}
        stop = threading.Event()
        t = threading.Thread(target=_job_thread, args=(tid, set(force or []), style_guide, stop), daemon=True, name=f"yt-{tid}")
        _running[tid] = {"thread": t, "stop": stop}
    t.start()
    if wait:
        t.join()
    return {"started": True}


def cancel(tid: str) -> dict:
    with _glock:
        r = _running.get(tid)
    if r:
        r["stop"].set()
    return {"cancelling": bool(r)}


def status(tid: str) -> dict:
    j = _job(tid)
    with _glock:
        running = tid in _running
    if not running and j.get("state") in ("running", "queued"):
        j["state"] = "interrupted"  # server restarted mid-job: POST …/run resumes from the files on disk
    total = len(j["videos"]) * len(STEPS)
    finished = sum(1 for v in j["videos"] for s in v["steps"].values() if s.get("status") in ("done", "skipped", "error", "blocked"))
    j["running"] = running
    j["progress"] = {"steps_finished": finished, "steps_total": total,
                     "videos_analysed": sum(1 for v in j["videos"] if v["steps"]["analysis"].get("status") == "done"),
                     "videos_with_errors": sum(1 for v in j["videos"] if any(s.get("status") == "error" for s in v["steps"].values())),
                     "videos": len(j["videos"])}
    return j


def list_jobs() -> list[dict]:
    out = []
    root = _root()
    for p in sorted(root.glob("*/job.json")) if root.is_dir() else []:
        j = _rj(p)
        if isinstance(j, dict):
            s = status(j["task_id"])
            out.append({k: s.get(k) for k in ("task_id", "playlist_title", "playlist_url", "state", "running", "progress", "updated_at")} | {"style_guide": s["style_guide"].get("status")})
    return out


# ── style guide ──────────────────────────────────────────────────────

GUIDE_KEYS = ("voice_and_tone", "hooks", "structure_template", "pacing", "editing", "visuals", "titles_and_thumbnails", "calls_to_action", "dos", "donts", "example_lines")


def style_prompt(analyses: list[dict], channel: str | None) -> str:
    compact = json.dumps([{k: a.get(k) for k in ANALYSIS_KEYS} | {"title": a["_meta"]["title"], "measured_wpm": (a.get("pacing") or {}).get("measured_words_per_minute") if isinstance(a.get("pacing"), dict) else None} for a in analyses], ensure_ascii=False)
    return f"""Below are per-video analyses of {len(analyses)} videos from the channel "{channel or 'unknown'}".
Write a reusable STYLE GUIDE so a writer can produce new videos in exactly this style. Generalise across videos; mention only patterns supported by the analyses.
Return a JSON object with keys:
 "voice_and_tone": string, "hooks": {{"pattern": string, "templates": [string]}},
 "structure_template": [{{"section": string, "share_pct": number, "purpose": string}}],
 "pacing": {{"target_wpm": number or null, "notes": string}}, "editing": [string], "visuals": [string],
 "titles_and_thumbnails": {{"title_formulas": [string], "thumbnail_notes": string}},
 "calls_to_action": [string], "dos": [string], "donts": [string], "example_lines": [string]
ANALYSES:
{_clip(compact, 17000)}"""


def render_guide_md(g: dict, job: dict, used: list[dict]) -> str:
    L = [f"# Style guide — {job.get('playlist_title') or job['playlist_id']}", "",
         f"Learned from {len(used)} video(s) of {job.get('channel') or 'this channel'} · model `{g['_meta']['model']}` · {time.strftime('%Y-%m-%d %H:%M', time.localtime(g['_meta']['at']))}", ""]
    def sec(title, val):
        if not val:
            return
        L.append(f"## {title}")
        if isinstance(val, str):
            L.append(val)
        elif isinstance(val, list):
            for x in val:
                L.append("- " + (", ".join(f"{k}: {v}" for k, v in x.items()) if isinstance(x, dict) else str(x)))
        elif isinstance(val, dict):
            for k, x in val.items():
                L.append(f"- **{k.replace('_', ' ')}**: " + ("; ".join(map(str, x)) if isinstance(x, list) else str(x)))
        L.append("")
    for k in GUIDE_KEYS:
        sec(k.replace("_", " ").capitalize(), g.get(k))
    L.append("## Sources")
    for a in used:
        L.append(f"- {a['_meta']['title']} (https://www.youtube.com/watch?v={a['_meta']['video_id']}) — transcript: {a['_meta']['transcript_source']}")
    return "\n".join(L) + "\n"


def build_style_guide(tid: str, force: bool = False, model: str | None = None) -> dict:
    j = _job(tid)
    td = _tdir(tid)
    if (td / "style_guide.json").is_file() and not force and j["style_guide"].get("status") == "done":
        return style_guide(tid)
    used = [a for v in j["videos"] if (a := _rj(td / v["id"] / "analysis.json"))]
    if not used:
        raise RuntimeError("no analysed videos yet")
    _update(tid, lambda x: x["style_guide"].update(status="running", error=None))
    m = model or j["model"]
    g = _ask_json(m, style_prompt(used, j.get("channel")))
    g["_meta"] = {"model": m, "videos": [a["_meta"]["video_id"] for a in used], "at": time.time()}
    md = render_guide_md(g, j, used)
    _wj(td / "style_guide.json", g)
    (td / "style_guide.md").write_text(md, "utf-8")
    doc = _d("save_doc")(j["style_guide"].get("document_id"), {"title": f"YouTube style guide — {j.get('playlist_title') or j['playlist_id']}", "body": md})
    if not j["style_guide"].get("document_id"):
        try:
            _d("attach")(tid, {"kind": "document", "ref": f"document:{doc['id']}", "label": "YouTube style guide"})
        except Exception:  # noqa: BLE001
            pass
    _update(tid, lambda x: x["style_guide"].update(status="done", error=None, document_id=doc["id"], videos=len(used), model=m, at=time.time()))
    return style_guide(tid)


def style_guide(tid: str) -> dict:
    td = _tdir(tid)
    g = _rj(td / "style_guide.json")
    if not g:
        raise YtError(404, "no style guide yet")
    return {"task_id": tid, "json": g, "markdown": (td / "style_guide.md").read_text("utf-8"), "document_id": _job(tid)["style_guide"].get("document_id")}


# ── Studio handoff ───────────────────────────────────────────────────

def draft(tid: str, body: dict) -> dict:
    topic = str(body.get("topic", "")).strip()
    if not topic or len(topic) > 500:
        raise YtError(400, "topic (1-500 chars) is required")
    g = style_guide(tid)["json"]
    j = _job(tid)
    m = str(body.get("model") or j["model"])
    guide = {k: v for k, v in g.items() if not k.startswith("_")}
    prompt = f"""Using this STYLE GUIDE, draft a new YouTube video on the topic: "{topic}".
Match the guide's hook pattern, structure, pacing, tone and calls to action. This is a draft for the creator to review; it will not be published.
Return a JSON object with keys:
 "titles": [5 strings], "hook": string (the first 15 seconds, spoken),
 "script": [{{"section": string, "est_seconds": number, "voiceover": string}}],
 "shot_list": [{{"shot": number, "section": string, "visual": string, "on_screen_text": string, "est_seconds": number}}],
 "thumbnail_ideas": [{{"concept": string, "text": string, "composition": string}}],
 "call_to_action": string, "description": string
STYLE GUIDE:
{_clip(json.dumps(guide, ensure_ascii=False), 14000)}"""
    out = _ask_json(m, prompt)
    did = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:4]
    out["_meta"] = {"id": did, "topic": topic, "model": m, "at": time.time(), "style_guide_at": g["_meta"]["at"], "published": False}
    td = _tdir(tid) / "drafts"
    _wj(td / f"{did}.json", out)
    md = render_draft_md(out)
    (td / f"{did}.md").write_text(md, "utf-8")
    doc = _d("save_doc")(None, {"title": f"Draft — {topic}", "body": md})
    try:
        _d("attach")(tid, {"kind": "deliverable", "ref": f"document:{doc['id']}", "label": f"Draft: {topic}"})
    except Exception:  # noqa: BLE001
        pass
    _update(tid, lambda x: x["drafts"].append({"id": did, "topic": topic, "document_id": doc["id"], "model": m, "at": time.time()}))
    return {"task_id": tid, "draft": out, "markdown": md, "document_id": doc["id"]}


def render_draft_md(d: dict) -> str:
    L = [f"# Draft — {d['_meta']['topic']}", "", "_Draft for review. Not published._", "", "## Title options"]
    L += [f"{i}. {t}" for i, t in enumerate(d.get("titles") or [], 1)]
    L += ["", "## Hook", str(d.get("hook", "")), "", "## Script"]
    for s in d.get("script") or []:
        if isinstance(s, dict):
            L += [f"### {s.get('section')} (~{s.get('est_seconds')}s)", str(s.get("voiceover", "")), ""]
    L += ["## Shot list", "| # | Section | Visual | On-screen text | s |", "|---|---|---|---|---|"]
    for s in d.get("shot_list") or []:
        if isinstance(s, dict):
            L.append(f"| {s.get('shot')} | {s.get('section')} | {s.get('visual')} | {s.get('on_screen_text')} | {s.get('est_seconds')} |")
    L += ["", "## Thumbnail ideas"]
    for t in d.get("thumbnail_ideas") or []:
        L.append("- " + (f"**{t.get('concept')}** — text “{t.get('text')}”; {t.get('composition')}" if isinstance(t, dict) else str(t)))
    L += ["", "## Call to action", str(d.get("call_to_action", "")), "", "## Description", str(d.get("description", ""))]
    return "\n".join(L) + "\n"


def frame_file(tid: str, vid: str, name: str) -> Path:
    if not _VID.match(vid) or not re.match(r"^f\d{2}\.jpg$", name):
        raise YtError(404, "no such frame")
    p = _vdir(tid, vid) / "frames" / name
    if not p.is_file():
        raise YtError(404, "no such frame")
    return p
