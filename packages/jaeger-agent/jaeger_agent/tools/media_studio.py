"""Video & YouTube production studio tools (FFmpeg / FFprobe + Research KB).

Gives Jaeger first-class media rendering capabilities on macOS without requiring
fragile shell quoting:
  - ``probe_media``: inspect video/audio/image streams, duration, fps, codecs.
  - ``render_video``: trim, concat, mux voiceover+video, image/avatar+audio to
    1080p YouTube MP4, extract audio, extract thumbnails, burn SRT captions.
  - ``youtube_studio``: inspect local YouTube production toolchain, search the
    researched YouTube style/notes KB, or pull a video's metadata/transcript.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from jaeger_os.core.safety.permissions import PermissionTier, requires_tier
from jaeger_os.core.tools.tool_registry import register_tool_from_function
from jaeger_agent.core.workspace import (
    SandboxError,
    _audit,
    _resolve_read,
    _resolve_write,
)

_FFMPEG_TIMEOUT_S = 300.0
_PROBE_TIMEOUT_S = 20.0
_RES_RE = re.compile(r"^(\d{2,4})x(\d{2,4})$")
_TIME_RE = re.compile(r"^[0-9:.]+$")


def _which_media(binary: str) -> str | None:
    found = shutil.which(binary)
    if found:
        return found
    for prefix in ("/opt/homebrew/bin", "/usr/local/bin"):
        cand = Path(prefix) / binary
        if cand.is_file() and os.access(cand, os.X_OK):
            return str(cand)
    return None


def _parse_fps(rate_str: str) -> float | None:
    if not rate_str or rate_str == "0/0":
        return None
    if "/" in rate_str:
        num, den = rate_str.split("/", 1)
        try:
            d = float(den)
            return round(float(num) / d, 3) if d else None
        except ValueError:
            return None
    try:
        return round(float(rate_str), 3)
    except ValueError:
        return None


def probe_media(path: str) -> dict[str, Any]:
    """Inspect a media file (video, audio, or image) with ``ffprobe``."""
    ffprobe = _which_media("ffprobe")
    if not ffprobe:
        return {"ok": False, "error": "ffprobe is not installed (brew install ffmpeg)"}
    try:
        target = _resolve_read(path)
    except SandboxError as exc:
        return {"ok": False, "error": str(exc)}
    if not target.is_file():
        return {"ok": False, "error": f"media file not found: {target}"}

    cmd = [
        ffprobe,
        "-v", "error",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        str(target),
    ]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=_PROBE_TIMEOUT_S, stdin=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"ffprobe timed out after {_PROBE_TIMEOUT_S}s"}
    if proc.returncode != 0:
        return {"ok": False, "error": (proc.stderr or proc.stdout or "ffprobe failed").strip()[:800]}

    try:
        raw = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError as exc:
        return {"ok": False, "error": f"invalid ffprobe JSON: {exc}"}

    fmt = raw.get("format") or {}
    video: dict[str, Any] | None = None
    audio: dict[str, Any] | None = None
    for st in raw.get("streams") or []:
        ctype = st.get("codec_type")
        if ctype == "video" and video is None:
            video = {
                "codec": st.get("codec_name"),
                "width": st.get("width"),
                "height": st.get("height"),
                "fps": _parse_fps(str(st.get("r_frame_rate") or "")),
                "pix_fmt": st.get("pix_fmt"),
            }
        elif ctype == "audio" and audio is None:
            audio = {
                "codec": st.get("codec_name"),
                "sample_rate": int(st["sample_rate"]) if str(st.get("sample_rate", "")).isdigit() else None,
                "channels": st.get("channels"),
            }

    duration = None
    try:
        if fmt.get("duration") is not None:
            duration = round(float(fmt["duration"]), 3)
    except (TypeError, ValueError):
        pass

    return {
        "ok": True,
        "path": str(target),
        "format": fmt.get("format_name"),
        "duration_s": duration,
        "size_bytes": target.stat().st_size,
        "bit_rate": int(fmt["bit_rate"]) if str(fmt.get("bit_rate", "")).isdigit() else None,
        "video": video,
        "audio": audio,
    }


def _safe_resolution(res: str) -> tuple[int, int]:
    m = _RES_RE.match((res or "").strip().lower())
    if not m:
        return (1920, 1080)
    w = max(64, min(3840, int(m.group(1))))
    h = max(64, min(2160, int(m.group(2))))
    # libx264 / yuv420p requires even dimensions.
    return (w - (w % 2), h - (h % 2))


def _safe_time(val: str) -> str:
    s = (val or "").strip()
    if not s:
        return ""
    if not _TIME_RE.match(s):
        raise ValueError(f"invalid timestamp/duration {val!r}; use seconds or HH:MM:SS")
    return s


def render_video(
    operation: str,
    inputs: list[str],
    output_path: str,
    start: str = "",
    duration: str = "",
    resolution: str = "1920x1080",
    fps: int = 30,
    subtitle_path: str = "",
) -> dict[str, Any]:
    """Render, edit, or export YouTube-ready media using local FFmpeg.

    Supported ``operation`` values:
      - ``trim``: clip ``inputs[0]`` with ``start`` and/or ``duration``.
      - ``concat``: stitch multiple clips ``inputs`` into one YouTube 1080p MP4.
      - ``mux_audio``: combine video ``inputs[0]`` + audio/voiceover ``inputs[1]``.
      - ``image_to_video``: combine image/avatar ``inputs[0]`` + audio ``inputs[1]`` (or ``duration``).
      - ``extract_audio``: extract audio track from ``inputs[0]`` (WAV/MP3/M4A).
      - ``thumbnail``: extract a 1280x720 thumbnail PNG/JPG from ``inputs[0]`` at ``start``.
      - ``burn_subtitles``: burn ``subtitle_path`` (.srt) into ``inputs[0]``.
    """
    ffmpeg = _which_media("ffmpeg")
    if not ffmpeg:
        return {"ok": False, "error": "ffmpeg is not installed (brew install ffmpeg)"}

    op = (operation or "").strip().lower()
    valid_ops = {"trim", "concat", "mux_audio", "image_to_video", "extract_audio", "thumbnail", "burn_subtitles"}
    if op not in valid_ops:
        return {"ok": False, "error": f"unknown operation {operation!r}; choose from {sorted(valid_ops)}"}
    if not inputs:
        return {"ok": False, "error": "inputs must contain at least one input media path"}

    try:
        resolved_inputs = [_resolve_read(p) for p in inputs]
        target_out = _resolve_write(output_path)
        start_s = _safe_time(start)
        dur_s = _safe_time(duration)
    except (SandboxError, ValueError) as exc:
        return {"ok": False, "error": str(exc)}

    for inp in resolved_inputs:
        if not inp.is_file():
            return {"ok": False, "error": f"input file not found: {inp}"}

    target_out.parent.mkdir(parents=True, exist_ok=True)
    w, h = _safe_resolution(resolution)
    safe_fps = max(1, min(60, int(fps or 30)))

    cmd: list[str] = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error"]
    temp_files: list[Path] = []

    try:
        if op == "trim":
            if start_s:
                cmd += ["-ss", start_s]
            cmd += ["-i", str(resolved_inputs[0])]
            if dur_s:
                cmd += ["-t", dur_s]
            cmd += [
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
                "-movflags", "+faststart", str(target_out),
            ]
        elif op == "concat":
            if len(resolved_inputs) < 2:
                return {"ok": False, "error": "concat requires at least 2 input clips"}
            # Re-encode through concat filter so clips with differing codecs/fps/resolutions merge reliably.
            for inp in resolved_inputs:
                cmd += ["-i", str(inp)]
            fc_parts: list[str] = []
            concat_inputs: list[str] = []
            for idx, inp in enumerate(resolved_inputs):
                has_audio = bool((probe_media(str(inp)).get("audio")))
                fc_parts.append(
                    f"[{idx}:v]scale={w}:{h}:force_original_aspect_ratio=decrease,"
                    f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,fps={safe_fps},format=yuv420p,setsar=1[v{idx}]"
                )
                if has_audio:
                    fc_parts.append(f"[{idx}:a]aresample=48000,aformat=channel_layouts=stereo[a{idx}]")
                else:
                    info = probe_media(str(inp))
                    clip_dur = float(info.get("duration_s") or 1.0)
                    fc_parts.append(f"anullsrc=r=48000:cl=stereo:d={clip_dur:.3f}[a{idx}]")
                concat_inputs.append(f"[v{idx}][a{idx}]")
            fc_parts.append(f"{''.join(concat_inputs)}concat=n={len(resolved_inputs)}:v=1:a=1[vout][aout]")
            cmd += [
                "-filter_complex", ";".join(fc_parts),
                "-map", "[vout]", "-map", "[aout]",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(target_out),
            ]
        elif op == "mux_audio":
            if len(resolved_inputs) < 2:
                return {"ok": False, "error": "mux_audio requires [video_path, audio_path]"}
            cmd += [
                "-i", str(resolved_inputs[0]),
                "-i", str(resolved_inputs[1]),
                "-map", "0:v:0", "-map", "1:a:0",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "192k", "-shortest",
                "-movflags", "+faststart", str(target_out),
            ]
        elif op == "image_to_video":
            cmd += ["-loop", "1", "-framerate", str(safe_fps), "-i", str(resolved_inputs[0])]
            if len(resolved_inputs) >= 2:
                cmd += ["-i", str(resolved_inputs[1])]
            elif dur_s:
                cmd += ["-t", dur_s]
            else:
                cmd += ["-t", "5"]
            vf = (
                f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
                f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,format=yuv420p"
            )
            cmd += [
                "-vf", vf,
                "-c:v", "libx264", "-tune", "stillimage", "-preset", "veryfast", "-crf", "20",
                "-pix_fmt", "yuv420p",
            ]
            if len(resolved_inputs) >= 2:
                cmd += ["-c:a", "aac", "-b:a", "192k", "-shortest"]
            cmd += ["-movflags", "+faststart", str(target_out)]
        elif op == "extract_audio":
            cmd += ["-i", str(resolved_inputs[0]), "-vn"]
            ext = target_out.suffix.lower()
            if ext == ".wav":
                cmd += ["-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le"]
            elif ext == ".mp3":
                cmd += ["-c:a", "libmp3lame", "-q:a", "2"]
            else:
                cmd += ["-c:a", "aac", "-b:a", "192k"]
            cmd.append(str(target_out))
        elif op == "thumbnail":
            ts = start_s or "00:00:01"
            tw, th = _safe_resolution(resolution if resolution != "1920x1080" else "1280x720")
            vf = f"scale={tw}:{th}:force_original_aspect_ratio=decrease,pad={tw}:{th}:(ow-iw)/2:(oh-ih)/2"
            cmd += ["-ss", ts, "-i", str(resolved_inputs[0]), "-frames:v", "1", "-vf", vf, str(target_out)]
        elif op == "burn_subtitles":
            if not subtitle_path:
                return {"ok": False, "error": "burn_subtitles requires subtitle_path (.srt)"}
            sub = _resolve_read(subtitle_path)
            if not sub.is_file():
                return {"ok": False, "error": f"subtitle file not found: {sub}"}
            # Copy subtitle to a simple temp path without colons/quotes for FFmpeg subtitles filter safety.
            tmp_sub = Path(tempfile.mkstemp(prefix="jaeger_sub_", suffix=".srt")[1])
            tmp_sub.write_bytes(sub.read_bytes())
            temp_files.append(tmp_sub)
            escaped = str(tmp_sub).replace("\\", "\\\\").replace(":", "\\:")
            cmd += [
                "-i", str(resolved_inputs[0]),
                "-vf", f"subtitles={escaped}",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
                "-c:a", "copy", "-movflags", "+faststart", str(target_out),
            ]

        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=_FFMPEG_TIMEOUT_S, stdin=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"ffmpeg {op} timed out after {_FFMPEG_TIMEOUT_S}s"}
    except SandboxError as exc:
        return {"ok": False, "error": str(exc)}
    finally:
        for tf in temp_files:
            try:
                tf.unlink(missing_ok=True)
            except OSError:
                pass

    if proc.returncode != 0:
        return {
            "ok": False,
            "operation": op,
            "error": (proc.stderr or proc.stdout or f"ffmpeg exited {proc.returncode}").strip()[:1200],
        }

    _audit("render_video", {"operation": op, "output": str(target_out)})
    probed = probe_media(str(target_out))
    return {
        "ok": True,
        "operation": op,
        "output_path": str(target_out),
        "size_bytes": target_out.stat().st_size if target_out.is_file() else 0,
        "media": probed if probed.get("ok") else None,
    }


def _kb_root() -> Path:
    state = Path(os.environ.get("JAEGER_STATE_HOME") or os.environ.get("JAEGER_STATE_DIR") or (Path.home() / ".jaeger"))
    return state / "research" / "kb"


def youtube_studio(
    action: str = "status",
    query: str = "",
    url_or_id: str = "",
    limit: int = 10,
) -> dict[str, Any]:
    """YouTube channel production & research helper.

    Actions:
      - ``status``: check local ffmpeg, ffprobe, yt-dlp, whisper-cli, and KB docs.
      - ``kb_search``: search your researched YouTube style guides & notes in ``~/.jaeger/research/kb``.
      - ``transcript``: fetch metadata & captions/transcript for a YouTube video via ``yt-dlp``.
    """
    act = (action or "status").strip().lower()
    kb = _kb_root()

    if act == "status":
        kb_files = sorted(kb.rglob("*.md")) if kb.is_dir() else []
        return {
            "ok": True,
            "tools": {
                "ffmpeg": _which_media("ffmpeg"),
                "ffprobe": _which_media("ffprobe"),
                "yt_dlp": _which_media("yt-dlp"),
                "whisper_cli": _which_media("whisper-cli"),
            },
            "research_kb_dir": str(kb),
            "research_kb_docs": len(kb_files),
        }

    if act == "kb_search":
        if not kb.is_dir():
            return {"ok": True, "kb_dir": str(kb), "matches": [], "note": "No YouTube research KB directory yet."}
        q = (query or "").strip().lower()
        cap = max(1, min(30, int(limit or 10)))
        matches: list[dict[str, Any]] = []
        for md in sorted(kb.rglob("*.md")):
            try:
                text = md.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if q and q not in text.lower() and q not in md.name.lower():
                continue
            snippet = text[:500].strip()
            if q:
                idx = text.lower().find(q)
                if idx >= 0:
                    start_i = max(0, idx - 120)
                    snippet = text[start_i:start_i + 420].strip()
            matches.append({"path": str(md), "name": md.name, "snippet": snippet})
            if len(matches) >= cap:
                break
        return {"ok": True, "query": query, "count": len(matches), "matches": matches}

    if act == "transcript":
        yt_dlp = _which_media("yt-dlp")
        if not yt_dlp:
            return {"ok": False, "error": "yt-dlp is not installed (brew install yt-dlp)"}
        target = (url_or_id or "").strip()
        if not target:
            return {"ok": False, "error": "url_or_id is required for action='transcript'"}
        if re.fullmatch(r"[A-Za-z0-9_-]{11}", target):
            target = f"https://www.youtube.com/watch?v={target}"
        with tempfile.TemporaryDirectory(prefix="jaeger_yt_") as td:
            out_tpl = str(Path(td) / "%(id)s.%(ext)s")
            cmd = [
                yt_dlp,
                "--skip-download",
                "--write-auto-sub",
                "--write-sub",
                "--sub-lang", "en",
                "--sub-format", "vtt/srt/best",
                "--dump-single-json",
                "-o", out_tpl,
                target,
            ]
            try:
                proc = subprocess.run(cmd, capture_output=True, text=True, timeout=45, stdin=subprocess.DEVNULL)
            except subprocess.TimeoutExpired:
                return {"ok": False, "error": "yt-dlp transcript fetch timed out after 45s"}
            meta: dict[str, Any] = {}
            if proc.stdout.strip():
                try:
                    raw_meta = json.loads(proc.stdout.splitlines()[-1])
                    meta = {
                        "id": raw_meta.get("id"),
                        "title": raw_meta.get("title"),
                        "channel": raw_meta.get("channel") or raw_meta.get("uploader"),
                        "duration_s": raw_meta.get("duration"),
                        "view_count": raw_meta.get("view_count"),
                        "upload_date": raw_meta.get("upload_date"),
                        "description": str(raw_meta.get("description") or "")[:1000],
                    }
                except Exception:
                    pass
            sub_files = sorted(Path(td).glob("*.vtt")) + sorted(Path(td).glob("*.srt"))
            transcript_text = ""
            if sub_files:
                raw_sub = sub_files[0].read_text(encoding="utf-8", errors="ignore")
                lines: list[str] = []
                prev = ""
                for line in raw_sub.splitlines():
                    s = re.sub(r"<[^>]+>", "", line).strip()
                    if not s or s.startswith("WEBVTT") or s.startswith("Kind:") or s.startswith("Language:") or "-->" in s or s.isdigit():
                        continue
                    if s != prev:
                        lines.append(s)
                        prev = s
                transcript_text = " ".join(lines)[:12_000]
            if not meta and not transcript_text:
                return {"ok": False, "error": (proc.stderr or "yt-dlp returned no metadata/captions").strip()[:800]}
            return {
                "ok": True,
                "meta": meta,
                "has_transcript": bool(transcript_text),
                "transcript": transcript_text,
            }

    return {"ok": False, "error": f"unknown action {action!r}; choose from status, kb_search, transcript"}


@register_tool_from_function(name="probe_media", side_effect="read")
@requires_tier(PermissionTier.READ_ONLY, skill="media", operation="probe_media",
               summary="inspect a video, audio, or image file with ffprobe")
def _t_probe_media(path: str) -> dict[str, Any]:
    """Inspect a media file's duration, resolution, fps, codecs, and audio streams via ffprobe."""
    return probe_media(path=path)


