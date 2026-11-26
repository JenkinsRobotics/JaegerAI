"""Standalone 2D/3D VR Avatar backend (VRM 0.x/1.0, GLB, Rive, 2D sprites/portraits).

Promoted and upgraded from JaegerAI's `jaeger.avatar/1` spec:
- Accepts **both VRM 0.x (`extensions.VRM`) and VRM 1.0 (`extensions.VRMC_vrm`)**,
  GLB, Rive, and 2D PNG/WebP/JPEG character assets.
- SHA-256 content-addressed storage under ``<state_dir>/avatars/`` with per-device
  triangle & byte budgets (desktop/ipad/iphone).
- Real phoneme-to-viseme timeline builder integrating ``jaeger_kokoro_tts``
  ``lip_marks()`` when available, plus deterministic phoneme-rule viseme curve
  generation (`aa`/`ih`/`ou`/`ee`/`oh`/`closed`/`fv`) for instant preview & sync.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import struct
import threading
import time
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib.parse import unquote

SCHEMA = "jaeger.avatar/1"
FORMATS = frozenset({"vrm", "glb", "rive", "image"})
REQUIRED_STATES = ("idle", "listening", "thinking", "speaking")
EMOTIONS = ("neutral", "calm", "happy", "warm", "focused", "curious", "concerned", "surprised", "sad", "relaxed", "angry")
VISEME_PROFILES = frozenset({"vrm5", "oculus15", "arkit52", "rive", "2d"})
MB = 1024 * 1024
BUDGETS = {
    "desktop": (25 * MB, 2 * MB, 200_000),
    "ipad": (14 * MB, 1 * MB, 75_000),
    "iphone": (10 * MB, 1 * MB, 40_000),
}
MAX_UPLOAD = 24 * MB
_AGENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_SHA_RE = re.compile(r"^[a-f0-9]{64}$")


class AvatarError(Exception):
    def __init__(self, status: int, message: str, **extra: Any) -> None:
        super().__init__(message)
        self.status = status
        self.payload = {"error": message, **extra}


def _image_dims(data: bytes) -> tuple[str, str, tuple[int, int]] | None:
    if data[:8] == b"\x89PNG\r\n\x1a\n" and len(data) >= 24:
        return "image/png", ".png", struct.unpack(">II", data[16:24])
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        c = data[12:16]
        if c == b"VP8 " and len(data) >= 30:
            w, h = struct.unpack("<HH", data[26:30])
            return "image/webp", ".webp", (w & 0x3FFF, h & 0x3FFF)
        if c == b"VP8L" and len(data) >= 25:
            b = int.from_bytes(data[21:25], "little")
            return "image/webp", ".webp", ((b & 0x3FFF) + 1, ((b >> 14) & 0x3FFF) + 1)
        if c == b"VP8X" and len(data) >= 30:
            return "image/webp", ".webp", (
                int.from_bytes(data[24:27], "little") + 1,
                int.from_bytes(data[27:30], "little") + 1,
            )
        return "image/webp", ".webp", (0, 0)
    if data[:3] == b"\xff\xd8\xff":
        i = 2
        while i + 9 < len(data):
            if data[i] != 0xFF:
                i += 1
                continue
            m = data[i + 1]
            if m in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                h, w = struct.unpack(">HH", data[i + 5 : i + 9])
                return "image/jpeg", ".jpg", (w, h)
            if m in (0xD8, 0x01) or 0xD0 <= m <= 0xD7:
                i += 2
                continue
            i += 2 + struct.unpack(">H", data[i + 2 : i + 4])[0]
        return "image/jpeg", ".jpg", (0, 0)
    return None


def inspect_glb_bytes(data: bytes) -> dict[str, Any]:
    """Inspect a GLB/VRM 0.x/VRM 1.0 binary container safely from raw bytes."""
    if len(data) < 20 or data[:4] != b"glTF":
        raise AvatarError(422, "not a GLB file (magic bytes are not glTF)", rule=3)
    version, _total = struct.unpack("<II", data[4:12])
    if version != 2:
        raise AvatarError(422, f"glTF version {version} is not supported; glTF 2.0 is required", rule=2)
    clen, ctype = struct.unpack("<II", data[12:20])
    if ctype != 0x4E4F534A:
        raise AvatarError(422, "GLB's first chunk is not JSON", rule=3)
    try:
        g = json.loads(data[20 : 20 + clen].decode("utf-8"))
    except ValueError as exc:
        raise AvatarError(422, "GLB JSON chunk is unreadable") from exc

    for im in g.get("images") or []:
        if "uri" in im and not str(im["uri"]).startswith("data:"):
            raise AvatarError(422, "external texture URI disallowed; embed textures inside .vrm/.glb", rule=10)
    for buf in g.get("buffers") or []:
        if "uri" in buf and not str(buf["uri"]).startswith("data:"):
            raise AvatarError(422, "external buffer URI disallowed; use self-contained .vrm/.glb", rule=10)

    used = set(g.get("extensionsUsed") or [])
    ext = g.get("extensions") or {}
    vrm1 = ext.get("VRMC_vrm") if ("VRMC_vrm" in used or "VRMC_vrm" in ext) else None
    vrm0 = ext.get("VRM") if ("VRM" in used or "VRM" in ext) else None
    is_vrm = vrm1 is not None or vrm0 is not None

    acc = g.get("accessors") or []
    tris = 0
    morphs: set[str] = set()
    for mesh in g.get("meshes") or []:
        for n in (mesh.get("extras") or {}).get("targetNames") or []:
            morphs.add(str(n))
        for prim in mesh.get("primitives") or []:
            if prim.get("mode", 4) != 4:
                continue
            ix = prim.get("indices")
            pos_ix = (prim.get("attributes") or {}).get("POSITION")
            src = (
                acc[ix]
                if isinstance(ix, int) and 0 <= ix < len(acc)
                else acc[pos_ix]
                if isinstance(pos_ix, int) and 0 <= pos_ix < len(acc)
                else None
            )
            tris += int((src or {}).get("count", 0)) // 3

    expressions: list[str] = []
    meta: dict[str, Any] | None = None
    if vrm1 is not None:
        fmt_ver = str(vrm1.get("specVersion", "1.0"))
        ex = vrm1.get("expressions") or {}
        expressions = sorted(
            set((ex.get("preset") or {}).keys()) | {f"custom:{k}" for k in (ex.get("custom") or {}).keys()}
        )
        m = vrm1.get("meta") or {}
        meta = {k: m.get(k) for k in ("name", "version", "authors", "licenseUrl", "avatarPermission") if k in m}
    elif vrm0 is not None:
        fmt_ver = str(vrm0.get("specVersion", "0.0"))
        groups = (vrm0.get("blendShapeMaster") or {}).get("blendShapeGroups") or []
        expressions = sorted({str(gr.get("presetName") or gr.get("name") or "") for gr in groups if gr.get("presetName") or gr.get("name")})
        m = vrm0.get("meta") or {}
        meta = {k: m.get(k) for k in ("title", "version", "author", "licenseName", "allowedUserName") if k in m}
    else:
        fmt_ver = str((g.get("asset") or {}).get("version", "2.0"))

    return {
        "format": "vrm" if is_vrm else "glb",
        "format_version": fmt_ver,
        "vrm_major": 1 if vrm1 is not None else (0 if vrm0 is not None else None),
        "mime": "model/gltf-binary",
        "triangles": tris,
        "materials": len(g.get("materials") or []),
        "textures": len(g.get("textures") or []),
        "morphs": sorted(morphs),
        "animations": [str(a.get("name") or f"animation_{i}") for i, a in enumerate(g.get("animations") or [])],
        "expressions": expressions,
        "meta": meta,
        "generator": (g.get("asset") or {}).get("generator"),
    }


def inspect_avatar_bytes(data: bytes, name: str = "") -> dict[str, Any]:
    img = _image_dims(data)
    if img:
        mime, ext, (w, h) = img
        return {"format": "image", "format_version": None, "mime": mime, "ext": ext, "width": w, "height": h}
    if data[:4] == b"RIVE":
        return {"format": "rive", "format_version": None, "mime": "application/x-rive", "ext": ".riv"}
    if data[:4] == b"glTF":
        info = inspect_glb_bytes(data)
        info["ext"] = ".vrm" if info["format"] == "vrm" else ".glb"
        return info
    raise AvatarError(422, "unsupported avatar format: use .vrm (0.x/1.0), .glb, .riv, .png, .webp or .jpg", rule=3)


def budget_report(info: Mapping[str, Any], size: int) -> dict[str, Any]:
    warn: list[str] = []
    devices: dict[str, Any] = {}
    fmt = str(info.get("format") or "")
    for dev, (mbytes, rbytes, tri) in BUDGETS.items():
        cap = rbytes if fmt == "rive" else mbytes if fmt in ("vrm", "glb") else None
        over: list[str] = []
        if cap and size > cap:
            over.append(f"{size / MB:.1f} MB > {cap / MB:.0f} MB")
        if fmt in ("vrm", "glb") and int(info.get("triangles") or 0) > tri:
            over.append(f"{int(info['triangles']):,} triangles > {tri:,}")
        devices[dev] = {"ok": not over, "over": over}
        if over:
            warn.append(f"Over {dev} budget: " + "; ".join(over))
    hard = (2 * BUDGETS["desktop"][1]) if fmt == "rive" else (2 * BUDGETS["desktop"][0]) if fmt in ("vrm", "glb") else None
    return {"devices": devices, "warnings": warn, "rejected": bool(hard and size > hard)}


def build_viseme_timeline(
    text: str,
    *,
    kokoro_marks: Sequence[Sequence[Any]] | None = None,
    duration_s: float | None = None,
) -> dict[str, Any]:
    """Build a VRM5/2D viseme timeline from real Kokoro ``lip_marks`` or fast grapheme timing.

    Maps Kokoro's ``[start, end, "p" | "f"]`` marks + vowel timing into smooth
    ``{t_ms, duration_ms, viseme, weight}`` frames ready for Three.js VRM & 2D rigs.
    """
    frames: list[dict[str, Any]] = []
    if kokoro_marks:
        for mark in kokoro_marks:
            if len(mark) < 3:
                continue
            start_s, end_s, code = float(mark[0]), float(mark[1]), str(mark[2])
            vis = "closed" if code == "p" else ("ih" if code == "f" else "aa")
            frames.append({
                "t_ms": int(round(start_s * 1000)),
                "duration_ms": max(30, int(round((end_s - start_s) * 1000))),
                "viseme": vis,
                "weight": 0.0 if vis == "closed" else 0.75,
                "code": code,
            })
        return {
            "source": "kokoro_lip_marks",
            "stub": False,
            "duration_ms": int(round((duration_s or (frames[-1]["t_ms"] / 1000.0 + 0.1 if frames else 0.0)) * 1000)),
            "frames": frames,
        }

    # Deterministic grapheme-to-VRM5 viseme sequence when audio is not pre-rendered
    clean = re.sub(r"\s+", " ", (text or "").strip().lower())
    t_ms = 0
    for ch in clean[:400]:
        if ch in "pbm":
            frames.append({"t_ms": t_ms, "duration_ms": 55, "viseme": "closed", "weight": 0.0})
            t_ms += 55
        elif ch in "fv":
            frames.append({"t_ms": t_ms, "duration_ms": 55, "viseme": "ih", "weight": 0.45})
            t_ms += 55
        elif ch == "a":
            frames.append({"t_ms": t_ms, "duration_ms": 75, "viseme": "aa", "weight": 0.85})
            t_ms += 75
        elif ch == "e":
            frames.append({"t_ms": t_ms, "duration_ms": 70, "viseme": "ee", "weight": 0.75})
            t_ms += 70
        elif ch == "i":
            frames.append({"t_ms": t_ms, "duration_ms": 65, "viseme": "ih", "weight": 0.7})
            t_ms += 65
        elif ch == "o":
            frames.append({"t_ms": t_ms, "duration_ms": 75, "viseme": "oh", "weight": 0.8})
            t_ms += 75
        elif ch == "u":
            frames.append({"t_ms": t_ms, "duration_ms": 70, "viseme": "ou", "weight": 0.75})
            t_ms += 70
        elif ch == " ":
            frames.append({"t_ms": t_ms, "duration_ms": 60, "viseme": "closed", "weight": 0.0})
            t_ms += 60
        elif ch in ",.!?;:":
            frames.append({"t_ms": t_ms, "duration_ms": 140, "viseme": "closed", "weight": 0.0})
            t_ms += 140
        else:
            t_ms += 35
    frames.append({"t_ms": t_ms, "duration_ms": 60, "viseme": "closed", "weight": 0.0})
    return {
        "source": "grapheme_vrm5",
        "stub": False,
        "duration_ms": t_ms + 60,
        "frames": frames,
    }


class AvatarStore:
    """Thread-safe avatar asset, card, version, and live emotion/state manager."""

    def __init__(self, state_dir: Path) -> None:
        self._root = Path(state_dir).expanduser().resolve() / "avatars"
        self._assets_dir = self._root / "assets"
        self._cards_dir = self._root / "cards"
        self._assets_dir.mkdir(parents=True, exist_ok=True)
        self._cards_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._live: dict[str, dict[str, Any]] = {}

    @staticmethod
    def _clean_agent(aid: str) -> str:
        clean = unquote(aid or "jaeger").strip()
        if not _AGENT_RE.match(clean) or ".." in clean:
            raise AvatarError(400, "invalid agent id")
        return clean

    def _read_json(self, path: Path, default: Any) -> Any:
        try:
            return json.loads(path.read_text("utf-8"))
        except (OSError, ValueError):
            return default

    def _write_json(self, path: Path, data: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), "utf-8")
        os.replace(tmp, path)

    def add_asset(self, data: bytes, name: str) -> dict[str, Any]:
        if not data:
            raise AvatarError(400, "empty avatar file")
        if len(data) > MAX_UPLOAD:
            raise AvatarError(413, f"file exceeds {MAX_UPLOAD // MB} MB limit", rule=3)
        info = inspect_avatar_bytes(data, name)
        budget = budget_report(info, len(data))
        if budget["rejected"]:
            raise AvatarError(422, "avatar asset exceeds maximum device budget", rule=3, budget=budget)
        sha = hashlib.sha256(data).hexdigest()
        ext = str(info["ext"])
        blob_path = self._assets_dir / f"{sha}{ext}"
        with self._lock:
            if not blob_path.exists():
                blob_path.write_bytes(data)
            idx_path = self._assets_dir / "index.json"
            idx = self._read_json(idx_path, {})
            rec = {
                "id": sha,
                "sha256": sha,
                "uri": f"/v1/avatars/assets/{sha}/file",
                "name": (name or sha[:12])[:120],
                "bytes": len(data),
                "created_at": int(time.time()),
                **info,
                "budget": budget,
            }
            idx[sha] = rec
            self._write_json(idx_path, idx)
            return rec

    def list_assets(self) -> list[dict[str, Any]]:
        with self._lock:
            idx = self._read_json(self._assets_dir / "index.json", {})
            return sorted(idx.values(), key=lambda r: int(r.get("created_at") or 0), reverse=True)

    def get_asset_file(self, sha: str) -> tuple[Path, str] | None:
        if not _SHA_RE.match(sha or ""):
            return None
        with self._lock:
            idx = self._read_json(self._assets_dir / "index.json", {})
            rec = idx.get(sha)
            if not rec:
                return None
            p = self._assets_dir / f"{sha}{rec['ext']}"
            return (p, str(rec.get("mime") or "application/octet-stream")) if p.is_file() else None

    def set_agent_avatar(
        self,
        agent_id: str,
        *,
        asset_sha: str | None = None,
        mode: str = "3d_vrm",  # "3d_vrm" | "2d_character" | "rive"
        display_name: str = "Jaeger",
        accent_color: str = "#5B8DEF",
        preset: str = "studio_cel",
    ) -> dict[str, Any]:
        aid = self._clean_agent(agent_id)
        with self._lock:
            card_path = self._cards_dir / f"{aid}.json"
            existing = self._read_json(card_path, {"agent_id": aid, "schema": SCHEMA, "version": 0, "history": []})
            version = int(existing.get("version") or 0) + 1
            cfg = {
                "schema": SCHEMA,
                "agent_id": aid,
                "version": version,
                "mode": mode,
                "display_name": display_name,
                "accent_color": accent_color,
                "preset": preset,
                "asset_sha": asset_sha,
                "updated_at": int(time.time()),
            }
            history = list(existing.get("history") or [])
            history.append({k: v for k, v in cfg.items() if k != "history"})
            cfg["history"] = history[-25:]
            self._write_json(card_path, cfg)
            return self.get_agent_avatar(aid)

    def get_agent_avatar(self, agent_id: str) -> dict[str, Any]:
        aid = self._clean_agent(agent_id)
        with self._lock:
            cfg = self._read_json(
                self._cards_dir / f"{aid}.json",
                {
                    "schema": SCHEMA,
                    "agent_id": aid,
                    "version": 1,
                    "mode": "2d_character",
                    "display_name": aid.capitalize(),
                    "accent_color": "#5B8DEF",
                    "preset": "studio_cel",
                    "asset_sha": None,
                    "history": [],
                },
            )
            asset = None
            sha = cfg.get("asset_sha")
            if sha:
                idx = self._read_json(self._assets_dir / "index.json", {})
                asset = idx.get(sha)
            live = self._live.get(
                aid,
                {"emotion": "warm", "intensity": 0.65, "state": "idle", "amplitude": 0.0, "updated_at": time.time()},
            )
            return {"agent_id": aid, "avatar": cfg, "asset": asset, "live": live}

    def set_live_state(
        self,
        agent_id: str,
        *,
        emotion: str | None = None,
        intensity: float | None = None,
        state: str | None = None,
        amplitude: float | None = None,
    ) -> dict[str, Any]:
        aid = self._clean_agent(agent_id)
        with self._lock:
            cur = dict(
                self._live.get(
                    aid,
                    {"emotion": "warm", "intensity": 0.65, "state": "idle", "amplitude": 0.0},
                )
            )
            if emotion and emotion in EMOTIONS:
                cur["emotion"] = emotion
            if intensity is not None:
                cur["intensity"] = max(0.0, min(1.0, float(intensity)))
            if state:
                cur["state"] = str(state)
            if amplitude is not None:
                cur["amplitude"] = max(0.0, min(1.0, float(amplitude)))
            cur["updated_at"] = time.time()
            self._live[aid] = cur
            return cur


__all__ = [
    "AvatarError",
    "AvatarStore",
    "BUDGETS",
    "EMOTIONS",
    "FORMATS",
    "SCHEMA",
    "build_viseme_timeline",
    "budget_report",
    "inspect_avatar_bytes",
    "inspect_glb_bytes",
]
