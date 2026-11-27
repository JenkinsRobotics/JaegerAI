"""Read-only public video discovery through the YouTube Data API."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


_API_ROOT = "https://www.googleapis.com/youtube/v3"
_VIDEO_ID = re.compile(r"[A-Za-z0-9_-]{11}")
_ERROR_REASON = re.compile(r"[A-Za-z][A-Za-z_]{0,79}")


def _request(resource: str, key: str, **params: str | int) -> dict[str, Any]:
    operation = f"{resource}.list"
    request = Request(
        f"{_API_ROOT}/{resource}?{urlencode(params)}",
        headers={"Accept": "application/json", "X-Goog-Api-Key": key},
    )
    try:
        with urlopen(request, timeout=10) as response:
            data = json.load(response)
    except HTTPError as exc:
        reason = ""
        with exc:
            try:
                error = json.load(exc)["error"]
                reasons = error.get("errors") or []
                candidate = reasons[0]["reason"] if reasons else error.get("status", "")
                if isinstance(candidate, str) and _ERROR_REASON.fullmatch(candidate):
                    reason = f" ({candidate})"
            except (ValueError, KeyError, IndexError, TypeError, AttributeError, OSError):
                pass
        raise RuntimeError(f"YouTube Data API {operation} returned HTTP {exc.code}{reason}.") from None
    except (URLError, OSError):
        raise RuntimeError(f"YouTube Data API {operation} network request failed.") from None
    except ValueError:
        raise RuntimeError(f"YouTube Data API {operation} returned invalid JSON.") from None
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        raise RuntimeError(f"YouTube Data API {operation} returned no items array.")
    return data


def _read_key(state_dir: Path) -> str:
    try:
        key = (state_dir / "secrets" / "youtube_api_key").read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        key = ""
    if not key:
        raise RuntimeError("YouTube Data API key is missing or unreadable in Jaeger state (secrets/youtube_api_key).")

    return key


def search_public_videos(state_dir: Path, query: str, limit: int = 6) -> dict[str, Any]:
    """Search public videos, then fetch their snippets and view counts in one batch."""
    query = query.strip()
    if not query or len(query) > 250:
        raise ValueError("YouTube search query must contain 1–250 characters.")
    if type(limit) is not int or not 1 <= limit <= 10:
        raise ValueError("YouTube search limit must be an integer from 1 to 10.")
    key = _read_key(state_dir)

    search = _request("search", key, part="snippet", type="video", q=query, maxResults=limit,
                      fields="items(id/videoId)")
    operations = ["search.list"]
    ids = list(dict.fromkeys(
        video_id for item in search["items"]
        if isinstance(item, dict) and isinstance(item.get("id"), dict)
        and isinstance(video_id := item["id"].get("videoId"), str) and _VIDEO_ID.fullmatch(video_id)
    ))
    if not ids:
        return {"provider": "YouTube Data API v3", "operations": operations, "videos": []}

    details = _request("videos", key, part="snippet,statistics", id=",".join(ids),
                       fields="items(id,snippet(title,channelId,channelTitle,publishedAt,description),statistics(viewCount))")
    operations.append("videos.list")
    items = {item["id"]: item for item in details["items"] if isinstance(item, dict)
             and isinstance(item.get("id"), str)}
    videos = []
    for video_id in ids:
        if video_id not in items:
            continue
        item = items[video_id]
        snippet = item.get("snippet") or {}
        views = (item.get("statistics") or {}).get("viewCount")
        videos.append({
            "video_id": video_id,
            "title": snippet.get("title"),
            "channel": snippet.get("channelTitle"),
            "channel_id": snippet.get("channelId"),
            "published_at": snippet.get("publishedAt"),
            "view_count": int(views) if isinstance(views, str) and views.isascii() and views.isdecimal() else None,
            "description": (snippet.get("description") or "")[:600],
            "url": f"https://www.youtube.com/watch?v={video_id}",
        })
    return {"provider": "YouTube Data API v3", "operations": operations, "videos": videos}


def latest_playlist_video(state_dir: Path, playlist: str) -> dict[str, Any]:
    """Find the most recently added item, regardless of playlist ordering."""
    playlist = playlist.strip()
    if not playlist or len(playlist) > 150:
        raise ValueError("Provide a configured playlist name or YouTube playlist ID.")
    if not re.fullmatch(r"(?:PL|UU|OLAK5uy_)[A-Za-z0-9_-]{10,80}", playlist):
        matches = set()
        for job in (state_dir / "research" / "youtube").glob("*/job.json"):
            try:
                record = json.loads(job.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if not isinstance(record, dict):
                continue
            name, identifier = record.get("playlist_title"), record.get("playlist_id")
            if isinstance(name, str) and name.casefold() == playlist.casefold() and isinstance(identifier, str):
                matches.add(identifier)
        if len(matches) != 1:
            raise RuntimeError("The playlist name did not resolve uniquely in Jaeger research state. Supply its playlist ID.")
        playlist = matches.pop()
    key = _read_key(state_dir)
    newest: dict[str, Any] = {}
    token = ""
    seen_tokens = set()
    for _ in range(100):
        params = {"pageToken": token} if token else {}
        page = _request("playlistItems", key, part="snippet", playlistId=playlist, maxResults=50,
                        fields="nextPageToken,items(snippet(publishedAt,title,resourceId/videoId))", **params)
        for item in page["items"]:
            snippet = item.get("snippet") or {}
            added = snippet.get("publishedAt") or ""
            if added > newest.get("added_at", ""):
                identifier = (snippet.get("resourceId") or {}).get("videoId") or ""
                newest = {"added_at": added, "title": snippet.get("title"), "video_id": identifier}
        token = page.get("nextPageToken")
        if not token:
            break
        if token in seen_tokens:
            raise RuntimeError("YouTube repeated a playlist page token; newest addition could not be verified.")
        seen_tokens.add(token)
    else:
        raise RuntimeError("Playlist exceeds the 5,000-item scan limit; newest addition could not be verified.")
    if not _VIDEO_ID.fullmatch(newest.get("video_id", "")):
        raise RuntimeError("No resolvable latest video was returned for this playlist.")
    return newest | {"playlist_id": playlist, "operation": "playlistItems.list",
                     "url": f"https://www.youtube.com/watch?v={newest['video_id']}"}