@register_tool_from_function(name="render_video", side_effect="external")
@requires_tier(PermissionTier.WRITE_LOCAL, skill="media", operation="render_video",
               summary="render or edit a video/audio file with FFmpeg")
def _t_render_video(
    operation: str,
    inputs: list[str],
    output_path: str,
    start: str = "",
    duration: str = "",
    resolution: str = "1920x1080",
    fps: int = 30,
    subtitle_path: str = "",
) -> dict[str, Any]:
    """Render YouTube-ready videos with local FFmpeg.
    operations: trim, concat, mux_audio, image_to_video, extract_audio, thumbnail, burn_subtitles."""
    return render_video(
        operation=operation,
        inputs=inputs,
        output_path=output_path,
        start=start,
        duration=duration,
        resolution=resolution,
        fps=fps,
        subtitle_path=subtitle_path,
    )


@register_tool_from_function(name="youtube_studio", side_effect="read")
@requires_tier(PermissionTier.READ_ONLY, skill="media", operation="youtube_studio",
               summary="inspect YouTube production tools, search research KB, or fetch a transcript")
def _t_youtube_studio(
    action: str = "status",
    query: str = "",
    url_or_id: str = "",
    limit: int = 10,
) -> dict[str, Any]:
    """YouTube production helper: action='status' checks ffmpeg/yt-dlp/KB,
    action='kb_search' searches your style guides & research notes,
    action='transcript' fetches metadata and captions for a YouTube video."""
    return youtube_studio(action=action, query=query, url_or_id=url_or_id, limit=limit)


__all__ = ["probe_media", "render_video", "youtube_studio"]
