"""YouTube Research pipeline v2 (on-device; WebUI-owned server-side jobs).

One playlist = one pipeline task (id "yt:<playlist>"). Work runs in PHASES across all videos so only
one large model is resident at a time (resource_manager decides when each step may run):
  phase 1: meta -> transcript -> frames (scene cuts) -> ocr -> audio
     transcript: reuse existing/imported -> youtube-transcript-api -> yt-dlp captions -> whisper.cpp (-ojf words)
     frames: ffmpeg scene-change cuts on a low-res copy, <=60 stills, 3-still sequences at <=SEQ_CUTS cuts
     ocr: Apple Vision (ocrmac). audio: ffmpeg silencedetect + EBU R128, librosa tempo/beats/loudness.
  phase 2: shot_notes - local video-language model on each cut sequence
  phase 3: timeline (deterministic merge) -> analysis (chunked content notes, style pass, scoring + 7 areas)
  phase 4: style guide (md + json + Document) and the Obsidian KB at <state>/research/kb
Each step writes its own file and is skipped when it exists (resume); errors are per video.
Nothing is uploaded, published, removed from the playlist or messaged anywhere.
"""
from __future__ import annotations

import base64
import contextlib
import json
import re
import shutil
import subprocess
import threading
import time
import urllib.parse
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import parse_qs, urlparse

STEPS = ("meta", "transcript", "frames", "ocr", "audio", "shot_notes", "timeline", "analysis")
PHASES = (("meta", "transcript", "frames", "ocr", "audio"), ("shot_notes",), ("timeline", "analysis"))
DEFAULT_MODEL = "gemma4:12b"
VLM_PREFS = ("qwen3-vl:8b", "qwen2.5vl:7b", "minicpm-v:latest")
MAX_FRAMES = 60
SEQ_CUTS = 12
SCENE_THRESHOLD = 0.3
IO_WORKERS = 3
AREAS = ("engineering", "production", "visuals", "sound", "hardware", "software", "narrative")
_LIST = re.compile(r"^[A-Za-z0-9_-]{10,64}$")
_VID = re.compile(r"^[A-Za-z0-9_-]{11}$")
TOOLS_DIR = Path(__file__).with_name("research_tools")

_deps: dict = {}
_locks: dict = {}
_running: dict = {}
_watchers: dict = {}
_paused: dict = {}
_glock = threading.Lock()


class YtError(Exception):
    def __init__(self, status: int, message: str, **extra):
        super().__init__(message)
        self.status, self.extra = status, extra


def bind(**deps) -> None:
    """state_root, llm(model, prompt), vision(model, prompt, [b64]), ollama_models(), set_stage, attach,
    get_record, save_doc; optional: run(cmd, timeout), which(name), rm, api_key(), http(url), research_python, cleanup."""
    _deps.update(deps)


def _d(name):
    return _deps[name]


def _run(cmd, timeout: float = 600) -> subprocess.CompletedProcess:
    r = _deps.get("run")
    if r:
        return r(cmd, timeout)
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)


def _which(name: str):
    w = _deps.get("which")
    return w(name) if w else shutil.which(name)


def _rm_slot(kind: str, tid: str, model=None, priority: int = 5):
    rm = _deps.get("rm")
    return rm.acquire(kind, job=tid, priority=priority, model=model) if rm else contextlib.nullcontext({})


def research_python():
    """The isolated venv with librosa/ocrmac/youtube-transcript-api (repo/.venv-research)."""
    if "research_python" in _deps:
        return _deps["research_python"]
    for base in Path(__file__).resolve().parents:
        cand = base / ".venv-research" / "bin" / "python"
        if cand.is_file():
            return str(cand)
    return None


def _whisper_model():
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
    vlm = next((m for m in VLM_PREFS if m in models), None)
    wm = _whisper_model()
    py = research_python()
    return {"yt_dlp": bool(_which("yt-dlp")), "ffmpeg": bool(_which("ffmpeg")),
            "whisper_cpp": bool(_which("whisper-cli") and wm), "whisper_model": wm.name if wm else None,
            "research_venv": bool(py), "ocr": bool(py), "audio_features": bool(py), "transcript_api": bool(py),
            "youtube_data_api": bool(_api_key()), "ollama": bool(models), "video_model": vlm,
            "default_model": DEFAULT_MODEL if DEFAULT_MODEL in models else (models[0] if models else None)}


