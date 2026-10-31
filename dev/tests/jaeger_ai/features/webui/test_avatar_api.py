"""Agent avatar API: asset inspection + validation (§6a), versions/restore, card round-trip, emotion, viseme stub."""
from __future__ import annotations

import importlib.util
import json
import pathlib
import struct
import sys
import types

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[5] / "jaeger_ai/features/webui/api/avatar_api.py"


def png(w: int, h: int, pad: int = 0) -> bytes:
    return b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + struct.pack(">II", w, h) + b"\x08\x06\x00\x00\x00" + b"\0" * (4 + pad)


def glb(doc: dict) -> bytes:
    js = json.dumps(doc).encode()
    js += b" " * (-len(js) % 4)
    body = struct.pack("<II", len(js), 0x4E4F534A) + js
    return b"glTF" + struct.pack("<II", 2, 12 + len(body)) + body


VRM = {"asset": {"version": "2.0"}, "extensionsUsed": ["VRMC_vrm"],
       "extensions": {"VRMC_vrm": {"specVersion": "1.0", "meta": {"name": "t", "authors": ["MJ"], "licenseUrl": "https://example.org/l", "commercialUsage": "personalNonProfit"},
                                   "expressions": {"preset": {"happy": {}, "sad": {}, "aa": {}, "ih": {}, "ou": {}, "ee": {}, "oh": {}, "relaxed": {}}}}},
       "accessors": [{"count": 300}], "meshes": [{"primitives": [{"attributes": {"POSITION": 0}, "indices": 0}]}],
       "materials": [{}], "animations": [{"name": "idle_breathe"}]}


