"""Flagship YouTube Channel Studio & 32 GB Phased Research Pipeline.

Promoted and modularized from JaegerAI's on-device `youtube_research.py` v2:
- Runs research in 3 memory-safe PHASES across a playlist so ONLY ONE large
  model (either VLM or LLM, never both simultaneously) is resident in 32 GB RAM:
    Phase 1 (CPU / lightweight): meta -> transcript -> frames -> ocr -> audio
    Phase 2 (VLM slot):          shot_notes (qwen3-vl:8b / qwen2.5vl:7b)
    Phase 3 (LLM slot):          timeline -> analysis (gemma4:12b) + style guide KB
- Full YouTube Episode Studio backed by SQLite WAL:
    idea -> research -> script -> storyboard -> edit -> approval_gate -> ready_to_publish
- Emits multi-track NLE clips directly consumable by `@jaeger/ui-kit` `StudioTimeline`.
- Strictly fail-closed: ZERO auto-publishing without explicit owner approval.
"""

from __future__ import annotations

import json
import re
import shutil
import sqlite3
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

STEPS = ("meta", "transcript", "frames", "ocr", "audio", "shot_notes", "timeline", "analysis")
PHASES = (
    ("meta", "transcript", "frames", "ocr", "audio"),
    ("shot_notes",),
    ("timeline", "analysis"),
)
DEFAULT_MODEL = "gemma4:12b"
VLM_PREFS = ("qwen3-vl:8b", "qwen2.5vl:7b", "minicpm-v:latest")
AREAS = ("engineering", "production", "visuals", "sound", "hardware", "software", "narrative")
EPISODE_STAGES = (
    "idea",
    "research",
    "script",
    "storyboard",
    "edit",
    "approval_gate",
    "ready_to_publish",
)
_LIST_RE = re.compile(r"^[A-Za-z0-9_-]{10,64}$")
_VID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")


def probe_youtube_toolchain(ollama_models: list[str] | None = None) -> dict[str, Any]:
    """Detect local YouTube research & studio binaries without mutating system state."""
    models = list(ollama_models or [])
    vlm = next((m for m in VLM_PREFS if m in models), None)
    whisper_model = None
    for root in (Path.home() / ".whisper", Path("/opt/homebrew/share/whisper-cpp")):
        for name in ("ggml-base.en.bin", "ggml-small.en.bin", "ggml-base.bin", "ggml-small.bin"):
            if (root / name).is_file():
                whisper_model = name
                break
        if whisper_model:
            break
    return {
        "yt_dlp": bool(shutil.which("yt-dlp")),
        "ffmpeg": bool(shutil.which("ffmpeg")),
        "whisper_cpp": bool(shutil.which("whisper-cli") and whisper_model),
        "whisper_model": whisper_model,
        "ollama_ready": bool(models),
        "vlm_model": vlm or VLM_PREFS[0],
        "llm_model": DEFAULT_MODEL if DEFAULT_MODEL in models else (models[0] if models else DEFAULT_MODEL),
        "memory_policy": "single_heavy_model_per_phase_32gb",
        "phases": [list(p) for p in PHASES],
        "analysis_areas": list(AREAS),
    }


def plan_phased_research(
    playlist_or_url: str,
    *,
    video_ids: list[str] | None = None,
    llm_model: str = DEFAULT_MODEL,
    vlm_model: str = VLM_PREFS[0],
) -> dict[str, Any]:
    """Build a 32 GB-safe 3-phase execution plan for a YouTube playlist or video set."""
    clean = (playlist_or_url or "").strip()
    vids = [v for v in (video_ids or []) if _VID_RE.match(v)]
    return {
        "source": clean,
        "video_count": len(vids),
        "video_ids": vids,
        "max_concurrent_heavy_models": 1,
        "phases": [
            {
                "phase": 1,
                "name": "CPU Ingestion & Signal Extraction",
                "steps": list(PHASES[0]),
                "heavy_model": None,
                "estimated_ram_gb": 1.2,
                "resumable": True,
            },
            {
                "phase": 2,
                "name": "Visual Cut Analysis (VLM Slot)",
                "steps": list(PHASES[1]),
                "heavy_model": vlm_model,
                "estimated_ram_gb": 8.0,
                "resumable": True,
            },
            {
                "phase": 3,
                "name": "Timeline Merge, 7-Area Scoring & Style Guide KB (LLM Slot)",
                "steps": list(PHASES[2]),
                "heavy_model": llm_model,
                "estimated_ram_gb": 10.5,
                "outputs": ["style_guide.md", "style_guide.json", "obsidian_kb"],
                "resumable": True,
            },
        ],
        "auto_publish": False,
        "safety": "read_only_local_kb",
    }