def _safe(tid: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", tid)


def _base() -> Path:
    return Path(_d("state_root")()) / "research"


def _root() -> Path:
    return _base() / "youtube"


def kb_root() -> Path:
    return _base() / "kb"


def _tdir(tid: str) -> Path:
    return _root() / _safe(tid)


def _vdir(tid: str, vid: str) -> Path:
    return _tdir(tid) / vid


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


def _lock(tid: str):
    with _glock:
        return _locks.setdefault(tid, threading.Lock())


def _job(tid: str) -> dict:
    j = _rj(_tdir(tid) / "job.json")
    if not isinstance(j, dict):
        raise YtError(404, "no YouTube research job for this task")
    for v in j["videos"]:
        for s in STEPS:
            v["steps"].setdefault(s, {"status": "pending"})
    return j


def _update(tid: str, fn) -> dict:
    with _lock(tid):
        j = _job(tid)
        fn(j)
        j["updated_at"] = time.time()
        _wj(_tdir(tid) / "job.json", j)
        return j


def _set_step(tid: str, vid: str, step: str, status: str, error=None, **extra) -> None:
    def f(j):
        for v in j["videos"]:
            if v["id"] == vid:
                v["steps"][step] = {"status": status, "error": error, "at": time.time(), **extra}
    _update(tid, f)


# -- playlist listing: YouTube Data API key if present, else yt-dlp --

def _api_key():
    f = _deps.get("api_key")
    if f:
        return f()
    p = Path(_d("state_root")()) / "secrets" / "youtube_api_key"
    try:
        return p.read_text().strip() or None
    except OSError:
        return None


def _http_json(url: str) -> dict:
    h = _deps.get("http")
    if h:
        return h(url)
    with urllib.request.urlopen(url, timeout=30) as r:
        return json.loads(r.read())


def _iso_dur(s):
    m = re.match(r"^P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?$", s or "")
    if not m:
        return None
    d, h, mi, se = (int(x or 0) for x in m.groups())
    return d * 86400 + h * 3600 + mi * 60 + se


def list_playlist(lid: str, limit: int) -> dict:
    key = _api_key()
    note = "no YouTube Data API key; used yt-dlp"
    if key:
        try:
            return _list_api(lid, limit, key)
        except Exception as exc:  # noqa: BLE001
            note = f"YouTube Data API failed ({type(exc).__name__}); used yt-dlp"
    out = _list_ytdlp(lid, limit)
    out["listing_note"] = note
    return out


def _list_api(lid: str, limit: int, key: str) -> dict:
    def q(path, **kw):
        return _http_json("https://www.googleapis.com/youtube/v3/" + path + "?" + urllib.parse.urlencode({**kw, "key": key}))
    meta = q("playlists", part="snippet,contentDetails", id=lid).get("items") or []
    if not meta:
        raise RuntimeError("playlist not visible to the API key")
    entries, token = [], None
    while len(entries) < limit:
        kw = {"pageToken": token} if token else {}
        r = q("playlistItems", part="snippet,contentDetails,status", playlistId=lid, maxResults=50, **kw)
        for it in r.get("items", []):
            sn = it.get("snippet", {})
            cd = it.get("contentDetails") or {}
            if sn.get("title") in ("Private video", "Deleted video") or (it.get("status") or {}).get("privacyStatus") == "private":
                continue
            entries.append({"id": cd.get("videoId"), "title": sn.get("title"), "channel": sn.get("videoOwnerChannelTitle"),
                            "position": sn.get("position"), "added_at": sn.get("publishedAt"), "published_at": cd.get("videoPublishedAt")})
        token = r.get("nextPageToken")
        if not token:
            break
    entries = [e for e in entries if e["id"] and _VID.match(e["id"])][:limit]
    for i in range(0, len(entries), 50):
        chunk = entries[i:i + 50]
        r = q("videos", part="contentDetails", id=",".join(e["id"] for e in chunk))
        dur = {it["id"]: _iso_dur((it.get("contentDetails") or {}).get("duration")) for it in r.get("items", [])}
        for e in chunk:
            e["duration"] = dur.get(e["id"])
    sn = meta[0].get("snippet", {})
    return {"title": sn.get("title"), "channel": sn.get("channelTitle"), "item_count": (meta[0].get("contentDetails") or {}).get("itemCount"),
            "entries": entries, "listing": "youtube_data_api"}


def _list_ytdlp(lid: str, limit: int) -> dict:
    url = f"https://www.youtube.com/playlist?list={lid}"
    r = _run(["yt-dlp", "--flat-playlist", "-J", "--no-warnings", "--playlist-end", str(limit), url], timeout=300)
    if r.returncode != 0:
        raise YtError(502, f"yt-dlp could not read the playlist: {(r.stderr or '').strip()[-300:]}")
    d = json.loads(r.stdout)
    ents = [{"id": e.get("id"), "title": e.get("title"), "duration": e.get("duration"), "channel": e.get("channel") or e.get("uploader")}
            for e in (d.get("entries") or []) if e.get("id") and _VID.match(e["id"]) and e.get("title") not in ("[Private video]", "[Deleted video]")]
    return {"title": d.get("title"), "channel": d.get("channel") or d.get("uploader"), "item_count": d.get("playlist_count"), "entries": ents[:limit], "listing": "yt-dlp"}


_CHAN = re.compile(r"^/(@[A-Za-z0-9._-]{2,100}|channel/UC[A-Za-z0-9_-]{22}|c/[A-Za-z0-9._-]+|user/[A-Za-z0-9._-]+)(/videos|/shorts|/streams|/featured)?/?$")


def resolve_list(url: str) -> str:
    """Playlist URL -> list id. Channel URL (@handle, /channel/UC..., /c/, /user/) -> its uploads playlist (UU...)."""
    u = urlparse(str(url).strip())
    if u.scheme == "https" and u.hostname in ("www.youtube.com", "youtube.com", "m.youtube.com") and not parse_qs(u.query).get("list"):
        m = _CHAN.match(u.path)
        if m:
            ch = m.group(1)
            if ch.startswith("channel/"):
                return "UU" + ch[len("channel/") + 2:]
            key = _api_key()
            if key and ch.startswith("@"):
                with contextlib.suppress(Exception):
                    it = _http_json("https://www.googleapis.com/youtube/v3/channels?" + urllib.parse.urlencode({"part": "contentDetails", "forHandle": ch, "key": key})).get("items") or []
                    if it:
                        return it[0]["contentDetails"]["relatedPlaylists"]["uploads"]
            r = _run(["yt-dlp", "--flat-playlist", "-J", "--no-warnings", "--playlist-end", "1", f"https://www.youtube.com/{ch}/videos"], timeout=120)
            with contextlib.suppress(ValueError):
                cid = json.loads(r.stdout or "{}").get("channel_id") or ""
                if cid.startswith("UC"):
                    return "UU" + cid[2:]
            raise YtError(422, "could not resolve the channel's uploads playlist")
    return playlist_id(url)


def playlist_id(url: str) -> str:
    u = urlparse(str(url).strip())
    if u.scheme != "https" or u.hostname not in ("www.youtube.com", "youtube.com", "m.youtube.com", "music.youtube.com"):
        raise YtError(400, "playlist_url must be an https://www.youtube.com/... URL with a list= parameter")
    lid = (parse_qs(u.query).get("list") or [""])[0]
    if not _LIST.match(lid):
        raise YtError(400, "playlist_url has no valid list= id")
    return lid


def _video(e: dict) -> dict:
    return {"id": e["id"], "title": e.get("title"), "duration": e.get("duration"), "channel": e.get("channel"),
            "url": f"https://www.youtube.com/watch?v={e['id']}", "position": e.get("position"), "steps": {s: {"status": "pending"} for s in STEPS}}


def ingest(body: dict) -> dict:
    lid = resolve_list(body.get("playlist_url") or body.get("url") or "")
    url = f"https://www.youtube.com/playlist?list={lid}"
    tid = str(body.get("task_id") or f"yt:{lid}")
    if not re.match(r"^[A-Za-z0-9][A-Za-z0-9:._-]{0,127}$", tid):
        raise YtError(400, "invalid task_id")
    max_videos = max(1, min(int(body.get("max_videos") or 40), 5000))
    t = tools()
    model = str(body.get("model") or t["default_model"] or DEFAULT_MODEL)
    vlm = body.get("video_model") or t["video_model"]
    if body.get("local_only", True) and any(re.search(r"(^|[-:])cloud\b", m or "") for m in (model, vlm)):
        raise YtError(400, "local_only: pick local models, not cloud ones")
    existing = _rj(_tdir(tid) / "job.json")
    if isinstance(existing, dict):
        if max_videos > len(existing["videos"]):
            pl = list_playlist(lid, max_videos)
            have = {v["id"] for v in existing["videos"]}
            add = [_video(e) for e in pl["entries"] if e["id"] not in have]
            _update(tid, lambda j: (j["videos"].extend(add), j.update(max_videos=max_videos, item_count=pl.get("item_count"))))
        _update(tid, lambda j: j.update(model=model, video_model=vlm))
        import_existing(tid)
        if body.get("start", True):
            start(tid)
        return status(tid)
    if not _api_key() and not _which("yt-dlp"):
        raise YtError(503, "neither a YouTube Data API key nor yt-dlp is available")
    pl = list_playlist(lid, max_videos)
    if not pl["entries"]:
        raise YtError(422, "the playlist has no public videos")
    job = {"task_id": tid, "playlist_id": lid, "playlist_url": url, "playlist_title": pl.get("title"), "channel": pl.get("channel"),
           "item_count": pl.get("item_count"), "listing": pl.get("listing"), "listing_note": pl.get("listing_note"), "max_videos": max_videos,
           "model": model, "video_model": vlm, "created_at": time.time(), "updated_at": time.time(), "state": "queued", "phase": None,
           "videos": [_video(e) for e in pl["entries"]], "style_guide": {"status": "pending"}, "kb": {"status": "pending"}, "drafts": []}
    _wj(_tdir(tid) / "job.json", job)
    rec = _d("get_record")(tid)
    if not rec or rec.get("stage") in (None, "intake"):
        _d("set_stage")(tid, {"stage": "research", "note": "YouTube research ingest"})
    with contextlib.suppress(Exception):
        _d("attach")(tid, {"kind": "source", "ref": url, "label": f"YouTube playlist: {pl.get('title') or lid}"})
    import_existing(tid)
    if body.get("start", True):
        start(tid)
    return status(tid)


# -- phase 1 steps --

CLIENTS = (None, "mweb", "web_safari")


def _ytdlp_dl(fmt: str, out_tmpl: str, url: str, glob_dir: Path, glob_pat: str, timeout: float):
    """yt-dlp media download; on 403/format errors retry with other player clients (YouTube often 403s the default)."""
    errs = []
    for c in CLIENTS:
        for f in glob_dir.glob(glob_pat):
            f.unlink(missing_ok=True)
        cmd = ["yt-dlp", "-f", fmt, "--no-playlist", "--no-warnings"] + (["--extractor-args", f"youtube:player_client={c}"] if c else []) + ["-o", out_tmpl, url]
        r = _run(cmd, timeout=timeout)
        got = next(iter(sorted(p for p in glob_dir.glob(glob_pat) if not p.name.endswith((".part", ".ytdl")))), None)
        if r.returncode == 0 and got:
            return got, c
        errs.append(f"{c or 'default'}: {_last_line(r.stderr, 120)}")
    raise RuntimeError("download failed (" + " | ".join(errs) + ")")


def step_meta(tid: str, v: dict) -> dict:
    with _rm_slot("download", tid):
        r = _run(["yt-dlp", "-J", "--skip-download", "--no-warnings", "--no-playlist", v["url"]], timeout=180)
    if r.returncode != 0:
        raise RuntimeError(f"yt-dlp metadata failed: {(r.stderr or '').strip()[-300:]}")
    d = json.loads(r.stdout)
    keys = ("id", "title", "duration", "upload_date", "view_count", "like_count", "comment_count", "channel", "channel_follower_count",
            "tags", "categories", "chapters", "thumbnail", "language", "width", "height", "fps")
    keep = {k: d.get(k) for k in keys}
    keep["description"] = (d.get("description") or "")[:5000]
    keep["has_captions"] = bool(d.get("subtitles"))
    keep["has_auto_captions"] = bool(d.get("automatic_captions"))
    _wj(_vdir(tid, v["id"]) / "meta.json", keep)
    return {}


_TS = re.compile(r"(\d+):(\d{2}):(\d{2})[.,](\d{3})\s+-->")


def parse_vtt(text: str) -> list:
    """WebVTT -> [{start, text}], de-duplicating YouTube auto-caption roll-up lines."""
    segs, cur, seen_last = [], None, ""
    for line in text.splitlines():
        m = _TS.match(line.strip())
        if m:
            h, mi, s, ms = map(int, m.groups())
            cur = h * 3600 + mi * 60 + s + ms / 1000
            continue
        if cur is None or not line.strip() or line.startswith(("WEBVTT", "Kind:", "Language:", "NOTE")):
            continue
        clean = re.sub(r"<[^>]+>", "", line).replace("&amp;", "&").replace("&gt;", ">").replace("&lt;", "<").replace("&nbsp;", " ").strip()
        if not clean or clean == seen_last:
            continue
        seen_last = clean
        segs.append({"start": round(cur, 2), "text": clean})
    return segs


def _whisper_json(path: Path):
    d = _rj(path, {}) or {}
    segs, words = [], []
    for s in d.get("transcription", []):
        off = s.get("offsets") or {}
        txt = (s.get("text") or "").strip()
        if txt:
            segs.append({"start": round(off.get("from", 0) / 1000, 2), "end": round(off.get("to", 0) / 1000, 2), "text": txt})
        for tk in s.get("tokens") or []:
            t = tk.get("text") or ""
            if t.startswith("[_") or not t.strip():
                continue
            o = tk.get("offsets") or {}
            if t.startswith(" ") or not words:
                words.append({"w": t.strip(), "start": round(o.get("from", 0) / 1000, 2), "end": round(o.get("to", 0) / 1000, 2), "p": round(float(tk.get("p", 0)), 2)})
            else:
                words[-1]["w"] += t
                words[-1]["end"] = round(o.get("to", 0) / 1000, 2)
    return segs, words


def _last_line(s: str, n: int = 160) -> str:
    lines = (s or "").strip().splitlines()
    return lines[-1][:n] if lines else ""


def step_transcript(tid: str, v: dict) -> dict:
    d = _vdir(tid, v["id"])
    d.mkdir(parents=True, exist_ok=True)
    tried = []
    py = research_python()
    if py:
        with _rm_slot("download", tid):
            r = _run([py, str(TOOLS_DIR / "transcript_api.py"), v["id"], str(d / "yta.json")], timeout=120)
        y = _rj(d / "yta.json") if r.returncode == 0 else None
        (d / "yta.json").unlink(missing_ok=True)
        if y and y.get("segments"):
            segs = y["segments"]
            src = "youtube_transcript_api" + (" (auto)" if y.get("generated") else "")
            _wj(d / "transcript.json", {"source": src, "segments": segs, "text": " ".join(s["text"] for s in segs)})
            return {"source": "youtube_transcript_api"}
        tried.append("transcript-api: " + (_last_line(r.stderr) or "failed"))
    for old in d.glob("subs*.vtt"):
        old.unlink()
    with _rm_slot("download", tid):
        r = _run(["yt-dlp", "--skip-download", "--no-warnings", "--no-playlist", "--write-subs", "--write-auto-subs", "--sub-langs", "en,en-US,en-GB,en-orig",
                  "--sub-format", "vtt", "-o", str(d / "subs.%(ext)s"), v["url"]], timeout=180)
    vtts = sorted(d.glob("subs*.vtt"), key=lambda p: (".en." not in p.name, len(p.name)))
    segs = parse_vtt(vtts[0].read_text("utf-8", errors="replace")) if vtts else []
    for f in vtts:
        f.unlink(missing_ok=True)
    if segs:
        meta = _rj(d / "meta.json", {}) or {}
        _wj(d / "transcript.json", {"source": "youtube_captions" if meta.get("has_captions") else "youtube_auto_captions", "segments": segs,
                                    "text": " ".join(s["text"] for s in segs), "tried": tried})
        return {"source": "captions"}
    tried.append("yt-dlp captions: " + (_last_line(r.stderr) if r.returncode else "no English captions"))
    wm = _whisper_model()
    if not (_which("whisper-cli") and wm and _which("ffmpeg")):
        raise RuntimeError("no transcript: " + " | ".join(tried) + " | local whisper.cpp/ffmpeg unavailable")
    with _rm_slot("download", tid):
        src, _client = _ytdlp_dl("bestaudio/best", str(d / "audio.%(ext)s"), v["url"], d, "audio.*", 900)
    wav = d / "audio16k.wav"
    try:
        c = _run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-ar", "16000", "-ac", "1", str(wav)], timeout=900)
        if c.returncode != 0:
            raise RuntimeError(f"ffmpeg audio conversion failed: {(c.stderr or '').strip()[-200:]}")
        with _rm_slot("whisper", tid):
            w = _run(["whisper-cli", "-m", str(wm), "-f", str(wav), "-ojf", "-otxt", "-of", str(d / "whisper"), "-np"], timeout=7200)
    finally:
        src.unlink(missing_ok=True)
        wav.unlink(missing_ok=True)
    if w.returncode != 0 or not (d / "whisper.json").is_file():
        raise RuntimeError(f"whisper.cpp failed: {(w.stderr or '').strip()[-200:]}")
    segs, words = _whisper_json(d / "whisper.json")
    (d / "whisper.json").unlink(missing_ok=True)
    (d / "whisper.txt").unlink(missing_ok=True)
    _wj(d / "words.json", words)
    _wj(d / "transcript.json", {"source": f"whisper.cpp ({wm.name})", "fallback_reason": " | ".join(tried), "segments": segs,
                                "words_file": "words.json", "text": " ".join(s["text"] for s in segs)})
    return {"source": "whisper.cpp"}


def _scene_cuts(video: Path, tid: str) -> list:
    with _rm_slot("ffmpeg", tid):
        r = _run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(video), "-an", "-vf",
                  f"select='gt(scene,{SCENE_THRESHOLD})',metadata=print:file=-", "-f", "null", "-"], timeout=3600)
    times = [float(x) for x in re.findall(r"pts_time:([0-9.]+)", (r.stdout or "") + (r.stderr or ""))]
    return sorted(set(round(t, 2) for t in times))