@pytest.fixture()
def av(tmp_path, monkeypatch):
    monkeypatch.setenv("JAEGER_STATE_HOME", str(tmp_path))
    spec = importlib.util.spec_from_file_location("_avatar_api_t", ROOT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def ext(av, model, fb, **over):
    asset = model
    e = {"schema": av.SCHEMA, "format": asset["format"], "format_version": asset.get("format_version") if asset["format"] != "image" else None,
         "asset": {"uri": asset["uri"]}, "fallback": {"uri": fb["uri"]},
         "states": {s: {"animation": None, "expression": "neutral"} for s in av.REQUIRED_STATES},
         "emotions": {"neutral": {"neutral": 1}, "happy": {"happy": 1}}, "visemes": {"profile": "vrm5", "map": {"A": "aa", "sil": None}},
         "license": {"spdx": "CC-BY-4.0", "author": "Matthew Jenkins", "commercial": True}, "version": "1.0.0", "x_unknown": {"keep": [1, 2]}}
    e.update(over)
    return e


def test_inspect_vrm_reads_stats_from_bytes(av):
    a = av.add_asset(glb(VRM), "t.vrm")
    assert a["format"] == "vrm" and a["format_version"] == "1.0" and a["triangles"] == 100 and a["materials"] == 1
    assert "happy" in a["expressions"] and a["animations"] == ["idle_breathe"] and a["uri"] == f"jaeger-asset://{a['sha256']}"
    plain = av.add_asset(glb({"asset": {"version": "2.0"}}), "bot.glb")
    assert plain["format"] == "glb"


@pytest.mark.parametrize("data,name,rule", [
    (glb({"asset": {"version": "2.0"}, "extensionsUsed": ["VRM"], "extensions": {"VRM": {}}}), "old.vrm", 2),
    (glb({"asset": {"version": "2.0"}, "images": [{"uri": "https://x/t.png"}]}), "ext.glb", 10),
    (b"MOC3xxxx", "a.moc3", 2),
    (b"<html>", "x.html", 3),
])
def test_rejects_with_rule(av, data, name, rule):
    with pytest.raises(av.AvatarError) as ei:
        av.add_asset(data, name)
    assert ei.value.payload["rule"] == rule


def test_budget_warns_and_rejects(av):
    info = {"format": "glb", "triangles": 60_000}
    r = av.budget_report(info, 9 * av.MB)
    assert not r["devices"]["iphone"]["ok"] and r["devices"]["desktop"]["ok"] and not r["rejected"]
    assert av.budget_report(info, 17 * av.MB)["rejected"]


def test_save_validate_version_restore_and_roundtrip(av):
    model = av.add_asset(glb(VRM), "t.vrm")
    fb = av.add_asset(png(512, 512), "fb.png")
    out = av.save_avatar("jaeger", {"avatar": ext(av, model, fb)})
    assert out["avatar"]["version"] == "1.0.0" and out["avatar"]["asset"]["sha256"] == model["sha256"]
    assert any("non-profit" in w for w in out["report"]["warnings"])  # VRM meta vs card licence
    out2 = av.save_avatar("jaeger", {"avatar": {**out["avatar"], "customization": {"primary": "#8d7337"}}})
    assert out2["avatar"]["version"] == "1.1.0" and out2["avatar"]["history"][0]["version"] == "1.0.0"
    assert out2["avatar"]["x_unknown"] == {"keep": [1, 2]}
    v = av.versions("jaeger")
    assert v["current"]["version"] == "1.1.0" and v["history"][0]["sha256"] == model["sha256"]
    r = av.restore("jaeger", {"version": "1.0.0"})
    assert r["avatar"]["version"] == "1.2.0" and "customization" not in r["avatar"] and r["avatar"]["asset"]["sha256"] == model["sha256"]
    card = av.get_avatar("jaeger")["card"]
    card["data"]["extensions"]["other_app"] = {"z": 1}
    again = av.save_avatar("jaeger", {"card": card})
    assert again["card"]["data"]["extensions"]["other_app"] == {"z": 1}


@pytest.mark.parametrize("over,rule", [
    ({"schema": "x"}, 1), ({"format": "live2d"}, 2), ({"states": {"idle": {}}}, 5),
    ({"emotions": {"happy": {"happy": 2}}}, 6), ({"visemes": {"profile": "nope"}}, 7),
    ({"license": {"spdx": "MIT"}}, 8), ({"version": "v1"}, 9),
    ({"states": {s: {"animation": "dance"} for s in ("idle", "listening", "thinking", "speaking")}}, 5),
])
def test_validation_rules(av, over, rule):
    model = av.add_asset(glb(VRM), "t.vrm")
    fb = av.add_asset(png(512, 512), "fb.png")
    rep = av.validate(ext(av, model, fb, **over))
    assert not rep["ok"] and rule in {e["rule"] for e in rep["errors"]}


def test_fallback_rules_and_uri(av):
    fb_bad = av.add_asset(png(256, 128), "small.png")
    model = av.add_asset(glb(VRM), "t.vrm")
    rep = av.validate(ext(av, model, fb_bad))
    assert {e["rule"] for e in rep["errors"]} == {4}
    rep = av.validate(ext(av, model, fb_bad, asset={"uri": "file:///etc/passwd"}))
    assert 3 in {e["rule"] for e in rep["errors"]}


def test_history_immutable_and_bad_ids(av):
    fb = av.add_asset(png(512, 512), "fb.png")
    e = ext(av, fb, fb, format="image", format_version=None)
    av.save_avatar("a1", {"avatar": e})
    cur = av.save_avatar("a1", {"avatar": e})["avatar"]
    cur["history"][0]["version"] = "9.9.9"
    with pytest.raises(av.AvatarError):
        av.save_avatar("a1", {"card": {"spec": "chara_card_v3", "data": {"extensions": {"jaeger": {"avatar": {**cur, "version": "9.0.0"}}}}}})
    with pytest.raises(av.AvatarError):
        av.get_avatar("../etc")


def test_emotion_and_viseme_stub(av):
    assert av.get_avatar("jaeger")["live"]["source"] == "default"
    assert av.set_emotion("jaeger", {"emotion": "warm", "intensity": 0.6})["emotion"] == "warm"
    assert av.get_avatar("jaeger")["live"]["intensity"] == 0.6
    with pytest.raises(av.AvatarError):
        av.set_emotion("jaeger", {"emotion": "angry"})
    v = av.visemes_stub("Hello there.")
    assert v["stub"] is True and v["timeline"][-1]["viseme"] == "sil" and {"E", "O"} <= {x["viseme"] for x in v["timeline"]}


class _H:
    def __init__(self):
        self.status, self.headers, self.body = None, {}, b""
        self.wfile = types.SimpleNamespace(write=lambda b: setattr(self, "body", self.body + b))
    def send_response(self, s): self.status = s
    def send_header(self, k, v): self.headers[k] = v
    def end_headers(self): pass


def test_router(av):
    import base64
    got = {}
    j = lambda h, data, status=200: got.update(data=data, status=status)
    body = {"name": "fb.png", "data_base64": base64.b64encode(png(512, 512)).decode()}
    P = lambda path, q="": types.SimpleNamespace(path=path, query=q)
    assert av.route(_H(), P("/v1/assets"), "POST", lambda h: body, j) and got["status"] == 201
    sha = got["data"]["sha256"]
    h = _H()
    assert av.route(h, P(f"/v1/assets/{sha}/file"), "GET", None, j) and h.status == 200 and h.body[:4] == b"\x89PNG"
    assert av.route(_H(), P("/v1/agents/jaeger/avatar/visemes", "text=hi"), "GET", None, j) and got["data"]["stub"] is True
    assert av.route(_H(), P("/v1/agents/jaeger/avatar"), "GET", None, j) and got["data"]["avatar"] is None
    assert av.route(_H(), P("/v1/agents/jaeger/avatar"), "PUT", lambda h: {"avatar": {"schema": "bad"}}, j) and got["status"] == 422
    assert not av.route(_H(), P("/v1/agents/jaeger/sessions"), "GET", None, j)