@dataclass(slots=True)
class EpisodeRecord:
    episode_id: str
    title: str
    topic: str
    stage: str
    target_duration_s: int
    assigned_role: str
    hook: str
    script_md: str
    timeline_clips: list[dict[str, Any]] = field(default_factory=list)
    owner_approved: bool = False
    approval_note: str = ""
    updated_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_default_timeline(title: str, duration_s: int = 480) -> list[dict[str, Any]]:
    """Build a multi-track NLE clip skeleton directly compatible with `@jaeger/ui-kit` StudioTimeline."""
    dur = max(60, int(duration_s))
    hook_end = min(20, max(10, dur // 20))
    body_dur = max(30, dur - hook_end - 30)
    return [
        {"id": "v_hook", "track": "video", "label": f"Cold Open: {title[:28]}", "startSec": 0, "durationSec": hook_end},
        {"id": "v_body", "track": "video", "label": "Main Build & Live Demo", "startSec": hook_end, "durationSec": body_dur},
        {"id": "v_outro", "track": "video", "label": "Recap & Next Milestone", "startSec": hook_end + body_dur, "durationSec": 30},
        {"id": "vo_main", "track": "voiceover", "label": "Kokoro MLX Narration + Lip Marks", "startSec": 2, "durationSec": dur - 6},
        {"id": "broll_1", "track": "broll", "label": "JP01 / Code Close-up B-Roll", "startSec": hook_end + 10, "durationSec": min(45, body_dur // 3)},
        {"id": "bgm_bed", "track": "music", "label": "Ambient Synth Bed (-24 LUFS)", "startSec": 0, "durationSec": dur},
    ]


class YouTubeStudioStore:
    """SQLite WAL backing store for YouTube channel episodes & approval-gated publishing."""

    def __init__(self, state_dir: Path) -> None:
        self._dir = Path(state_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._db = self._dir / "youtube_studio.sqlite3"
        self._lock = threading.RLock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db), timeout=10.0)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _init_db(self) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS episodes (
                    episode_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    topic TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    target_duration_s INTEGER NOT NULL,
                    assigned_role TEXT NOT NULL,
                    hook TEXT NOT NULL,
                    script_md TEXT NOT NULL,
                    timeline_json TEXT NOT NULL,
                    owner_approved INTEGER NOT NULL,
                    approval_note TEXT NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )

    def create_episode(
        self,
        *,
        title: str,
        topic: str = "",
        target_duration_s: int = 480,
        hook: str = "",
        script_md: str = "",
    ) -> EpisodeRecord:
        eid = f"yt_{uuid.uuid4().hex[:10]}"
        now = time.time()
        clean_title = (title or "Untitled Episode").strip()
        rec = EpisodeRecord(
            episode_id=eid,
            title=clean_title,
            topic=(topic or clean_title).strip(),
            stage="idea",
            target_duration_s=max(30, int(target_duration_s)),
            assigned_role="researcher",
            hook=hook or f"Watch {clean_title} run autonomously on a single 32 GB machine.",
            script_md=script_md or f"# {clean_title}\n\n## Cold Open (0:00-0:15)\nHook viewer with live result first.\n",
            timeline_clips=build_default_timeline(clean_title, target_duration_s),
            owner_approved=False,
            approval_note="",
            updated_at=now,
        )
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO episodes (
                    episode_id, title, topic, stage, target_duration_s, assigned_role,
                    hook, script_md, timeline_json, owner_approved, approval_note, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    rec.episode_id,
                    rec.title,
                    rec.topic,
                    rec.stage,
                    rec.target_duration_s,
                    rec.assigned_role,
                    rec.hook,
                    rec.script_md,
                    json.dumps(rec.timeline_clips),
                    0,
                    "",
                    rec.updated_at,
                ),
            )
        return rec

    def _row_to_rec(self, r: tuple[Any, ...]) -> EpisodeRecord:
        return EpisodeRecord(
            episode_id=r[0],
            title=r[1],
            topic=r[2],
            stage=r[3],
            target_duration_s=int(r[4]),
            assigned_role=r[5],
            hook=r[6],
            script_md=r[7],
            timeline_clips=json.loads(r[8] or "[]"),
            owner_approved=bool(r[9]),
            approval_note=r[10],
            updated_at=float(r[11]),
        )

    def get_episode(self, episode_id: str) -> EpisodeRecord | None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                """
                SELECT episode_id, title, topic, stage, target_duration_s, assigned_role,
                       hook, script_md, timeline_json, owner_approved, approval_note, updated_at
                FROM episodes WHERE episode_id = ?
                """,
                (episode_id,),
            ).fetchone()
        return self._row_to_rec(row) if row else None

    def list_episodes(self, *, limit: int = 50) -> list[EpisodeRecord]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                """
                SELECT episode_id, title, topic, stage, target_duration_s, assigned_role,
                       hook, script_md, timeline_json, owner_approved, approval_note, updated_at
                FROM episodes ORDER BY updated_at DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [self._row_to_rec(r) for r in rows]

    def advance_stage(
        self,
        episode_id: str,
        *,
        target_stage: str,
        owner_approved: bool | None = None,
        approval_note: str = "",
    ) -> tuple[bool, str, EpisodeRecord | None]:
        if target_stage not in EPISODE_STAGES:
            return False, f"invalid_stage:{target_stage}", None
        ep = self.get_episode(episode_id)
        if ep is None:
            return False, "episode_not_found", None
        approved = ep.owner_approved if owner_approved is None else bool(owner_approved)
        if target_stage == "ready_to_publish" and not approved:
            return False, "owner_approval_required_before_publish", ep

        role_by_stage = {
            "idea": "producer",
            "research": "researcher",
            "script": "scriptwriter",
            "storyboard": "designer",
            "edit": "editor",
            "approval_gate": "producer",
            "ready_to_publish": "publisher",
        }
        now = time.time()
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                UPDATE episodes
                SET stage = ?, assigned_role = ?, owner_approved = ?, approval_note = ?, updated_at = ?
                WHERE episode_id = ?
                """,
                (
                    target_stage,
                    role_by_stage[target_stage],
                    1 if approved else 0,
                    approval_note or ep.approval_note,
                    now,
                    episode_id,
                ),
            )
        return True, "updated", self.get_episode(episode_id)


__all__ = [
    "AREAS",
    "DEFAULT_MODEL",
    "EPISODE_STAGES",
    "EpisodeRecord",
    "PHASES",
    "STEPS",
    "VLM_PREFS",
    "YouTubeStudioStore",
    "build_default_timeline",
    "plan_phased_research",
    "probe_youtube_toolchain",
]