def _sample(xs: list, n: int) -> list:
    if len(xs) <= n:
        return list(xs)
    step = (len(xs) - 1) / (n - 1)
    return [xs[round(i * step)] for i in range(n)]


def _still(video: Path, t: float, out: Path) -> bool:
    c = _run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{max(t, 0):.2f}", "-i", str(video), "-frames:v", "1", "-vf", "scale=480:-2", str(out)], timeout=120)
    return c.returncode == 0 and out.is_file()


def step_frames(tid: str, v: dict) -> dict:
    if not _which("ffmpeg"):
        return {"skipped": "ffmpeg not installed"}
    d = _vdir(tid, v["id"])
    fd = d / "frames"
    if fd.exists():
        shutil.rmtree(fd)
    (fd / "seq").mkdir(parents=True, exist_ok=True)
    dur = (_rj(d / "meta.json", {}) or {}).get("duration") or v.get("duration") or 0
    if not dur:
        _wj(d / "frames.json", {"skipped": "unknown duration", "frames": []})
        return {"skipped": "unknown duration"}
    for f in ("ocr.json", "shot_notes.json", "audio.json"):
        if ((_rj(d / f, {}) or {}).get("skipped") or "") == "frames failed":
            (d / f).unlink(missing_ok=True)
    with _rm_slot("download", tid):
        vf, client = _ytdlp_dl("18/bv*[height<=480][ext=mp4]+ba/b[height<=480]/worst", str(d / "lowres.%(ext)s"), v["url"], d, "lowres.*", 1800)
    try:
        cuts = _scene_cuts(vf, tid)
        later = [c for c in cuts if c > 1.0]
        points = [0.5] + later
        frames, seqs = [], []
        with _rm_slot("ffmpeg", tid):
            for i, t in enumerate(_sample(points, MAX_FRAMES)):
                out = fd / f"f{i:03d}.jpg"
                if _still(vf, t + (0.2 if i else 0), out):
                    frames.append({"file": f"frames/{out.name}", "t": round(t, 2), "kind": "start" if i == 0 else "cut"})
            for k, t in enumerate(_sample(later or [dur / 2], SEQ_CUTS)):
                files = []
                for j, dt in enumerate((-0.6, 0.25, 1.5)):
                    out = fd / "seq" / f"s{k:02d}_{j}.jpg"
                    if _still(vf, min(max(t + dt, 0), max(dur - 0.1, 0)), out):
                        files.append(f"frames/seq/{out.name}")
                if len(files) >= 2:
                    seqs.append({"t": t, "files": files})
            _run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(vf), "-vn", "-ac", "1", "-ar", "22050", str(d / "audio22k.wav")], timeout=900)
    finally:
        vf.unlink(missing_ok=True)
    if not frames:
        raise RuntimeError("ffmpeg produced no frames")
    mins = dur / 60
    _wj(d / "cuts.json", {"threshold": SCENE_THRESHOLD, "cuts": cuts, "count": len(cuts), "cuts_per_minute": round(len(cuts) / mins, 2) if mins else None,
                          "avg_shot_s": round(dur / (len(cuts) + 1), 2), "frames_sampled": len(frames), "download_client": client or "default",
                          "shots": [{"t": a, "shot_len_s": round(b - a, 2)} for a, b in zip([0.0] + cuts, cuts + [float(dur)])],
                          "sampled_from": "all cuts" if len(points) <= MAX_FRAMES else f"{MAX_FRAMES} of {len(points)} evenly"})
    _wj(d / "sequences.json", seqs)
    _wj(d / "frames.json", {"frames": frames})
    return {"count": len(frames), "cuts": len(cuts)}


def step_ocr(tid: str, v: dict) -> dict:
    d = _vdir(tid, v["id"])
    py = research_python()
    fr = (_rj(d / "frames.json", {}) or {}).get("frames") or []
    if not fr or not py:
        why = "no frames" if not fr else "research venv missing"
        _wj(d / "ocr.json", {"skipped": why, "frames": []})
        return {"skipped": why}
    with _rm_slot("ocr", tid):
        r = _run([py, str(TOOLS_DIR / "ocr_frames.py"), str(d / "frames"), str(d / "ocr_raw.json")], timeout=1800)
    raw = _rj(d / "ocr_raw.json")
    (d / "ocr_raw.json").unlink(missing_ok=True)
    if r.returncode != 0 or raw is None:
        raise RuntimeError(f"OCR failed: {(r.stderr or '').strip()[-200:]}")
    t_of = {Path(f["file"]).name: f["t"] for f in fr}
    out = [{"t": t_of.get(x["file"]), "file": x["file"], "text": x.get("text", ""), "lines": x.get("lines", [])} for x in raw if x["file"] in t_of]
    _wj(d / "ocr.json", {"engine": "Apple Vision (ocrmac, accurate)", "frames": out})
    return {"with_text": sum(1 for x in out if x["text"])}


def _ffmpeg_audio(wav: Path, tid: str) -> dict:
    with _rm_slot("audio", tid):
        r = _run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(wav), "-af", "silencedetect=noise=-35dB:d=0.4,ebur128=peak=true", "-f", "null", "-"], timeout=1800)
    e = r.stderr or ""
    starts = [float(x) for x in re.findall(r"silence_start: ([0-9.]+)", e)]
    ends = [(float(a), float(b)) for a, b in re.findall(r"silence_end: ([0-9.]+) \| silence_duration: ([0-9.]+)", e)]
    sil = [{"start": round(s, 2), "end": round(en, 2), "dur": round(du, 2)} for s, (en, du) in zip(starts, ends)]
    summ = e[e.rfind("Summary:"):] if "Summary:" in e else ""

    def g(pat):
        m = re.search(pat, summ)
        return float(m.group(1)) if m else None
    return {"silences": sil, "silence_count": len(sil), "silence_total_s": round(sum(s["dur"] for s in sil), 1),
            "integrated_lufs": g(r"I:\s+(-?[0-9.]+) LUFS"), "loudness_range_lu": g(r"LRA:\s+([0-9.]+) LU"), "true_peak_dbfs": g(r"Peak:\s+(-?[0-9.]+) dBFS")}


def step_audio(tid: str, v: dict) -> dict:
    d = _vdir(tid, v["id"])
    wav = d / "audio22k.wav"
    if not wav.is_file() and _which("ffmpeg"):  # temp wav gone (resume): fetch audio again
        with _rm_slot("download", tid):
            src, _c = _ytdlp_dl("bestaudio/best", str(d / "audio.%(ext)s"), v["url"], d, "audio.[!j]*", 900)
        try:
            _run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-vn", "-ac", "1", "-ar", "22050", str(wav)], timeout=900)
        finally:
            src.unlink(missing_ok=True)
    if not wav.is_file():
        _wj(d / "audio.json", {"skipped": "no audio extracted"})
        return {"skipped": "no audio"}
    try:
        out = {"ffmpeg": _ffmpeg_audio(wav, tid)}
        py = research_python()
        if py:
            with _rm_slot("audio", tid):
                r = _run([py, str(TOOLS_DIR / "audio_features.py"), str(wav), str(d / "librosa.json")], timeout=3600)
            out["librosa"] = _rj(d / "librosa.json") if r.returncode == 0 else {"error": (r.stderr or "").strip()[-200:]}
            (d / "librosa.json").unlink(missing_ok=True)
    finally:
        wav.unlink(missing_ok=True)
    _wj(d / "audio.json", out)
    return {"lufs": out["ffmpeg"].get("integrated_lufs")}


SHOT_PROMPT = ("These {n} stills are consecutive moments around one edit point in a YouTube video (about 0.6 s before, just after, 1.5 s after). "
               "In 2-3 sentences: shot type and framing, implied camera movement, what changed across the cut (hard cut, jump cut, match cut, "
               "B-roll insert, graphic/text overlay, screen recording), on-screen text or graphics, lighting/colour. Be concrete; no guessing beyond the images.")


def step_shot_notes(tid: str, v: dict, vlm) -> dict:
    d = _vdir(tid, v["id"])
    seqs = _rj(d / "sequences.json") or []
    if not seqs or not vlm:
        why = "no sequences" if not seqs else "no local video model"
        _wj(d / "shot_notes.json", {"skipped": why, "notes": []})
        return {"skipped": why}
    notes = []
    for s in seqs:
        imgs = [base64.b64encode((d / f).read_bytes()).decode() for f in s["files"]]
        with _rm_slot("vlm", tid, model=vlm):
            txt = _d("vision")(vlm, SHOT_PROMPT.format(n=len(imgs)), imgs)
            _tokens(tid, "vlm")
        notes.append({"t": s["t"], "note": " ".join(str(txt).split())[:800]})
    _wj(d / "shot_notes.json", {"model": vlm, "notes": notes})
    return {"model": vlm, "count": len(notes)}


# -- phase 3: timeline + analysis --

