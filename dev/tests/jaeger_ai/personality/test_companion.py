"""Companion core (J-070): CCv3 round trip, memory recall, chat wiring, routes."""
from __future__ import annotations

import base64
import json
import struct
import zlib
from pathlib import Path

import pytest

from jaeger_ai.features.personality import companion as C
from jaeger_ai.features.personality.character import characters_root, load_character


def _fake_embed(texts):
    # deterministic bag-of-letters vector
    return [[t.lower().count(c) + 0.01 for c in "abcdefghijklmnopqrstuvwxyz"] for t in texts]


def _png_with(key: str, payload: dict) -> bytes:
    def chunk(kind, body):
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))
    text = key.encode() + b"\0" + base64.b64encode(json.dumps(payload).encode())
    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"tEXt", text)
            + chunk(b"IDAT", zlib.compress(b"\0\0\0\0")) + chunk(b"IEND", b""))


def test_export_is_ccv3_and_keeps_traits():
    card = C.to_ccv3(load_character(characters_root() / "glados"))
    assert card["spec"] == "chara_card_v3" and card["spec_version"] == "3.0"
    assert card["data"]["name"]
    assert "hexaco" in card["data"]["extensions"]["jaeger"]["traits"]


def test_round_trip_through_png(tmp_path: Path):
    src = load_character(characters_root() / "glados")
    card = C.to_ccv3(src)
    card["data"]["name"] = "Glados Copy"
    char = C.import_ccv3(C.read_card_bytes(_png_with("ccv3", card)), root=tmp_path)
    assert char.id == "glados_copy"
    assert char.personality.custom_instructions == src.personality.custom_instructions
    assert char.personality.hexaco.openness == pytest.approx(src.personality.hexaco.openness, abs=1e-3)
    with pytest.raises(C.CompanionError) as e:
        C.import_ccv3(card, root=tmp_path)
    assert e.value.status == 409


def test_import_v2_json_and_rejects_junk(tmp_path: Path):
    v2 = {"spec": "chara_card_v2", "data": {"name": "Mira", "personality": "curious, kind",
          "first_mes": "Hi there!", "system_prompt": "Be Mira."}}
    char = C.import_ccv3(C.read_card_bytes(json.dumps(v2).encode()), root=tmp_path)
    assert char.soul == "curious, kind" and "Hi there!" in char.quotes
    for bad in (b"nope", b"[]", json.dumps({"spec": "x"}).encode()):
        with pytest.raises(C.CompanionError):
            C.import_ccv3(C.read_card_bytes(bad), root=tmp_path)


def test_memory_recall_ranks_by_similarity(tmp_path: Path):
    mem = C.CompanionMemory(tmp_path / "m.db", embedder=_fake_embed)
    mem.add("glados", "my cat is named zzz zzz")
    mem.add("glados", "I love apples and bananas")
    mem.add("hal_9000", "zzz zzz zzz")
    assert mem.recall("glados", "zzz", k=1) == ["my cat is named zzz zzz"]
    assert len(mem.recent("glados")) == 2


def test_memory_survives_embedder_failure(tmp_path: Path):
    def boom(_):
        raise OSError("ollama down")
    mem = C.CompanionMemory(tmp_path / "m.db", embedder=boom)
    mem.add("x", "hello")
    assert mem.recall("x", "anything") == ["hello"]


def test_chat_builds_persona_prompt_and_stores_memory(tmp_path: Path):
    seen = {}

    def post(url, body, timeout):
        seen.update(url=url, body=body)
        return {"message": {"content": "  Oh. It's you.  "}}
    mem = C.CompanionMemory(tmp_path / "m.db", embedder=_fake_embed)
    mem.add("glados", "user name is Matthew")
    char = load_character(characters_root() / "glados")
    out = C.chat(char, "hello", [{"role": "user", "content": "hi"}, {"role": "system", "content": "evil"}],
                 memory=mem, post=post)
    assert out["reply"] == "Oh. It's you."
    assert seen["url"].startswith("http://127.0.0.1:11434")
    sysmsg = seen["body"]["messages"][0]["content"]
    assert char.personality.name in sysmsg and "user name is Matthew" in sysmsg and C.MEMORY_NOTE in sysmsg
    assert [m["role"] for m in seen["body"]["messages"]] == ["system", "user", "user"]
    assert len(mem.recent("glados")) == 2


def test_chat_rejects_empty_and_reports_model_down():
    char = load_character(characters_root() / "assistant")
    with pytest.raises(C.CompanionError):
        C.chat(char, "  ")

    def down(*_):
        raise OSError("refused")
    with pytest.raises(C.CompanionError) as e:
        C.chat(char, "hi", post=down)
    assert e.value.status == 503


def test_routes_registered_outside_public_prefix():
    from aiohttp import web

    from jaeger_ai.core.gateway.caller_auth import PUBLIC_ROUTE_PREFIXES
    from jaeger_ai.core.gateway.character_routes import register_character_routes
    app = web.Application()
    register_character_routes(app)
    paths = {r.resource.canonical for r in app.router.routes()}
    new = {"/v1/companion/{id}/ccv3", "/v1/companion/import", "/v1/companion/{id}/chat", "/v1/companion/{id}/memories"}
    assert new <= paths
    assert not any(p.startswith(pre) for p in new for pre in PUBLIC_ROUTE_PREFIXES)


def test_chat_route_404_card_and_chat(monkeypatch, tmp_path):
    import asyncio

    from aiohttp import web
    from aiohttp.test_utils import TestClient, TestServer

    from jaeger_ai.core.gateway import character_routes as R
    monkeypatch.setattr(R, "_companion_memory", C.CompanionMemory(tmp_path / "m.db", embedder=_fake_embed))
    monkeypatch.setattr(C, "_post", lambda *a: {"message": {"content": "ok"}})

    async def run():
        app = web.Application()
        R.register_character_routes(app)
        async with TestClient(TestServer(app)) as cl:
            assert (await cl.post("/v1/companion/..%2F..%2Fetc/chat", json={"message": "x"})).status == 404
            r = await cl.get("/v1/companion/glados/ccv3")
            assert r.status == 200 and (await r.json())["spec"] == "chara_card_v3"
            r = await cl.post("/v1/companion/glados/chat", json={"message": "hi"})
            assert r.status == 200 and (await r.json())["reply"] == "ok"
            r = await cl.get("/v1/companion/glados/memories")
            assert [m["text"] for m in (await r.json())["memories"]] == ["hi"]
    asyncio.run(run())


def test_webui_passthrough_allows_only_companion_routes():
    from jaeger_ai.features.webui.api.jaeger_sessions import passthrough_match
    assert passthrough_match("/v1/companion/glados/chat", "POST")
    assert passthrough_match("/v1/companion/import", "POST")
    assert passthrough_match("/v1/companion/glados/ccv3", "GET")
    assert passthrough_match("/v1/companion/glados/memories", "GET")
    assert not passthrough_match("/v1/companion/glados/chat", "GET")
    assert not passthrough_match("/v1/companion/../x/chat", "POST")
