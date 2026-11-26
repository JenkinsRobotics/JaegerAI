"""Episode 01+ Media Production helpers: OpenTimelineIO (.otio) export & Timestamped Media Archive.

Implements Directive §7.1–7.6:
- Export any YouTube Studio episode timeline as a valid OpenTimelineIO
  ``Timeline.1`` JSON document ready for DaVinci Resolve, Premiere, FCP, or Blender.
- Durable SQLite WAL ``MediaArchiveStore`` organizing captured camera, screen,
  gameplay, and audio assets by timestamp, project, channel, transcript, and
  explicit ``is_reconstructed`` truth provenance (Directive §7.4).
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Mapping

from .studio import EpisodeRecord


def export_episode_to_otio(episode: EpisodeRecord, *, fps: float = 24.0) -> dict[str, Any]:
    """Export an EpisodeRecord's multi-track timeline to OpenTimelineIO Timeline.1 JSON."""
    tracks_by_kind: dict[str, list[dict[str, Any]]] = {
        "video": [],
        "broll": [],
        "voiceover": [],
        "music": [],
    }
    for clip in episode.timeline_clips:
        kind = str(clip.get("track") or "video").lower()
        bucket = tracks_by_kind.setdefault(kind, [])
        start_s = float(clip.get("startSec") or 0.0)
        dur_s = max(0.5, float(clip.get("durationSec") or 1.0))
        bucket.append({
            "OTIO_SCHEMA": "Clip.2",
            "name": str(clip.get("label") or clip.get("id") or "Clip"),
            "source_range": {
                "OTIO_SCHEMA": "TimeRange.1",
                "start_time": {"OTIO_SCHEMA": "RationalTime.1", "rate": fps, "value": round(start_s * fps, 2)},
                "duration": {"OTIO_SCHEMA": "RationalTime.1", "rate": fps, "value": round(dur_s * fps, 2)},
            },
            "media_reference": {
                "OTIO_SCHEMA": "ExternalReference.1",
                "target_url": str(clip.get("sourceUrl") or f"jaeger://episode/{episode.episode_id}/{clip.get('id', 'clip')}"),
            },
            "metadata": {"jaeger_track": kind, "clip_id": clip.get("id")},
        })

    otio_tracks: list[dict[str, Any]] = []
    for tname, clips in tracks_by_kind.items():
        if not clips:
            continue
        otio_kind = "Audio" if tname in ("voiceover", "music") else "Video"
        otio_tracks.append({
            "OTIO_SCHEMA": "Track.1",
            "name": tname,
            "kind": otio_kind,
            "children": clips,
        })

    return {
        "OTIO_SCHEMA": "Timeline.1",
        "name": episode.title,
        "global_start_time": {"OTIO_SCHEMA": "RationalTime.1", "rate": fps, "value": 0.0},
        "metadata": {
            "jaeger_episode_id": episode.episode_id,
            "stage": episode.stage,
            "owner_approved": episode.owner_approved,
            "fps": fps,
        },
        "tracks": {
            "OTIO_SCHEMA": "Stack.1",
            "name": "tracks",
            "children": otio_tracks,
        },
    }


@dataclass(slots=True)
class ArchivedMediaItem:
    asset_id: str
    kind: str  # camera | screen | gameplay | audio | photo | render
    project_id: str
    channel_tag: str
    source_path: str
    scene_description: str
    transcript: str
    is_reconstructed: bool
    tags: list[str] = field(default_factory=list)
    captured_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class MediaArchiveStore:
    """Timestamped SQLite WAL archive distinguishing genuine recordings from reconstructions (§7.3–7.4)."""

    def __init__(self, state_dir: Path) -> None:
        self._dir = Path(state_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._db = self._dir / "media_archive.sqlite3"
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
                CREATE TABLE IF NOT EXISTS media_archive (
                    asset_id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    channel_tag TEXT NOT NULL,
                    source_path TEXT NOT NULL,
                    scene_description TEXT NOT NULL,
                    transcript TEXT NOT NULL,
                    is_reconstructed INTEGER NOT NULL,
                    tags_json TEXT NOT NULL,
                    captured_at REAL NOT NULL
                )
                """
            )

    def add(
        self,
        *,
        kind: str,
        source_path: str,
        project_id: str = "general",
        channel_tag: str = "",
        scene_description: str = "",
        transcript: str = "",
        is_reconstructed: bool = False,
        tags: list[str] | None = None,
        captured_at: float | None = None,
    ) -> ArchivedMediaItem:
        aid = f"med_{uuid.uuid4().hex[:10]}"
        item = ArchivedMediaItem(
            asset_id=aid,
            kind=kind,
            project_id=project_id,
            channel_tag=channel_tag,
            source_path=source_path,
            scene_description=scene_description,
            transcript=transcript,
            is_reconstructed=bool(is_reconstructed),
            tags=list(tags or []),
            captured_at=time.time() if captured_at is None else float(captured_at),
        )
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO media_archive (
                    asset_id, kind, project_id, channel_tag, source_path,
                    scene_description, transcript, is_reconstructed, tags_json, captured_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item.asset_id,
                    item.kind,
                    item.project_id,
                    item.channel_tag,
                    item.source_path,
                    item.scene_description,
                    item.transcript,
                    1 if item.is_reconstructed else 0,
                    json.dumps(item.tags),
                    item.captured_at,
                ),
            )
        return item

    def search(
        self,
        *,
        query: str = "",
        project_id: str | None = None,
        kind: str | None = None,
        limit: int = 50,
    ) -> list[ArchivedMediaItem]:
        clauses: list[str] = []
        args: list[Any] = []
        if project_id:
            clauses.append("project_id = ?")
            args.append(project_id)
        if kind:
            clauses.append("kind = ?")
            args.append(kind)
        if query.strip():
            like = f"%{query.strip()}%"
            clauses.append("(scene_description LIKE ? OR transcript LIKE ? OR tags_json LIKE ? OR source_path LIKE ?)")
            args.extend([like, like, like, like])
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        args.append(int(limit))
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT asset_id, kind, project_id, channel_tag, source_path,
                       scene_description, transcript, is_reconstructed, tags_json, captured_at
                FROM media_archive {where}
                ORDER BY captured_at DESC LIMIT ?
                """,
                args,
            ).fetchall()
        return [
            ArchivedMediaItem(
                asset_id=r[0],
                kind=r[1],
                project_id=r[2],
                channel_tag=r[3],
                source_path=r[4],
                scene_description=r[5],
                transcript=r[6],
                is_reconstructed=bool(r[7]),
                tags=json.loads(r[8] or "[]"),
                captured_at=float(r[9]),
            )
            for r in rows
        ]


__all__ = ["ArchivedMediaItem", "MediaArchiveStore", "export_episode_to_otio"]