def step_timeline(tid: str, v: dict) -> dict:
    d = _vdir(tid, v["id"])
    tr = _rj(d / "transcript.json", {}) or {}
    cuts = (_rj(d / "cuts.json", {}) or {}).get("cuts") or []
    ocr = (_rj(d / "ocr.json", {}) or {}).get("frames") or []
    shots = (_rj(d / "shot_notes.json", {}) or {}).get("notes") or []
    au = _rj(d / "audio.json", {}) or {}
    ff, lb = au.get("ffmpeg") or {}, au.get("librosa") or {}
    ev = [{"t": s.get("start"), "type": "speech", "text": s.get("text")} for s in tr.get("segments") or []]
    ev += [{"t": c, "type": "cut"} for c in cuts]
    ev += [{"t": o["t"], "type": "ocr", "text": o["text"]} for o in ocr if o.get("text") and o.get("t") is not None]
    ev += [{"t": s["t"], "type": "shot", "text": s["note"]} for s in shots]
    ev += [{"t": s["start"], "type": "silence", "dur": s["dur"]} for s in ff.get("silences") or []]
    ev = sorted((e for e in ev if e.get("t") is not None), key=lambda e: (e["t"], e["type"]))
    dur = (_rj(d / "meta.json", {}) or {}).get("duration") or v.get("duration") or 0
    pm = []
    rms = lb.get("rms_db_per_s") or []
    beats = lb.get("beat_times") or []
    for m in range(int(dur // 60) + 1 if dur else 0):
        a, b = m * 60, m * 60 + 60
        sl = rms[a:b]
        pm.append({"minute": m, "words": sum(len((s.get("text") or "").split()) for s in tr.get("segments") or [] if a <= (s.get("start") or 0) < b),
                   "cuts": sum(1 for c in cuts if a <= c < b), "ocr_frames": sum(1 for o in ocr if o.get("text") and a <= (o.get("t") or -1) < b),
                   "silence_s": round(sum(s["dur"] for s in ff.get("silences") or [] if a <= s["start"] < b), 1),
                   "loudness_db": round(sum(sl) / len(sl), 1) if sl else None, "beats": sum(1 for t in beats if a <= t < b)})
    _wj(d / "timeline.json", {"duration": dur, "events": ev, "per_minute": pm})
    return {"events": len(ev)}


def extract_json(text: str):
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", str(text).strip())
    with contextlib.suppress(ValueError):
        return json.loads(t)
    a, b = t.find("{"), t.rfind("}")
    if a >= 0 and b > a:
        with contextlib.suppress(ValueError):
            return json.loads(t[a:b + 1])
    raise ValueError("model did not return JSON")


def _tokens(tid: str, kind: str) -> None:
    """Record Ollama token counts (prompt_eval_count/eval_count) of the last call on this thread."""
    u = _deps.get("usage")
    got = u() if u else None
    if not tid or not got:
        return

    def f(j):
        t = j.setdefault("tokens", {}).setdefault(kind, {"calls": 0, "prompt": 0, "output": 0})
        t["calls"] += 1
        t["prompt"] += int(got.get("prompt") or 0)
        t["output"] += int(got.get("output") or 0)
    with contextlib.suppress(Exception):
        _update(tid, f)


def _ask_json(model: str, prompt: str, tid: str = "", kind: str = "llm") -> dict:
    last = None
    for attempt in range(2):
        with _rm_slot("llm", tid, model=model):
            out = _d("llm")(model, prompt if attempt == 0 else prompt + "\n\nReturn ONLY a single valid JSON object. No prose, no code fences.")
            _tokens(tid, kind)
        try:
            j = extract_json(out)
            if isinstance(j, dict):
                return j
        except ValueError as e:
            last = e
    raise RuntimeError(f"{model}: {last or 'non-object JSON'}")


def _clip(text: str, n: int) -> str:
    return text if len(text) <= n else text[: int(n * 0.75)] + "\n[...]\n" + text[-int(n * 0.25):]


def _mmss(t) -> str:
    t = int(t or 0)
    return f"{t // 60}:{t % 60:02d}"


CHUNK = 9000
ANALYSIS_KEYS = ("summary", "topics", "key_ideas", "hook", "structure", "pacing", "editing", "tone", "visuals", "calls_to_action", "title_pattern")


def _timed(tr: dict) -> str:
    segs = tr.get("segments") or []
    return "\n".join(f"[{_mmss(s.get('start'))}] {s.get('text')}" for s in segs) if segs else tr.get("text", "")


def _chunk_notes(tid: str, d: Path, timed: str, model: str) -> str:
    if len(timed) <= 10500:
        return timed
    cached = _rj(d / "chunk_notes.json")
    if not cached:
        parts = [timed[i:i + CHUNK] for i in range(0, len(timed), CHUNK)]
        cached = []
        for i, p in enumerate(parts):
            r = _ask_json(model, f"""Part {i + 1}/{len(parts)} of a timed YouTube transcript. Return JSON {{"notes": [string]}}: 6-12 dense notes covering
every claim, example, tool, number and structural move, each starting with its [m:ss] timestamp; plus "quotes": [{{"t": "m:ss", "text": exact short quote}}] (3-6).
TRANSCRIPT PART:
{p}""", tid)
            cached.append(r)
        _wj(d / "chunk_notes.json", cached)
    return "\n".join("\n".join(map(str, c.get("notes") or [])) + "\nQUOTES: " + "; ".join(f"[{q.get('t')}] {q.get('text')}" for q in c.get("quotes") or [] if isinstance(q, dict)) for c in cached)


def _facts(d: Path, v: dict) -> dict:
    tr = _rj(d / "transcript.json", {}) or {}
    meta = _rj(d / "meta.json", {}) or {}
    cuts = _rj(d / "cuts.json", {}) or {}
    au = _rj(d / "audio.json", {}) or {}
    ocr = (_rj(d / "ocr.json", {}) or {}).get("frames") or []
    dur = meta.get("duration") or v.get("duration")
    words = len((tr.get("text") or "").split())
    lb = au.get("librosa") or {}
    return {"duration_s": dur, "words": words, "words_per_minute": round(words / (dur / 60), 1) if dur else None,
            "cuts": cuts.get("count"), "cuts_per_minute": cuts.get("cuts_per_minute"), "avg_shot_s": cuts.get("avg_shot_s"),
            "silence_total_s": (au.get("ffmpeg") or {}).get("silence_total_s"), "integrated_lufs": (au.get("ffmpeg") or {}).get("integrated_lufs"),
            "loudness_range_lu": (au.get("ffmpeg") or {}).get("loudness_range_lu"), "tempo_bpm": lb.get("tempo_bpm"), "music_likely_heuristic": lb.get("music_likely"),
            "ocr_frames_with_text": sum(1 for o in ocr if o.get("text")), "frames_sampled": len(ocr), "transcript_source": tr.get("source"),
            "views": meta.get("view_count"), "likes": meta.get("like_count")}


def step_analysis(tid: str, v: dict, model: str) -> dict:
    d = _vdir(tid, v["id"])
    tr = _rj(d / "transcript.json")
    if not tr:
        raise RuntimeError("no transcript")
    meta = _rj(d / "meta.json", {}) or {"title": v.get("title"), "duration": v.get("duration")}
    facts = _facts(d, v)
    body = _chunk_notes(tid, d, _timed(tr), model)
    shots = "\n".join(f"- [{_mmss(s['t'])}] {s['note']}" for s in (_rj(d / "shot_notes.json", {}) or {}).get("notes") or []) or "(none)"
    ocr = "\n".join(f"- [{_mmss(o['t'])}] {o['text'][:160]}" for o in (_rj(d / "ocr.json", {}) or {}).get("frames") or [] if o.get("text")) or "(none)"
    chapters = ", ".join(f"{c.get('title')}@{_mmss(c.get('start_time'))}" for c in (meta.get("chapters") or [])[:30]) or "none"
    ctx = f"""TITLE: {meta.get('title')}
CHANNEL: {meta.get('channel')}
MEASURED FACTS (trust these over impressions): {json.dumps(facts)}
CHAPTERS: {chapters}
DESCRIPTION: {_clip(meta.get('description') or '', 1000)}
SHOT NOTES (local video model at cuts):
{_clip(shots, 2200)}
ON-SCREEN TEXT (OCR):
{_clip(ocr, 1400)}
TRANSCRIPT / NOTES ({tr.get('source')}):
{_clip(body, 10500)}"""
    a = _ask_json(model, f"""Analyse this YouTube video. Use ONLY the data; say "unknown" when unsure. Return JSON with keys:
 "summary": string (3 sentences), "topics": [string], "key_ideas": [string] (5-10, concrete),
 "hook": {{"first_15s": string, "technique": string, "strength": 1-5}},
 "structure": {{"segments": [{{"label": string, "start": "m:ss", "purpose": string}}], "pattern": string}},
 "pacing": {{"notes": string}}, "editing": {{"style": string, "devices": [string]}},
 "tone": {{"voice": string, "persona": string, "vocabulary": [string]}},
 "visuals": {{"shot_types": [string], "on_screen_text": string, "notes": string}},
 "calls_to_action": [{{"at": "m:ss", "text": string}}], "title_pattern": string
{ctx}""", tid)
    b = _ask_json(model, f"""Score and mine this YouTube video for Jenkins Robotics (a solo robotics/AI maker channel). Use ONLY the data. Return JSON:
 "scores": {{"channel_context": 1-5, "self_interest": 1-5, "style_copy": 1-5}}, "score_why": {{same keys: string}},
 "flags": {{"substance": bool, "hype": bool, "actionable": bool, "needs_visual_review": bool}}, "confidence": 0-1,
 "metrics": {{ "pacing", "cut_rhythm", "retention_proxy", "text_on_screen", "hook", "cta_clarity": each {{"value": 1-5, "reason": string, "evidence_t": ["m:ss", ...]}} }},
 "channel_idea": string, "self_interest_action": string, "style_note": string, "key_insights": [string], "tools_detected": [string],
 "areas": {{ {", ".join(f'"{x}"' for x in AREAS)}: [2-5 of {{"technique": string, "detail": string, "why_it_matters": string,
   "apply_for_jr": string, "quote": exact short quote from transcript or "", "timestamp": "m:ss"}}] (use [] if the video has nothing for that area) }}
{ctx}""", tid)
    a.update({k: b.get(k) for k in ("metrics", "scores", "score_why", "flags", "confidence", "channel_idea", "self_interest_action", "style_note", "key_insights", "tools_detected", "areas")})
    a["measured"] = facts
    a["_meta"] = {"provenance": "jaeger-youtube-research-v2", "model": model, "video_id": v["id"], "title": meta.get("title"),
                  "transcript_source": tr.get("source"), "shot_notes": shots != "(none)", "at": time.time()}
    _wj(d / "analysis.json", a)
    return {"model": model}


_OUT = {"meta": "meta.json", "transcript": "transcript.json", "frames": "frames.json", "ocr": "ocr.json", "audio": "audio.json",
        "shot_notes": "shot_notes.json", "timeline": "timeline.json", "analysis": "analysis.json"}
_HARD = ("meta", "transcript", "analysis")


def _do_step(tid: str, v: dict, step: str, j: dict, force: set, stop) -> bool:
    """Run one step for one video. Returns False when the video is blocked."""
    cur = next(x for x in _job(tid)["videos"] if x["id"] == v["id"])
    st = cur["steps"][step].get("status")
    if st == "blocked" and not (_vdir(tid, v["id"]) / _OUT[STEPS[STEPS.index(step) - 1]]).is_file():
        return False
    out = _vdir(tid, v["id"]) / _OUT[step]
    if out.is_file() and step not in force:
        if st not in ("done", "skipped"):
            prev = _rj(out, {})
            sk = isinstance(prev, dict) and prev.get("skipped")
            _set_step(tid, v["id"], step, "skipped" if sk else "done", reused=True, **({"reason": sk} if sk else {}))
        return True
    if any(cur["steps"][h].get("status") == "error" for h in _HARD if STEPS.index(h) < STEPS.index(step)):
        return False
    while (_paused.get(tid) or _job(tid).get("paused")) and not stop.is_set():  # persisted: works across processes
        time.sleep(2)
    if stop.is_set():
        return False
    _set_step(tid, v["id"], step, "running")
    try:
        if step == "shot_notes":
            info = step_shot_notes(tid, v, j.get("video_model"))
        elif step == "analysis":
            info = step_analysis(tid, v, j["model"])
        else:
            info = globals()["step_" + step](tid, v)
        sk = info.get("skipped")
        _set_step(tid, v["id"], step, "skipped" if sk else "done", **({"reason": sk} if sk else info))
        if step in _HARD:  # a retried hard step that now works unblocks the steps after it
            def unblock(jj):
                for x in jj["videos"]:
                    if x["id"] == v["id"]:
                        for rest in STEPS[STEPS.index(step) + 1:]:
                            if x["steps"][rest].get("status") == "blocked" and x["steps"][rest].get("error") == f"needs {step}":
                                x["steps"][rest] = {"status": "pending"}
            _update(tid, unblock)
        return True
    except Exception as exc:  # noqa: BLE001
        _set_step(tid, v["id"], step, "error", str(exc)[:500])
        if step in _HARD:
            for rest in STEPS[STEPS.index(step) + 1:]:
                _set_step(tid, v["id"], rest, "blocked", f"needs {step}")
            return False
        if step == "frames":
            d = _vdir(tid, v["id"])
            for f, k in (("ocr.json", "frames"), ("shot_notes.json", "notes")):
                _wj(d / f, {"skipped": "frames failed", k: []})
            (d / "audio22k.wav").unlink(missing_ok=True)
        return True


def _job_thread(tid: str, force: set, with_style: bool, stop: threading.Event) -> None:
    try:
        _update(tid, lambda j: j.update(state="running", error=None))
        for pi, steps in enumerate(PHASES, 1):
            _update(tid, lambda j: j.update(phase=pi))
            j = _job(tid)
            iw = _deps.get("io_workers")
            workers = (max(1, min(int(iw()), 4)) if iw else IO_WORKERS) if pi == 1 else 1
            _update(tid, lambda j, w=workers: j.update(workers=w))

            claimed, cl_lock = set(), threading.Lock()

            def worker(steps=steps, j=j, claimed=claimed, cl_lock=cl_lock):
                while not stop.is_set():
                    with cl_lock:  # current job order each time, so POST .../reorder takes effect for unstarted videos
                        v = next((x for x in _job(tid)["videos"] if x["id"] not in claimed), None)
                        if v is None:
                            return
                        claimed.add(v["id"])
                    for s in steps:
                        if not _do_step(tid, v, s, j, force, stop):
                            break
            with ThreadPoolExecutor(max_workers=workers) as ex:
                for f in [ex.submit(worker) for _ in range(workers)]:
                    f.result()
            if stop.is_set():
                _update(tid, lambda j: j.update(state="cancelled"))
                return
            cl = _deps.get("cleanup")
            if cl:
                with contextlib.suppress(Exception):
                    cl(_tdir(tid))
        _update(tid, lambda j: j.update(phase=4))
        if with_style:
            try:
                build_style_guide(tid, force="style_guide" in force)
            except Exception as exc:  # noqa: BLE001
                _update(tid, lambda j, error=str(exc)[:500]: j["style_guide"].update(status="error", error=error))
        try:
            n = write_kb(tid)
            _update(tid, lambda j: j["kb"].update(status="done", path=str(kb_root()), notes=n, at=time.time()))
        except Exception as exc:  # noqa: BLE001
            _update(tid, lambda j, error=str(exc)[:500]: j["kb"].update(status="error", error=error))
        rm = _deps.get("rm")
        if rm:
            with contextlib.suppress(Exception):
                rm.release_models([m for m in (_job(tid).get("model"), _job(tid).get("video_model")) if m])
        j = _job(tid)
        errs = sum(1 for v in j["videos"] if any(s.get("status") == "error" for s in v["steps"].values()))
        _update(tid, lambda j: j.update(state="done" if not errs and j["style_guide"].get("status") == "done" else "done_with_errors"))
    except Exception as exc:  # noqa: BLE001
        _update(tid, lambda j, error=str(exc)[:500]: j.update(state="error", error=error))
    finally:
        with _glock:
            _running.pop(tid, None)


RUNNER_FRESH_S = 120


def runner_heartbeat():
    hb = _rj(Path(_d("state_root")()) / "jobs" / "runner.json")
    if isinstance(hb, dict) and time.time() - float(hb.get("at") or 0) < RUNNER_FRESH_S:
        return hb
    return None


def runner_owns(tid: str) -> bool:
    if _deps.get("is_runner"):
        return False
    hb = runner_heartbeat()
    return bool(hb and tid in (hb.get("owned") or []))


def start(tid: str, force=None, style_guide: bool = True, wait: bool = False) -> dict:
    _job(tid)
    if runner_owns(tid):
        return {"started": False, "reason": "owned by the 24/7 job runner (com.jenkinsrobotics.jaeger-jobs)"}
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


def extend(tid: str, n: int) -> int:
    """Grow the job to the first n playlist videos (keeps order, adds only unseen ids). Returns videos added."""
    j = _job(tid)
    if n <= len(j["videos"]):
        return 0
    pl = list_playlist(j["playlist_id"], n)
    have = {v["id"] for v in j["videos"]}
    add = [_video(e) for e in pl["entries"] if e["id"] not in have]
    _update(tid, lambda x: (x["videos"].extend(add), x.update(max_videos=n, item_count=pl.get("item_count") or x.get("item_count"))))
    return len(add)


def batch_done(j: dict) -> bool:
    fin = ("done", "skipped", "error", "blocked")
    return all(all(v["steps"][s].get("status") in fin for s in STEPS) for v in j["videos"])


def last_progress_at(j: dict) -> float:
    return max([float(j.get("updated_at") or 0)] + [float(s.get("at") or 0) for v in j["videos"] for s in v["steps"].values()])


def pause(tid: str, paused: bool = True) -> dict:
    _job(tid)
    _paused[tid] = bool(paused)
    _update(tid, lambda j: j.update(paused=bool(paused)))
    return {"paused": bool(paused), "note": "running steps finish; no new step starts while paused"}


def reorder(tid: str, video_ids) -> dict:
    if not isinstance(video_ids, list) or not all(isinstance(x, str) for x in video_ids):
        raise YtError(400, "video_ids must be a list of video ids")

    def f(j):
        pos = {vid: i for i, vid in enumerate(video_ids)}
        orig = {v["id"]: i for i, v in enumerate(j["videos"])}
        j["videos"].sort(key=lambda v: pos.get(v["id"], len(pos) + orig[v["id"]]))
    _update(tid, f)
    return {"order": [v["id"] for v in _job(tid)["videos"]]}


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
    hb = None if running else runner_heartbeat()
    if hb and tid in (hb.get("active") or []):
        running = True
        j["owner"] = "job-runner"
    if not running and j.get("state") in ("running", "queued"):
        j["state"] = "interrupted"
    total = len(j["videos"]) * len(STEPS)
    fin = sum(1 for v in j["videos"] for s in v["steps"].values() if s.get("status") in ("done", "skipped", "error", "blocked"))
    j["running"] = running
    j["paused"] = bool(_paused.get(tid))
    if running and j["paused"]:
        j["state"] = "paused"
    j["progress"] = {"steps_finished": fin, "steps_total": total,
                     "videos_analysed": sum(1 for v in j["videos"] if v["steps"]["analysis"].get("status") == "done"),
                     "videos_with_errors": sum(1 for v in j["videos"] if any(s.get("status") == "error" for s in v["steps"].values())),
                     "videos": len(j["videos"])}
    rm = _deps.get("rm")
    if rm:
        with contextlib.suppress(Exception):
            j["resource_usage"] = rm.job_usage(tid)
    return j


def list_jobs() -> list:
    out = []
    root = _root()
    for p in sorted(root.glob("*/job.json")) if root.is_dir() else []:
        j = _rj(p)
        if isinstance(j, dict):
            s = status(j["task_id"])
            out.append({k: s.get(k) for k in ("task_id", "playlist_title", "playlist_url", "state", "phase", "running", "progress", "updated_at")} | {"style_guide": s["style_guide"].get("status")})
    return out


# -- style guide --

GUIDE_KEYS = ("text_styles", "music", "palette_notes", "voice_and_tone", "hooks", "structure_template", "pacing", "editing", "visuals", "sound", "titles_and_thumbnails", "calls_to_action", "dos", "donts", "example_lines")


def style_prompt(analyses: list, channel, visual=None) -> str:
    compact = json.dumps([{k: a.get(k) for k in ANALYSIS_KEYS if k not in ("summary", "key_ideas")} | {"title": a["_meta"]["title"], "measured": a.get("measured"), "style_note": a.get("style_note")} for a in analyses], ensure_ascii=False)
    return f"""Below are per-video analyses (with MEASURED facts: wpm, cuts/min, LUFS, silences, OCR) of {len(analyses)} videos from "{channel or 'unknown'}".
Write a reusable STYLE GUIDE. Generalise; cite measured ranges (e.g. cuts/min, wpm, LUFS) where they exist. Return JSON with keys:
 "voice_and_tone": string, "hooks": {{"pattern": string, "templates": [string]}},
 "structure_template": [{{"section": string, "share_pct": number, "purpose": string}}],
 "pacing": {{"target_wpm": number or null, "cuts_per_minute": string, "notes": string}}, "editing": [string], "visuals": [string], "sound": [string],
 "titles_and_thumbnails": {{"title_formulas": [string], "thumbnail_notes": string}},
 "calls_to_action": [string], "dos": [string], "donts": [string], "example_lines": [string],
 "text_styles": [{{"use": string, "look": string}}], "music": string, "palette_notes": string
MEASURED VISUALS (palette from frames, on-screen text from OCR, music from librosa): {{visual}}
ANALYSES:
{_clip(compact, 16000)}""".replace("{visual}", _clip(json.dumps(visual or {}), 1500))


def _stats(used: list) -> dict:
    out = {}
    for k in ("words_per_minute", "cuts_per_minute", "avg_shot_s", "integrated_lufs", "silence_total_s", "tempo_bpm"):
        xs = sorted(x for a in used if isinstance(x := (a.get("measured") or {}).get(k), (int, float)))
        if xs:
            out[k] = {"min": xs[0], "median": xs[len(xs) // 2], "max": xs[-1], "n": len(xs)}
    return out


def render_guide_md(g: dict, job: dict, used: list) -> str:
    L = [f"# Style guide - {job.get('playlist_title') or job['playlist_id']}", "",
         f"Learned from {len(used)} video(s) · model `{g['_meta']['model']}` · {time.strftime('%Y-%m-%d %H:%M', time.localtime(g['_meta']['at']))}", "",
         "## Measured across videos (ffmpeg/librosa/whisper, not model guesses)"]
    for k, s in (g.get("_measured") or {}).items():
        L.append(f"- **{k}**: median {s['median']} (range {s['min']}-{s['max']}, n={s['n']})")
    L.append("")
    vis = g.get("_visual") or {}
    if vis.get("palette"):
        L += ["## Palette (measured from frames)", " ".join(f"`{c['hex']}` {round(c['share'] * 100)}%" for c in vis["palette"]), ""]
    if vis.get("text"):
        L += ["## On-screen text (measured from OCR)", "```json", json.dumps(vis["text"], indent=1), "```", ""]
    if vis.get("music"):
        L += ["## Music / sound (measured)", "```json", json.dumps(vis["music"], indent=1), "```", ""]

    def sec(title, val):
        if not val:
            return
        L.append(f"## {title}")
        if isinstance(val, str):
            L.append(val)
        elif isinstance(val, list):
            L.extend("- " + (", ".join(f"{k}: {x}" for k, x in it.items()) if isinstance(it, dict) else str(it)) for it in val)
        elif isinstance(val, dict):
            L.extend(f"- **{k.replace('_', ' ')}**: " + ("; ".join(map(str, x)) if isinstance(x, list) else str(x)) for k, x in val.items())
        L.append("")
    for k in GUIDE_KEYS:
        sec(k.replace("_", " ").capitalize(), g.get(k))
    L.append("## Sources")
    L.extend(f"- {a['_meta']['title']} (https://www.youtube.com/watch?v={a['_meta']['video_id']}) - transcript: {a['_meta']['transcript_source']}" for a in used)
    return "\n".join(L) + "\n"


def build_style_guide(tid: str, force: bool = False, model=None) -> dict:
    j = _job(tid)
    td = _tdir(tid)
    if (td / "style_guide.json").is_file() and not force and j["style_guide"].get("status") == "done" and j["style_guide"].get("videos") == sum(1 for v in j["videos"] if (td / v["id"] / "analysis.json").is_file()):
        return style_guide(tid)
    used = [a for v in j["videos"] if (a := _rj(td / v["id"] / "analysis.json"))]
    if not used:
        raise RuntimeError("no analysed videos yet")
    _update(tid, lambda x: x["style_guide"].update(status="running", error=None))
    m = model or j["model"]
    vis = _visual_stats(tid, j)
    g = _ask_json(m, style_prompt(used, j.get("channel"), vis), tid)
    g["_measured"] = _stats(used)
    g["_visual"] = vis
    g["_meta"] = {"model": m, "videos": [a["_meta"]["video_id"] for a in used], "at": time.time()}
    md = render_guide_md(g, j, used)
    _wj(td / "style_guide.json", g)
    (td / "style_guide.md").write_text(md, "utf-8")
    doc = _d("save_doc")(j["style_guide"].get("document_id"), {"title": f"YouTube style guide - {j.get('playlist_title') or j['playlist_id']}", "body": md})
    if not j["style_guide"].get("document_id"):
        with contextlib.suppress(Exception):
            _d("attach")(tid, {"kind": "document", "ref": f"document:{doc['id']}", "label": "YouTube style guide"})
    _update(tid, lambda x: x["style_guide"].update(status="done", error=None, document_id=doc["id"], videos=len(used), model=m, at=time.time()))
    return style_guide(tid)


def style_guide(tid: str) -> dict:
    td = _tdir(tid)
    g = _rj(td / "style_guide.json")
    if not g:
        raise YtError(404, "no style guide yet")
    return {"task_id": tid, "json": g, "markdown": (td / "style_guide.md").read_text("utf-8"), "document_id": _job(tid)["style_guide"].get("document_id")}


# -- drafts (Content Strategist voice + SEO rules); only on explicit request --

VOICE_RULES = """VOICE: Content Strategist for Jenkins Robotics - direct, specific, builder-to-builder; show the work, real numbers, no hype words
(insane, crazy, game-changer, mind-blowing, revolutionary). SEO RULES: every title under 60 characters with the main keyword early;
description opens with a 1-2 sentence keyword-rich summary; chapters as "m:ss Label" starting at 0:00; 8-15 lowercase tags."""
HYPE = ("insane", "crazy", "game-changer", "game changer", "mind-blowing", "revolutionary", "you won't believe")


def enforce_seo(d: dict) -> dict:
    issues = []
    titles = [t for t in (d.get("titles") or []) if isinstance(t, str)]
    keep = [t for t in titles if len(t) < 60]
    if len(keep) < len(titles):
        issues.append(f"dropped {len(titles) - len(keep)} title(s) of 60+ characters")
    d["titles"] = keep
    if not d.get("chapters"):
        t, ch = 0, []
        for s in d.get("script") or []:
            if isinstance(s, dict):
                ch.append(f"{_mmss(t)} {s.get('section')}")
                t += int(s.get("est_seconds") or 0)
        d["chapters"] = ch
        issues.append("chapters built from script timings")
    tags = list(dict.fromkeys(str(x).lower().strip() for x in d.get("tags") or [] if str(x).strip()))[:15]
    if len(tags) < 8:
        issues.append(f"only {len(tags)} tags (want 8-15)")
    d["tags"] = tags
    blob = json.dumps(d, ensure_ascii=False).lower()
    hits = [h for h in HYPE if h in blob]
    if hits:
        issues.append("hype words present: " + ", ".join(hits))
    d["seo_check"] = issues
    return d


def draft(tid: str, body: dict) -> dict:
    topic = str(body.get("topic", "")).strip()
    if not topic or len(topic) > 500:
        raise YtError(400, "topic (1-500 chars) is required")
    g = style_guide(tid)["json"]
    j = _job(tid)
    m = str(body.get("model") or j["model"])
    guide = {k: v for k, v in g.items() if not k.startswith("_meta")}
    techs = body.get("techniques") or []
    clips = body.get("clips") or []
    length = body.get("length_s")
    if not isinstance(techs, list) or not isinstance(clips, list) or len(techs) > 30 or len(clips) > 30:
        raise YtError(400, "techniques and clips must be lists (max 30)")
    lib = {t["id"]: t for t in techniques()["techniques"]}
    tsel = [lib[t] if isinstance(t, str) and t in lib else t for t in techs]
    csel = []
    for c in clips:
        if not isinstance(c, dict) or not _VID.match(str(c.get("video_id", ""))):
            raise YtError(400, "clips need {video_id, t, t_end}")
        tr = _rj(_vdir(tid, c["video_id"]) / "transcript.json", {}) or {}
        t0, t1 = float(c.get("t") or 0), float(c.get("t_end") or (float(c.get("t") or 0) + 15))
        csel.append({**c, "said": " ".join(x["text"] for x in tr.get("segments") or [] if t0 <= (x.get("start") or 0) <= t1)[:600]})
    extra = ""
    if tsel:
        extra += "\nUSE THESE TECHNIQUES (in this order): " + _clip(json.dumps([{k: t.get(k) for k in ("name", "type", "description")} if isinstance(t, dict) else t for t in tsel], ensure_ascii=False), 3000)
    if csel:
        extra += "\nREFERENCE CLIPS (style to echo, do not copy words): " + _clip(json.dumps(csel, ensure_ascii=False), 3000)
    if length:
        extra += f"\nTARGET LENGTH: about {int(length)} seconds; est_seconds must add up to it."
    out = _ask_json(m, f"""{VOICE_RULES}
Using this STYLE GUIDE, draft a new YouTube video on: "{topic}". Draft for review; it will not be published.
Return JSON: "titles": [5 strings], "hook": string, "script": [{{"section": string, "est_seconds": number, "voiceover": string}}],
"shot_list": [{{"shot": number, "section": string, "visual": string, "on_screen_text": string, "est_seconds": number}}],
"thumbnail_ideas": [{{"concept": string, "text": string, "composition": string}}], "call_to_action": string, "description": string,
"chapters": [string], "tags": [string]
STYLE GUIDE:
{_clip(json.dumps(guide, ensure_ascii=False), 11000)}{extra}""", tid)
    out = enforce_seo(out)
    out["_inputs"] = {"techniques": [t.get("id") if isinstance(t, dict) else t for t in tsel], "clips": clips, "length_s": length}
    did = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:4]
    out["_meta"] = {"id": did, "topic": topic, "model": m, "at": time.time(), "style_guide_at": g["_meta"]["at"], "published": False}
    td = _tdir(tid) / "drafts"
    _wj(td / f"{did}.json", out)
    md = render_draft_md(out)
    (td / f"{did}.md").write_text(md, "utf-8")
    doc = _d("save_doc")(None, {"title": f"Draft - {topic}", "body": md})
    with contextlib.suppress(Exception):
        _d("attach")(tid, {"kind": "deliverable", "ref": f"document:{doc['id']}", "label": f"Draft: {topic}"})
    _update(tid, lambda x: x["drafts"].append({"id": did, "topic": topic, "document_id": doc["id"], "model": m, "at": time.time()}))
    return {"task_id": tid, "draft": out, "markdown": md, "document_id": doc["id"]}


def render_draft_md(d: dict) -> str:
    L = [f"# Draft - {d['_meta']['topic']}", "", "_Draft for review. Not published._", "", "## Title options"]
    L += [f"{i}. {t}" for i, t in enumerate(d.get("titles") or [], 1)]
    L += ["", "## Hook", str(d.get("hook", "")), "", "## Script"]
    for s in d.get("script") or []:
        if isinstance(s, dict):
            L += [f"### {s.get('section')} (~{s.get('est_seconds')}s)", str(s.get("voiceover", "")), ""]
    L += ["## Shot list", "| # | Section | Visual | On-screen text | s |", "|---|---|---|---|---|"]
    L += [f"| {s.get('shot')} | {s.get('section')} | {s.get('visual')} | {s.get('on_screen_text')} | {s.get('est_seconds')} |" for s in d.get("shot_list") or [] if isinstance(s, dict)]
    L += ["", "## Thumbnail ideas"]
    L += ["- " + (f"**{t.get('concept')}** - text \"{t.get('text')}\"; {t.get('composition')}" if isinstance(t, dict) else str(t)) for t in d.get("thumbnail_ideas") or []]
    L += ["", "## Call to action", str(d.get("call_to_action", "")), "", "## Description", str(d.get("description", "")), "", "## Chapters"]
    L += list(map(str, d.get("chapters") or []))
    L += ["", "## Tags", ", ".join(d.get("tags") or []), "", "## SEO check"] + [f"- {x}" for x in d.get("seo_check") or ["ok"]]
    return "\n".join(L) + "\n"


def frame_file(tid: str, vid: str, name: str) -> Path:
    if not _VID.match(vid) or not re.match(r"^(seq/)?[fs]\d{2,3}(_\d)?\.jpg$", name):
        raise YtError(404, "no such frame")
    p = _vdir(tid, vid) / "frames" / name
    if not p.is_file():
        raise YtError(404, "no such frame")
    return p


# -- import of earlier Hermes KB work (read-only sources) --

def hermes_sources() -> list:
    home = Path.home()
    cands = [home / "Documents" / "archive 2 hermes" / "yt-kb-cache", home / "Documents" / "Jenkins_Robotics" / "03_Knowledge" / "YouTube"]
    nas = Path("/Volumes/Jenkins_Robotics/03-KNOWLEDGE/Obsidian/ARES_Brain/Knowledge_Base")
    if Path("/Volumes/Jenkins_Robotics").is_dir():
        cands.append(nas)
    extra = _deps.get("hermes_sources")
    return [Path(p) for p in (extra() if extra else cands) if Path(p).is_dir()]


_HTS = re.compile(r"<(\d+):(\d{2}):(\d{2})\.(\d{3})>")


def _hermes_transcript(raw: str) -> list:
    """Hermes notes keep yt-dlp roll-up VTT text with inline <hh:mm:ss.mmm><c> word</c> tags. Rebuild timed segments from the tagged words."""
    words, t = [], None
    for m in re.finditer(r"(<\d+:\d{2}:\d{2}\.\d{3}>)?<c>([^<]*)</c>|(<\d+:\d{2}:\d{2}\.\d{3}>)", raw):
        tag = m.group(1) or m.group(3)
        if tag:
            h, mi, s, ms = map(int, _HTS.match(tag).groups())
            t = h * 3600 + mi * 60 + s + ms / 1000
        if m.group(2) is not None and m.group(2).strip():
            words.append((t or 0.0, m.group(2).strip()))
    if not words:
        txt = " ".join(raw.split())
        return [{"start": 0.0, "text": txt}] if txt else []
    segs, cur, st = [], [], words[0][0]
    for tt, w in words:
        if cur and tt - st >= 6:
            segs.append({"start": round(st, 2), "text": " ".join(cur)})
            cur, st = [], tt
        cur.append(w)
    if cur:
        segs.append({"start": round(st, 2), "text": " ".join(cur)})
    return segs


def parse_hermes_note(text: str, path: str = "") -> dict:
    def field(name):
        m = re.search(rf"\*\*{name}:\*\*\s*(.*)", text)
        return m.group(1).strip() if m else None
    vid = None
    m = re.search(r"watch\?v=([A-Za-z0-9_-]{11})", text)
    if m:
        vid = m.group(1)
    title = (re.search(r"^#\s+(.+)$", text, re.M) or [None, None])[1]
    scores = {}
    for k in ("channel_context", "self_interest", "style_copy"):
        sm = re.search(rf"{k}\W+(\d)", text, re.I)
        if sm:
            scores[k] = int(sm.group(1))
    body = text.split("## Transcript", 1)[1] if "## Transcript" in text else ""
    body = re.split(r"\n## ", body, 1)[0]
    areas = {}
    for a in AREAS:
        am = re.search(rf"^##+\s*{a}\b.*?$(.*?)(?=^##\s|\Z)", text, re.I | re.M | re.S)
        if am:
            items = [x.strip("-* ").strip() for x in am.group(1).splitlines() if x.strip().startswith(("-", "*"))]
            if items:
                areas[a] = [{"technique": i[:200]} for i in items]
    return {"video_id": vid, "title": title, "channel": field("Channel"), "processed": field("Processed"), "transcript_source": field("Transcript Source"),
            "scores": scores, "areas": areas, "segments": _hermes_transcript(body), "provenance": "imported-from-hermes", "original_path": path}


def import_existing(tid: str) -> dict:
    j = _job(tid)
    wanted = {v["id"] for v in j["videos"]}
    kb = kb_root()
    (kb / "_imported").mkdir(parents=True, exist_ok=True)
    stats = {"sources": [], "notes": 0, "processed_ids": 0, "overlap": [], "transcripts_reused": 0, "nas_mounted": Path("/Volumes/Jenkins_Robotics").is_dir()}
    pids = set(_rj(kb / "processed_ids.json", []) or [])
    for src in hermes_sources():
        stats["sources"].append(str(src))
        p = _rj(src / "processed_ids.json")
        if isinstance(p, dict):
            p = list(p.get("ids") or p.keys())
        if isinstance(p, list):
            got = {x for x in p if isinstance(x, str) and _VID.match(x)}
            stats["processed_ids"] += len(got)
            pids |= got
        for f in sorted(src.rglob("*.md")):
            try:
                n = parse_hermes_note(f.read_text("utf-8", errors="replace"), str(f))
            except OSError:
                continue
            if not n["video_id"]:
                continue
            stats["notes"] += 1
            pids.add(n["video_id"])
            _wj(kb / "_imported" / f"{n['video_id']}.json", {k: x for k, x in n.items() if k != "segments"} | {"segments_count": len(n["segments"])})
            if n["video_id"] in wanted:
                stats["overlap"].append(n["video_id"])
                tp = _vdir(tid, n["video_id"]) / "transcript.json"
                if not tp.is_file() and n["segments"]:
                    _wj(tp, {"source": f"imported-from-hermes ({n.get('transcript_source') or 'unknown'})", "provenance": "imported-from-hermes",
                             "original_path": str(f), "segments": n["segments"], "text": " ".join(s["text"] for s in n["segments"])})
                    stats["transcripts_reused"] += 1
    _wj(kb / "processed_ids.json", sorted(pids))
    stats["overlap"] = sorted(set(stats["overlap"]))
    stats["remaining"] = len(wanted - set(stats["overlap"]))
    stats["at"] = time.time()
    _update(tid, lambda x: x.update(imported=stats))
    return stats


# -- optional inbox watcher (never edits the playlist) --

def poll_new(tid: str) -> dict:
    j = _job(tid)
    have = {v["id"] for v in j["videos"]}
    pl = list_playlist(j["playlist_id"], j["max_videos"])
    add = [_video(e) for e in pl["entries"] if e["id"] not in have]
    if add:
        _update(tid, lambda x: x["videos"].extend(add))
        start(tid)
    _update(tid, lambda x: x.setdefault("watch", {}).update(last_poll=time.time(), last_added=len(add)))
    return {"added": [v["id"] for v in add]}


def watch(tid: str, enabled: bool, interval_s: int = 3600) -> dict:
    _job(tid)
    interval_s = max(300, int(interval_s))
    with _glock:
        old = _watchers.pop(tid, None)
    if old:
        old.set()
    if enabled:
        stop = threading.Event()

        def loop():
            while not stop.wait(interval_s):
                with contextlib.suppress(Exception):
                    poll_new(tid)
        with _glock:
            _watchers[tid] = stop
        threading.Thread(target=loop, daemon=True, name=f"yt-watch-{tid}").start()
    _update(tid, lambda x: x.update(watch={"enabled": bool(enabled), "interval_s": interval_s, **{k: v for k, v in (x.get("watch") or {}).items() if k.startswith("last_")}}))
    return _job(tid)["watch"]


# -- Obsidian knowledge base at <state>/research/kb --

def slug(s: str, n: int = 80) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", str(s).lower()).strip("-")
    if len(s) <= n:
        return s or "untitled"
    cut = s[:n]
    return (cut[:cut.rfind("-")] if "-" in cut else cut) or "untitled"


def write_kb(tid: str) -> int:
    j = _job(tid)
    kb = kb_root()
    techniques = {a: {} for a in AREAS}
    written = 0
    index = []
    for v in j["videos"]:
        a = _rj(_vdir(tid, v["id"]) / "analysis.json")
        if not a:
            continue
        url = v["url"]
        title = a["_meta"].get("title") or v.get("title") or v["id"]
        links = []
        for area in AREAS:
            for t in (a.get("areas") or {}).get(area) or []:
                if not isinstance(t, dict) or not t.get("technique"):
                    continue
                s = slug(t["technique"])
                techniques[area].setdefault(s, {"name": t["technique"], "uses": []})["uses"].append({"vid": v["id"], "title": title, "url": url, **t})
                links.append(f"[[{area}/{s}|{t['technique']}]]")
        sc = a.get("scores") or {}
        L = [f"# {title}", "", f"[Watch on YouTube]({url})", "", f"Provenance: {a['_meta'].get('provenance')} · model `{a['_meta'].get('model')}`", "",
             "| channel_context | self_interest | style_copy | confidence |", "|---|---|---|---|",
             f"| {sc.get('channel_context')} | {sc.get('self_interest')} | {sc.get('style_copy')} | {a.get('confidence')} |", "",
             "Flags: " + ", ".join(k for k, x in (a.get("flags") or {}).items() if x), "", "Tools: " + ", ".join(map(str, a.get("tools_detected") or [])), "",
             "## Summary", str(a.get("summary", "")), "", "## Channel idea", str(a.get("channel_idea", "")), "",
             "## Topics", *[f"- {x}" for x in a.get("topics") or []], "", "## Key ideas", *[f"- {x}" for x in a.get("key_ideas") or []], "",
             "## Techniques", *[f"- {x}" for x in links], "", "## Measured", "```json", json.dumps(a.get("measured"), indent=1), "```", "", "Back to [[index]]"]
        (kb / "video_index").mkdir(parents=True, exist_ok=True)
        (kb / "video_index" / f"{v['id']}.md").write_text("\n".join(L) + "\n", "utf-8")
        written += 1
        index.append((v["id"], title, sc))
    for area, items in techniques.items():
        (kb / area).mkdir(parents=True, exist_ok=True)
        for s, it in items.items():
            L = [f"# {it['name']}", "", f"Area: [[{area}]]", ""]
            for u in it["uses"]:
                L += [f"## From [[video_index/{u['vid']}|{u['title']}]]", f"- {u.get('detail', '')}", f"- Why it matters: {u.get('why_it_matters', '')}",
                      f"- Apply for JR: {u.get('apply_for_jr', '')}"]
                if u.get("quote"):
                    L.append(f"> \"{u['quote']}\" ({u.get('timestamp', '?')}) - [Watch on YouTube]({u['url']})")
                L.append("")
            (kb / area / f"{s}.md").write_text("\n".join(L), "utf-8")
            written += 1
        (kb / f"{area}.md").write_text(f"# {area.capitalize()}\n\n" + "\n".join(f"- [[{area}/{s}|{it['name']}]] ({len(it['uses'])})" for s, it in sorted(items.items())) + "\n\nBack to [[index]]\n", "utf-8")
    imp = sorted(p.stem for p in (kb / "_imported").glob("*.json"))
    L = ["# YouTube research KB", "", f"Updated {time.strftime('%Y-%m-%d %H:%M')} · playlist {j.get('playlist_title')}", "", "## Areas", *[f"- [[{a}]] ({len(techniques[a])})" for a in AREAS],
         "", "## Videos", *[f"- [[video_index/{vid}|{t}]] - cc {s.get('channel_context')} / si {s.get('self_interest')} / sc {s.get('style_copy')}" for vid, t, s in index],
         "", f"## Imported from Hermes ({len(imp)})", *[f"- {x} (see _imported/{x}.json)" for x in imp]]
    (kb / "index.md").write_text("\n".join(L) + "\n", "utf-8")
    pids = set(_rj(kb / "processed_ids.json", []) or []) | {vid for vid, _, _ in index}
    _wj(kb / "processed_ids.json", sorted(pids))
    return written


# -- spec API: preview/estimate, per-video detail, technique library --

def _visual_stats(tid: str, j: dict) -> dict:
    td = _tdir(tid)
    frames = [str(td / v["id"] / f["file"]) for v in j["videos"] for f in ((_rj(td / v["id"] / "frames.json", {}) or {}).get("frames") or [])[::3]][:300]
    out = {}
    py = research_python()
    if frames and py:
        r = _run([py, str(TOOLS_DIR / "palette.py"), str(td / "palette.json")] + frames, timeout=600)
        pal = _rj(td / "palette.json") if r.returncode == 0 else None
        if pal:
            out["palette"] = pal["palette"]
    ocr = [(o, v["id"]) for v in j["videos"] for o in ((_rj(td / v["id"] / "ocr.json", {}) or {}).get("frames") or [])]
    lines = [ln for o, _ in ocr for ln in o.get("lines") or []]
    if ocr:
        hs = sorted(ln["bbox"][3] for ln in lines if isinstance(ln.get("bbox"), list) and len(ln["bbox"]) == 4) if lines else []
        ys = [ln["bbox"][1] for ln in lines if isinstance(ln.get("bbox"), list) and len(ln["bbox"]) == 4]
        txt = [ln.get("text", "") for ln in lines]
        spans = [s for v in j["videos"] for s in ocr_spans(tid, v["id"])]
        out["text"] = {"frames_with_text_pct": round(100 * sum(1 for o, _ in ocr if o.get("text")) / len(ocr), 1),
                       "median_line_height_rel": hs[len(hs) // 2] if hs else None,
                       "position": {k: sum(1 for y in ys if f(y)) for k, f in (("bottom", lambda y: y < 0.33), ("middle", lambda y: 0.33 <= y < 0.66), ("top", lambda y: y >= 0.66))},
                       "uppercase_pct": round(100 * sum(1 for t in txt if t.isupper()) / len(txt), 1) if txt else None,
                       "median_hold_s": sorted(s["t_end"] - s["t"] for s in spans)[len(spans) // 2] if spans else None,
                       "note": "Apple Vision bbox (normalised, origin bottom-left); font/colour not measured"}
    aus = [_rj(td / v["id"] / "audio.json", {}) or {} for v in j["videos"]]
    lb = [a.get("librosa") or {} for a in aus if a.get("librosa")]
    if aus:
        tempos = sorted(x["tempo_bpm"] for x in lb if isinstance(x.get("tempo_bpm"), (int, float)))
        lufs = sorted(x for a in aus if isinstance(x := (a.get("ffmpeg") or {}).get("integrated_lufs"), (int, float)))
        out["music"] = {"videos_music_likely": sum(1 for x in lb if x.get("music_likely")), "videos_with_audio_features": len(lb),
                        "median_tempo_bpm": tempos[len(tempos) // 2] if tempos else None, "median_integrated_lufs": lufs[len(lufs) // 2] if lufs else None,
                        "note": "music_likely is a beat-strength heuristic, not a classifier"}
    return out


def ocr_spans(tid: str, vid: str) -> list:
    """Merge consecutive OCR frames with the same text into spans {t, t_end, text}."""
    fr = sorted(((_rj(_vdir(tid, vid) / "ocr.json", {}) or {}).get("frames") or []), key=lambda o: o.get("t") or 0)
    cuts = (_rj(_vdir(tid, vid) / "cuts.json", {}) or {}).get("cuts") or []
    dur = (_rj(_vdir(tid, vid) / "meta.json", {}) or {}).get("duration") or 0
    spans = []
    for i, o in enumerate(fr):
        txt = " ".join((o.get("text") or "").split())
        nxt = fr[i + 1]["t"] if i + 1 < len(fr) else (next((c for c in cuts if c > (o.get("t") or 0)), dur) or (o.get("t") or 0))
        if not txt:
            continue
        if spans and spans[-1]["text"] == txt and abs(spans[-1]["t_end"] - (o.get("t") or 0)) < 0.5:
            spans[-1]["t_end"] = round(nxt, 2)
        else:
            spans.append({"t": o.get("t"), "t_end": round(nxt, 2), "text": txt[:300]})
    return spans


def video_detail(tid: str, vid: str) -> dict:
    if not _VID.match(vid):
        raise YtError(404, "no such video")
    j = _job(tid)
    v = next((x for x in j["videos"] if x["id"] == vid), None)
    if not v:
        raise YtError(404, "no such video in this job")
    d = _vdir(tid, vid)
    cuts = _rj(d / "cuts.json", {}) or {}
    return {"video": v, "meta": _rj(d / "meta.json"), "transcript": _rj(d / "transcript.json"), "words": _rj(d / "words.json"),
            "frames": (_rj(d / "frames.json", {}) or {}).get("frames"), "cuts": {k: cuts.get(k) for k in ("count", "cuts_per_minute", "avg_shot_s", "threshold")},
            "cut_list": cuts.get("shots") or [], "ocr_spans": ocr_spans(tid, vid), "ocr": _rj(d / "ocr.json"), "audio": _rj(d / "audio.json"),
            "shot_notes": _rj(d / "shot_notes.json"), "timeline": _rj(d / "timeline.json"), "analysis": _rj(d / "analysis.json"),
            "media": {"playable": False, "open_url": v["url"], "note": "no local video is kept (temp files are deleted); use frames or open on YouTube at a timestamp (&t=<s>s)"}}


def techniques(q: str = "", type_: str = "", creator: str = "") -> dict:
    """Technique library across every job: one entry per (area, slug) with timestamped examples."""
    lib = {}
    root = _root()
    for jp in sorted(root.glob("*/job.json")) if root.is_dir() else []:
        j = _rj(jp)
        if not isinstance(j, dict):
            continue
        for v in j["videos"]:
            a = _rj(jp.parent / v["id"] / "analysis.json")
            if not a:
                continue
            ch = (_rj(jp.parent / v["id"] / "meta.json", {}) or {}).get("channel") or v.get("channel")
            for area, items in (a.get("areas") or {}).items():
                for t in items or []:
                    if not isinstance(t, dict) or not t.get("technique"):
                        continue
                    tid_ = f"{area}/{slug(t['technique'])}"
                    e = lib.setdefault(tid_, {"id": tid_, "name": t["technique"], "type": area, "description": t.get("detail") or "", "examples": [], "creators": set(), "sources": {}})
                    e["examples"].append({"task_id": j["task_id"], "video_id": v["id"], "title": a["_meta"].get("title"), "t": t.get("timestamp"), "quote": t.get("quote"),
                                          "why_it_matters": t.get("why_it_matters"), "apply_for_jr": t.get("apply_for_jr")})
                    if ch:
                        e["creators"].add(ch)
                    e["sources"][j["task_id"]] = e["sources"].get(j["task_id"], 0) + 1
    out = []
    ql = q.lower()
    for e in lib.values():
        if type_ and e["type"] != type_:
            continue
        if creator and creator not in e["creators"]:
            continue
        if ql and ql not in (e["name"] + " " + e["description"]).lower():
            continue
        out.append({**e, "creators": sorted(e["creators"]), "clips": len(e["examples"]), "sources": [{"task_id": k, "count": c} for k, c in e["sources"].items()]})
    out.sort(key=lambda e: (-e["clips"], e["name"]))
    return {"techniques": out, "count": len(out), "types": list(AREAS)}


EST = {"meta_s": 4, "captions_s": 6, "whisper_rtf": 0.12, "frames_s_per_min": 6, "ocr_s_per_frame": 0.4, "audio_s_per_min": 3,
       "vlm_s_per_seq": 25, "llm_s_per_call": 70, "lowres_mb_per_min": 6, "kept_mb_per_video": 4, "tokens_per_llm_call": 6000}


def preview(body: dict) -> dict:
    """Title/count/duration before starting, plus a rough estimate (heuristic constants in EST; not measured)."""
    lid = resolve_list(body.get("playlist_url") or body.get("url") or "")
    n = max(1, min(int(body.get("max_videos") or 40), 5000))
    pl = list_playlist(lid, n)
    ents = pl["entries"]
    mins = sum((e.get("duration") or 0) for e in ents) / 60
    e = EST
    whisper_share = float(body.get("assume_whisper_share", 0.5))
    secs = (len(ents) * (e["meta_s"] + e["captions_s"] + SEQ_CUTS * e["vlm_s_per_seq"] + 3 * e["llm_s_per_call"] + MAX_FRAMES * e["ocr_s_per_frame"])
            + mins * 60 * e["whisper_rtf"] * whisper_share + mins * (e["frames_s_per_min"] + e["audio_s_per_min"])
            + sum(e["llm_s_per_call"] * ((d or 0) // 600) for d in (x.get("duration") for x in ents)))
    cfg = {}
    rm = _deps.get("rm")
    if rm:
        with contextlib.suppress(Exception):
            cfg = rm.config()["model_gb"]
    return {"playlist_id": lid, "title": pl.get("title"), "channel": pl.get("channel"), "item_count": pl.get("item_count"), "listing": pl.get("listing"),
            "videos": len(ents), "capped_at": n, "total_minutes": round(mins, 1), "longest_s": max((x.get("duration") or 0) for x in ents) if ents else 0,
            "entries": ents[:200],
            "estimate": {"minutes": round(secs / 60), "disk_gb_peak_temp": round(max((x.get("duration") or 0) for x in ents) / 60 * e["lowres_mb_per_min"] * IO_WORKERS / 1024, 2) if ents else 0,
                         "disk_gb_kept": round(len(ents) * e["kept_mb_per_video"] / 1024, 2), "tokens": int(len(ents) * 3 * e["tokens_per_llm_call"]),
                         "peak_mem_gb": max(cfg.get("gemma4:12b", 9.5), cfg.get("qwen3-vl:8b", 7.0)), "basis": "heuristic constants (EST), not a measurement",
                         "assume_whisper_share": whisper_share}}
