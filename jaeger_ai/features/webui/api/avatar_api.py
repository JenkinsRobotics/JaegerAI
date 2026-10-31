"""Agent avatars: card storage, asset upload + validation, versions, emotion, viseme stub (Jenkins Robotics, 2026-10-31).

Spec: ~/Documents/Jaeger-Design-Specs/avatar/AVATAR-SPEC.md (§6a validation rules, §7 endpoints).

  GET  /v1/agents/<id>/avatar                 {agent_id, avatar|null, card|null, live, asset|null}
  PUT  /v1/agents/<id>/avatar                 {avatar:{…extension}} or {card:{chara_card_v3}} → validated, saved as next version
  GET  /v1/agents/<id>/avatar/versions        current + immutable history
  POST /v1/agents/<id>/avatar/restore         {sha256} → re-points the extension at that version (new version number)
  GET  /v1/agents/<id>/avatar/card            the stored CCv3 card, unknown extensions preserved
  PUT  /v1/agents/<id>/avatar/emotion         {emotion, intensity} → live emotion (new field; nothing upstream sets it yet)
  GET  /v1/agents/<id>/avatar/visemes?text=…  STUB timeline from text (no TTS viseme source exists yet; flagged stub:true)
  POST /v1/assets                             {name, data_base64} → stored by SHA-256 + validation report
  GET  /v1/assets[/<sha>][/file]

Storage: <state>/avatars/cards/<agent>.json, <state>/avatars/assets/<sha>.<ext> (+ index.json). Live2D is
rejected (pending licence review). Nothing is fabricated: a file's stats are read from its bytes.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import struct
import threading
import time
from pathlib import Path
from urllib.parse import parse_qs, unquote

SCHEMA = "jaeger.avatar/1"
FORMATS = {"vrm", "glb", "rive", "image"}
REQUIRED_STATES = ("idle", "listening", "thinking", "speaking")
EMOTIONS = ("neutral", "happy", "warm", "focused", "curious", "concerned", "surprised", "sad")
VISEME_PROFILES = {"vrm5", "oculus15", "arkit52", "rive"}
MB = 1024 * 1024
# §5 budgets per device class: (model bytes, rive bytes, triangles, textures)
BUDGETS = {"desktop": (15 * MB, 1 * MB, 150_000), "ipad": (12 * MB, 1 * MB, 50_000), "iphone": (8 * MB, 1 * MB, 30_000)}
MAX_UPLOAD = 14 * MB  # base64 must fit read_body's 20 MB cap
FALLBACK_MAX = 400 * 1024
_AGENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_SHA = re.compile(r"^[a-f0-9]{64}$")
_SEMVER = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
_lock = threading.Lock()


class AvatarError(Exception):
    def __init__(self, status: int, message: str, **extra):
        super().__init__(message)
        self.status, self.payload = status, {"error": message, **extra}


def state_root() -> Path:
    return Path(os.environ.get("JAEGER_STATE_HOME") or os.environ.get("JAEGER_STATE_DIR") or Path.home() / ".jaeger")


def _dir(name: str) -> Path:
    p = state_root() / "avatars" / name
    p.mkdir(parents=True, exist_ok=True)
    return p


def _read(path: Path, default):
    try:
        return json.loads(path.read_text("utf-8"))
    except (OSError, ValueError):
        return default


def _write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), "utf-8")
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def _agent(aid: str) -> str:
    aid = unquote(aid)
    if not _AGENT.match(aid) or ".." in aid:
        raise AvatarError(400, "invalid agent id")
    return aid


# ── File inspection (reads the bytes; no guessing) ───────────────────

def _image_dims(data: bytes):
    if data[:8] == b"\x89PNG\r\n\x1a\n" and len(data) >= 24:
        return "image/png", ".png", struct.unpack(">II", data[16:24])
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        c = data[12:16]
        if c == b"VP8 " and len(data) >= 30:
            w, h = struct.unpack("<HH", data[26:30]); return "image/webp", ".webp", (w & 0x3FFF, h & 0x3FFF)
        if c == b"VP8L" and len(data) >= 25:
            b = int.from_bytes(data[21:25], "little"); return "image/webp", ".webp", ((b & 0x3FFF) + 1, ((b >> 14) & 0x3FFF) + 1)
        if c == b"VP8X" and len(data) >= 30:
            return "image/webp", ".webp", (int.from_bytes(data[24:27], "little") + 1, int.from_bytes(data[27:30], "little") + 1)
        return "image/webp", ".webp", (0, 0)
    if data[:3] == b"\xff\xd8\xff":
        i = 2
        while i + 9 < len(data):
            if data[i] != 0xFF:
                i += 1; continue
            m = data[i + 1]
            if m in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                h, w = struct.unpack(">HH", data[i + 5:i + 9]); return "image/jpeg", ".jpg", (w, h)
            if m in (0xD8, 0x01) or 0xD0 <= m <= 0xD7:
                i += 2; continue
            i += 2 + struct.unpack(">H", data[i + 2:i + 4])[0]
        return "image/jpeg", ".jpg", (0, 0)
    return None


def _glb(data: bytes) -> dict:
    if len(data) < 20 or data[:4] != b"glTF":
        raise AvatarError(422, "not a GLB file (magic bytes are not glTF)", rule=3)
    version, total = struct.unpack("<II", data[4:12])
    if version != 2:
        raise AvatarError(422, f"glTF version {version} is not supported; glTF 2.0 is required", rule=2)
    clen, ctype = struct.unpack("<II", data[12:20])
    if ctype != 0x4E4F534A:
        raise AvatarError(422, "GLB's first chunk is not JSON", rule=3)
    try:
        g = json.loads(data[20:20 + clen].decode("utf-8"))
    except ValueError as exc:
        raise AvatarError(422, "GLB JSON chunk is unreadable") from exc
    used = set(g.get("extensionsUsed") or [])
    ext = g.get("extensions") or {}
    if "VRM" in used or "VRM" in ext:
        raise AvatarError(422, "VRM 0.x isn't supported yet; re-export as VRM 1.0 (Blender VRM add-on or UniVRM)", rule=2)
    for im in g.get("images") or []:
        if "uri" in im and not str(im["uri"]).startswith("data:"):
            raise AvatarError(422, "the model references an external texture; only embedded textures are allowed", rule=10)
    for b in (g.get("buffers") or [])[0:]:
        if "uri" in b and not str(b["uri"]).startswith("data:"):
            raise AvatarError(422, "the model references an external buffer; use a self-contained .glb/.vrm", rule=10)
    acc = g.get("accessors") or []
    tris, morphs = 0, set()
    for mesh in g.get("meshes") or []:
        for n in (mesh.get("extras") or {}).get("targetNames") or []:
            morphs.add(str(n))
        for prim in mesh.get("primitives") or []:
            if prim.get("mode", 4) != 4:
                continue
            ix = prim.get("indices")
            src = acc[ix] if isinstance(ix, int) and ix < len(acc) else acc[prim.get("attributes", {}).get("POSITION", -1)] if isinstance(prim.get("attributes", {}).get("POSITION"), int) else None
            tris += int((src or {}).get("count", 0)) // 3
    vrm = ext.get("VRMC_vrm") if "VRMC_vrm" in used or "VRMC_vrm" in ext else None
    out = {
        "format": "vrm" if vrm is not None else "glb",
        "format_version": str((vrm or {}).get("specVersion", "1.0")) if vrm is not None else str((g.get("asset") or {}).get("version", "2.0")),
        "mime": "model/gltf-binary", "triangles": tris,
        "materials": len(g.get("materials") or []), "textures": len(g.get("textures") or []),
        "morphs": sorted(morphs), "animations": [str(a.get("name") or f"animation_{i}") for i, a in enumerate(g.get("animations") or [])],
        "expressions": [], "meta": None, "generator": (g.get("asset") or {}).get("generator"),
    }
    if vrm is not None:
        ex = vrm.get("expressions") or {}
        out["expressions"] = sorted(set((ex.get("preset") or {}).keys()) | set(f"custom:{k}" for k in (ex.get("custom") or {}).keys()))
        m = vrm.get("meta") or {}
        out["meta"] = {k: m.get(k) for k in ("name", "version", "authors", "licenseUrl", "avatarPermission", "commercialUsage", "allowRedistribution") if k in m}
    return out


def inspect(data: bytes, name: str = "") -> dict:
    """Read format, mime and stats from the bytes. Raises AvatarError(422) with the failed rule."""
    low = name.lower()
    if low.endswith((".moc3", ".zip")) or data[:4] == b"MOC3":
        raise AvatarError(422, "Live2D isn't supported yet (pending licence review)", rule=2)
    img = _image_dims(data)
    if img:
        mime, ext, (w, h) = img
        return {"format": "image", "format_version": None, "mime": mime, "ext": ext, "width": w, "height": h}
    if data[:4] == b"RIVE":
        return {"format": "rive", "format_version": None, "mime": "application/x-rive", "ext": ".riv",
                "note": "Rive state-machine inputs are checked in the viewer, not on the server"}
    if data[:4] == b"glTF":
        info = _glb(data)
        info["ext"] = ".vrm" if info["format"] == "vrm" else ".glb"
        return info
    raise AvatarError(422, "unsupported file: use .vrm, .glb, .riv, .png, .webp or .jpg", rule=3)


def budget_report(info: dict, size: int) -> dict:
    """Per-device-class warnings (§5). Over 2× the iPhone budget is rejected (rule 3)."""
    warn, devices = [], {}
    fmt = info["format"]
    for dev, (mbytes, rbytes, tri) in BUDGETS.items():
        cap = rbytes if fmt == "rive" else mbytes if fmt in ("vrm", "glb") else None
        over = []
        if cap and size > cap:
            over.append(f"{size / MB:.1f} MB > {cap / MB:.0f} MB")
        if fmt in ("vrm", "glb") and info.get("triangles", 0) > tri:
            over.append(f"{info['triangles']:,} triangles > {tri:,}")
        devices[dev] = {"ok": not over, "over": over}
        if over:
            warn.append(f"Over the {dev} budget: " + "; ".join(over))
    hard = (2 * BUDGETS["iphone"][1]) if fmt == "rive" else (2 * BUDGETS["iphone"][0]) if fmt in ("vrm", "glb") else None
    return {"devices": devices, "warnings": warn, "rejected": bool(hard and size > hard)}


# ── Asset store ──────────────────────────────────────────────────────

def _index() -> dict:
    return _read(_dir("assets") / "index.json", {})


def add_asset(data: bytes, name: str) -> dict:
    if not data:
        raise AvatarError(400, "empty file")
    if len(data) > MAX_UPLOAD:
        raise AvatarError(413, f"file is {len(data) / MB:.1f} MB; the upload limit is {MAX_UPLOAD // MB} MB", rule=3)
    info = inspect(data, name)
    budget = budget_report(info, len(data))
    if budget["rejected"]:
        raise AvatarError(422, "file is more than twice the iPhone budget", rule=3, budget=budget)
    sha = hashlib.sha256(data).hexdigest()
    rec = {"id": sha, "sha256": sha, "uri": f"jaeger-asset://{sha}", "name": (name or sha[:12])[:120], "bytes": len(data),
           "created_at": int(time.time()), **{k: v for k, v in info.items() if k != "ext"}, "ext": info["ext"],
           "budget": budget}
    with _lock:
        path = _dir("assets") / f"{sha}{info['ext']}"
        if not path.exists():
            tmp = path.with_suffix(".tmp"); tmp.write_bytes(data); os.replace(tmp, path)
        idx = _index(); idx.setdefault(sha, rec); _write(_dir("assets") / "index.json", idx)
    return _index()[sha]


def get_asset(sha: str) -> dict:
    if not _SHA.match(sha):
        raise AvatarError(400, "invalid asset id")
    rec = _index().get(sha)
    if not rec:
        raise AvatarError(404, "asset not found")
    return rec


def asset_bytes(sha: str) -> tuple[dict, bytes]:
    rec = get_asset(sha)
    return rec, (_dir("assets") / f"{sha}{rec['ext']}").read_bytes()


def _asset_from_uri(uri) -> dict | None:
    m = re.match(r"^jaeger-asset://([a-f0-9]{64})$", str(uri or ""))
    return _index().get(m.group(1)) if m else None


# ── Extension validation (§6a) ───────────────────────────────────────

def validate(ext, *, prev_version: str | None = None) -> dict:
    """Returns {ok, errors:[{rule,message}], warnings:[…]}. Unknown keys are kept, never rejected (rule 1)."""
    errs, warns = [], []
    e = lambda rule, msg: errs.append({"rule": rule, "message": msg})
    if not isinstance(ext, dict):
        return {"ok": False, "errors": [{"rule": 1, "message": "avatar must be an object"}], "warnings": []}
    if ext.get("schema") != SCHEMA:
        e(1, f"schema must be {SCHEMA}")
    fmt = ext.get("format")
    if fmt == "live2d":
        e(2, "Live2D isn't supported yet (pending licence review)")
    elif fmt not in FORMATS:
        e(2, "format must be vrm, glb, rive or image")
    fv = str(ext.get("format_version") or "")
    if fmt == "vrm" and fv != "1.0":
        e(2, "VRM format_version must be 1.0")
    if fmt == "glb" and fv != "2.0":
        e(2, "glTF format_version must be 2.0")
    asset = ext.get("asset") if isinstance(ext.get("asset"), dict) else {}
    uri = str(asset.get("uri") or "")
    stored = None
    if fmt != "image" or uri:
        if not uri.startswith(("embeded://", "https://", "jaeger-asset://")):
            e(3, "asset.uri must be embeded://, https:// or jaeger-asset://<id> (file: and http: are not allowed)")
        elif uri.startswith("jaeger-asset://"):
            stored = _asset_from_uri(uri)
            if not stored:
                e(3, "asset.uri points at an asset that isn't in the store")
            else:
                if asset.get("sha256") and asset["sha256"] != stored["sha256"]:
                    e(3, "asset.sha256 doesn't match the stored bytes")
                if fmt in FORMATS and stored["format"] != fmt:
                    e(3, f"format says {fmt} but the file is {stored['format']}")
                warns.extend(stored.get("budget", {}).get("warnings", []))
    fb = ext.get("fallback") if isinstance(ext.get("fallback"), dict) else None
    if not fb or not (fb.get("uri") or fb.get("ref")):
        e(4, "a fallback portrait is required")
    elif fb.get("uri"):
        f = _asset_from_uri(fb["uri"])
        if not f:
            e(4, "fallback must be a stored image (jaeger-asset://)")
        elif f["format"] != "image":
            e(4, "fallback must be an image")
        else:
            if f["bytes"] > FALLBACK_MAX:
                e(4, f"fallback is {f['bytes'] // 1024} KB; max 400 KB")
            if f.get("width") != f.get("height") or (f.get("width") or 0) < 512:
                e(4, f"fallback must be square and at least 512×512 (got {f.get('width')}×{f.get('height')})")
    states = ext.get("states") if isinstance(ext.get("states"), dict) else {}
    missing = [s for s in REQUIRED_STATES if s not in states]
    if missing:
        e(5, "states must define " + ", ".join(missing))
    known = set((stored or {}).get("expressions") or []) | {"neutral"}
    anims = set((stored or {}).get("animations") or [])
    if stored and stored["format"] in ("vrm", "glb"):
        known |= set(stored.get("morphs") or [])
        for k, st in states.items():
            st = st if isinstance(st, dict) else {}
            if st.get("animation") and st["animation"] not in anims:
                e(5, f"state {k}: animation “{st['animation']}” isn't in the file")
            if st.get("expression") and stored["format"] == "vrm" and st["expression"] not in known:
                e(5, f"state {k}: expression “{st['expression']}” isn't in the file")
    emos = ext.get("emotions") if isinstance(ext.get("emotions"), dict) else {}
    if "neutral" not in emos:
        e(6, "emotions must include neutral")
    for name, weights in emos.items():
        for target, w in (weights or {}).items() if isinstance(weights, dict) else []:
            if not isinstance(w, (int, float)) or not 0 <= w <= 1:
                e(6, f"emotion {name}: weight for {target} must be 0–1")
            elif stored and stored["format"] == "vrm" and target not in known:
                e(6, f"emotion {name}: expression “{target}” isn't in the file")
    vis = ext.get("visemes")
    if isinstance(vis, dict):
        if vis.get("profile") not in VISEME_PROFILES:
            e(7, "visemes.profile must be vrm5, oculus15, arkit52 or rive")
        elif stored and stored["format"] == "vrm":
            for k, t in (vis.get("map") or {}).items():
                if t is not None and t not in known:
                    e(7, f"viseme {k}: target “{t}” isn't in the file")
    lic = ext.get("license") if isinstance(ext.get("license"), dict) else {}
    if not (lic.get("spdx") or lic.get("url")):
        e(8, "license needs an SPDX id or a URL")
    if not lic.get("author"):
        e(8, "license needs an author")
    meta = (stored or {}).get("meta") or {}
    if meta and lic:
        if meta.get("commercialUsage") == "personalNonProfit" and lic.get("commercial") is True:
            warns.append("VRM meta says personal/non-profit use only, but the card says commercial")
        if meta.get("allowRedistribution") is False and lic.get("redistribution") is True:
            warns.append("VRM meta forbids redistribution, but the card allows it")
    v = str(ext.get("version") or "")
    if not _SEMVER.match(v):
        e(9, "version must be semver (e.g. 1.0.0)")
    elif prev_version and _SEMVER.match(prev_version) and tuple(map(int, v.split("."))) <= tuple(map(int, prev_version.split("."))):
        e(9, f"version must increase (current is {prev_version})")
    return {"ok": not errs, "errors": errs, "warnings": warns}


# ── Cards ────────────────────────────────────────────────────────────

def _card_path(aid: str) -> Path:
    return _dir("cards") / f"{aid}.json"


def _ext_of(card) -> dict | None:
    try:
        return card["data"]["extensions"]["jaeger"]["avatar"]
    except (KeyError, TypeError):
        return None


def _bump(v: str | None) -> str:
    m = _SEMVER.match(v or "")
    return f"{m.group(1)}.{int(m.group(2)) + 1}.0" if m else "1.0.0"


def _live(aid: str) -> dict:
    live = _read(_dir("cards") / f"{aid}.live.json", None)
    return live or {"emotion": "neutral", "intensity": 0.0, "updated_at": None, "source": "default"}


def get_avatar(aid: str) -> dict:
    aid = _agent(aid)
    card = _read(_card_path(aid), None)
    ext = _ext_of(card)
    asset = _asset_from_uri((ext or {}).get("asset", {}).get("uri")) if ext else None
    fb = _asset_from_uri((ext or {}).get("fallback", {}).get("uri")) if ext else None
    return {"agent_id": aid, "avatar": ext, "card": card, "asset": asset, "fallback_asset": fb, "live": _live(aid)}


def _hash_of(ext: dict) -> str:
    a = ext.get("asset") or {}
    return str(a.get("sha256") or (ext.get("fallback") or {}).get("sha256") or "")


def save_avatar(aid: str, body: dict) -> dict:
    aid = _agent(aid)
    with _lock:
        card = _read(_card_path(aid), None)
        incoming_card = body.get("card")
        if isinstance(incoming_card, dict):
            if incoming_card.get("spec") != "chara_card_v3":
                raise AvatarError(400, "card.spec must be chara_card_v3")
            new = _ext_of(incoming_card)
            if new is None:
                raise AvatarError(400, "card has no data.extensions.jaeger.avatar")
            base = incoming_card
        else:
            new = body.get("avatar")
            base = card or {"spec": "chara_card_v3", "spec_version": "3.0", "data": {"name": str(body.get("name") or aid), "assets": [], "extensions": {}}}
        if not isinstance(new, dict):
            raise AvatarError(400, "avatar object required")
        prev = _ext_of(card)
        new = json.loads(json.dumps(new))  # detach; unknown keys kept
        if prev and not isinstance(incoming_card, dict):
            new["history"] = list(prev.get("history") or []) + [{"version": prev.get("version"), "sha256": _hash_of(prev), "at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "snapshot": {k: v for k, v in prev.items() if k != "history"}}]
            if not body.get("keep_version"):
                new["version"] = _bump(prev.get("version"))
        elif not new.get("version"):
            new["version"] = "1.0.0"
        if prev and isinstance(new.get("history"), list) and prev.get("history"):
            if new["history"][:len(prev["history"])] != prev["history"]:
                raise AvatarError(422, "history entries are immutable", rule=9)
        a = new.get("asset")
        if isinstance(a, dict) and (st := _asset_from_uri(a.get("uri"))):
            a.setdefault("sha256", st["sha256"]); a["bytes"] = st["bytes"]; a["mime"] = st["mime"]
        f = new.get("fallback")
        if isinstance(f, dict) and (st := _asset_from_uri(f.get("uri"))):
            f["sha256"] = st["sha256"]
        same = isinstance(incoming_card, dict) and new == prev  # re-importing an exported card is a no-op for the extension
        report = validate(new, prev_version=None if same else (prev or {}).get("version"))
        if not report["ok"]:
            raise AvatarError(422, report["errors"][0]["message"], rule=report["errors"][0]["rule"], report=report)
        data = base.setdefault("data", {})
        data.setdefault("extensions", {}).setdefault("jaeger", {})["avatar"] = new
        _write(_card_path(aid), base)
    out = get_avatar(aid)
    out["report"] = report
    return out


def versions(aid: str) -> dict:
    cur = get_avatar(aid)["avatar"]
    if not cur:
        return {"agent_id": _agent(aid), "current": None, "history": []}
    hist = [{k: v for k, v in h.items() if k != "snapshot"} | {"restorable": bool(h.get("snapshot"))} for h in cur.get("history") or []]
    return {"agent_id": _agent(aid), "current": {"version": cur.get("version"), "sha256": _hash_of(cur), "format": cur.get("format")}, "history": list(reversed(hist))}


def restore(aid: str, body: dict) -> dict:
    sha, ver = str(body.get("sha256") or ""), str(body.get("version") or "")
    cur = get_avatar(aid)["avatar"]
    if not cur:
        raise AvatarError(404, "no avatar saved for this agent")
    for h in reversed(cur.get("history") or []):
        if (sha and h.get("sha256") == sha) or (ver and h.get("version") == ver):
            snap = h.get("snapshot")
            if not snap:
                raise AvatarError(409, "that version has no snapshot to restore")
            return save_avatar(aid, {"avatar": dict(snap)})
    raise AvatarError(404, "version not found in history")


def set_emotion(aid: str, body: dict) -> dict:
    aid = _agent(aid)
    emo = str(body.get("emotion") or "")
    if emo not in EMOTIONS:
        raise AvatarError(400, "emotion must be one of " + ", ".join(EMOTIONS))
    try:
        inten = float(body.get("intensity", 1.0))
    except (TypeError, ValueError) as exc:
        raise AvatarError(400, "intensity must be a number") from exc
    if not 0 <= inten <= 1:
        raise AvatarError(400, "intensity must be 0–1")
    live = {"emotion": emo, "intensity": inten, "updated_at": int(time.time()), "source": str(body.get("source") or "api")[:40]}
    _write(_dir("cards") / f"{aid}.live.json", live)
    return live


_VOWEL = {"a": "A", "i": "I", "y": "I", "u": "U", "w": "U", "e": "E", "o": "O"}


def visemes_stub(text: str, rate_wps: float = 2.6) -> dict:
    """PLACEHOLDER lip-sync: vowel letters → vrm5 visemes at a fixed speaking rate. No TTS emits visemes yet."""
    text = (text or "")[:2000]
    out, t = [], 0.0
    for word in re.findall(r"[A-Za-z']+|[.,!?;:]", text):
        if word in ".,!?;:":
            out.append({"t": round(t, 3), "viseme": "sil"}); t += 0.25; continue
        dur = 1 / rate_wps
        vs = [_VOWEL[c] for c in word.lower() if c in _VOWEL] or ["sil"]
        step = dur / len(vs)
        for i, v in enumerate(vs):
            out.append({"t": round(t + i * step, 3), "viseme": v})
        t += dur
    out.append({"t": round(t, 3), "viseme": "sil"})
    return {"stub": True, "source": "text-heuristic", "profile": "vrm5", "duration": round(t, 3), "timeline": out,
            "note": "Placeholder until the TTS engine reports real viseme timings or audio amplitude."}


# ── Router ───────────────────────────────────────────────────────────

def handles(p: str) -> bool:
    return p == "/v1/assets" or p.startswith("/v1/assets/") or bool(re.match(r"^/v1/agents/[^/]+/avatar(/.*)?$", p))


def route(handler, parsed, method: str, read_body, j) -> bool:
    p = parsed.path
    if not handles(p):
        return False
    try:
        body = read_body(handler) if method in ("POST", "PUT") else {}
        if not isinstance(body, dict):
            raise AvatarError(400, "JSON object body required")
        if p == "/v1/assets":
            if method == "GET":
                return j(handler, {"assets": sorted(_index().values(), key=lambda r: -r.get("created_at", 0))}) or True
            if method == "POST":
                try:
                    data = base64.b64decode(str(body.get("data_base64", "")), validate=True)
                except ValueError as exc:
                    raise AvatarError(400, "data_base64 is not valid base64") from exc
                return j(handler, add_asset(data, str(body.get("name", ""))), status=201) or True
        ma = re.match(r"^/v1/assets/([a-f0-9]{64})(/file)?$", p)
        if ma and method == "GET":
            if not ma.group(2):
                return j(handler, get_asset(ma.group(1))) or True
            rec, data = asset_bytes(ma.group(1))
            handler.send_response(200)
            handler.send_header("Content-Type", rec["mime"])
            handler.send_header("Content-Length", str(len(data)))
            handler.send_header("Cache-Control", "private, max-age=31536000, immutable")
            handler.send_header("Content-Security-Policy", "default-src 'none'")
            handler.send_header("X-Content-Type-Options", "nosniff")
            handler.end_headers()
            handler.wfile.write(data)
            return True
        m = re.match(r"^/v1/agents/([^/]+)/avatar(?:/([a-z]+))?$", p)
        if m:
            aid, act = m.group(1), m.group(2) or ""
            if act == "" and method == "GET":
                return j(handler, get_avatar(aid)) or True
            if act == "" and method == "PUT":
                return j(handler, save_avatar(aid, body)) or True
            if act == "versions" and method == "GET":
                return j(handler, versions(aid)) or True
            if act == "restore" and method == "POST":
                return j(handler, restore(aid, body)) or True
            if act == "card" and method == "GET":
                card = get_avatar(aid)["card"]
                if not card:
                    raise AvatarError(404, "no card saved for this agent")
                return j(handler, card) or True
            if act == "emotion" and method == "PUT":
                return j(handler, set_emotion(aid, body)) or True
            if act == "visemes" and method == "GET":
                _agent(aid)
                q = parse_qs(parsed.query or "")
                return j(handler, visemes_stub((q.get("text") or [""])[0])) or True
        raise AvatarError(405, "method not allowed")
    except AvatarError as exc:
        j(handler, exc.payload, status=exc.status)
        return True
    except ValueError as exc:
        j(handler, {"error": str(exc)}, status=400)
        return True
