"""Shared read-only YouTube Data API listing for chat and the research workspace."""
from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from collections.abc import Callable
from pathlib import Path

_VID = re.compile(r"^[A-Za-z0-9_-]{11}$")
_LIST = re.compile(r"^[A-Za-z0-9_-]{10,64}$")
_HOSTS = frozenset(("www.youtube.com", "youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be"))
_LINK = re.compile(r"""https://[^\s<>"']+""", re.IGNORECASE)


def playlist_id(url_or_id: str) -> str | None:
    target = url_or_id.strip()
    if _LIST.fullmatch(target) and len(target) != 11:
        return target
    try:
        u = urllib.parse.urlsplit(target)
        if u.scheme != "https" or u.hostname not in _HOSTS or u.username or u.password:
            return None
        values = urllib.parse.parse_qs(u.query).get("list", [])
    except ValueError:
        return None
    return values[0] if len(values) == 1 and _LIST.fullmatch(values[0]) else None


def mentions_youtube_playlist(text: str) -> bool:
    return any(playlist_id(match.group().rstrip(").,;!?]")) for match in _LINK.finditer(text))


def read_api_key(root: Path) -> str | None:
    try:
        return (root / "secrets" / "youtube_api_key").read_text().strip() or None
    except (OSError, UnicodeError):
        return None


def http_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=12) as response:
        return json.load(response)


def _iso_dur(s):
    m = re.match(r"^P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?$", s or "")
    if not m:
        return None
    d, h, mi, se = (int(x or 0) for x in m.groups())
    return d * 86400 + h * 3600 + mi * 60 + se


def list_playlist_api(lid: str, limit: int, key: str, http_json: Callable[[str], dict]) -> dict:
    if not _LIST.fullmatch(lid):
        raise ValueError("Invalid YouTube playlist ID")

    def q(path, **kw):
        return http_json("https://www.googleapis.com/youtube/v3/" + path + "?" + urllib.parse.urlencode({**kw, "key": key}))
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
