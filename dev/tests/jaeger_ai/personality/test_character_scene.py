"""Pack containment, data-only rendering, and real HTTP asset playback."""
from pathlib import Path

import pytest
from PIL import Image
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from jaeger_ai.features.personality.character import Character, load_character, characters_root
from jaeger_ai.features.personality.schema import Personality
from jaeger_ai.features.personality.scene import scene_asset, scene_presentation


def test_scene_assets_cannot_escape_pack_or_run_scripts(tmp_path):
    root = tmp_path / "pack"
    root.mkdir()
    Image.new('RGB', (2,2)).save(root / "image.png")
    (tmp_path / "secret.png").write_bytes(b"secret")
    (root / "link.png").symlink_to(tmp_path / "secret.png")
    (root / "script.svg").write_text('<svg onload="alert(1)"/>')
    char = Character(id="test", personality=Personality(), root=root,
        assets={"safe":"image.png", "escape":"../secret.png", "link":"link.png", "script":"script.svg", "absolute":str(tmp_path / "secret.png")},
        render={"scene":{"layout":"desk","actions":{"type":"safe","read":"escape","rest":"script"}}})
    assert scene_asset(char,"safe") == root / "image.png"
    for key in ("escape", "link", "script", "absolute", "../../secret"):
        assert scene_asset(char,key) is None
    presentation = scene_presentation(char)
    assert presentation["layout"] == "desk"
    assert set(presentation["actions"]) == {"type"}
    assert str(tmp_path) not in str(presentation)
    char.render['scene'] = {'layout': [], 'actions': None}
    assert scene_presentation(char)['layout'] == 'portrait'


def test_animated_images_require_controllable_video_instead(tmp_path):
    frames = [Image.new('RGB', (2,2), color) for color in ('red', 'blue')]
    frames[0].save(tmp_path / 'motion.gif', save_all=True, append_images=frames[1:], duration=100, loop=0)
    char = Character(id='motion', personality=Personality(), root=tmp_path, assets={'motion':'motion.gif'})
    assert scene_asset(char, 'motion') is None


def test_bundled_characters_keep_their_art_and_scene_style():
    for name, layout in (("mochi","desk"),("clanker","workbench")):
        pack = scene_presentation(load_character(characters_root() / name))
        assert pack["layout"] == layout
        assert pack["portrait"]["type"] == "image"


@pytest.mark.asyncio
async def test_scene_and_media_routes_use_real_http_and_video_ranges(tmp_path, monkeypatch):
    from jaeger_ai.core.gateway import character_routes
    root = tmp_path / 'packs'
    folder = root / 'test'
    folder.mkdir(parents=True)
    (folder / 'character.yaml').write_text('id: test\nassets:\n  primary: card.png\n  work: work.mp4\nrender:\n  scene:\n    layout: desk\n    actions: {type: work}\n')
    (folder / 'card.png').write_bytes(b'png')
    (folder / 'work.mp4').write_bytes(b'0123456789')
    monkeypatch.setattr(character_routes, 'characters_root', lambda: root)
    app = web.Application()
    character_routes.register_character_routes(app)
    async with TestClient(TestServer(app)) as client:
        response = await client.get('/v1/characters/test/scene')
        assert response.status == 200
        data = await response.json()
        assert data['actions']['type']['type'] == 'video'
        response = await client.get(data['actions']['type']['url'], headers={'Range':'bytes=2-5'})
        assert response.status == 206
        assert await response.read() == b'2345'
        assert response.headers['Content-Type'] == 'video/mp4'
        response = await client.get('/v1/characters/test/scene/assets/missing')
        assert response.status == 404


def test_authenticated_webui_proxy_preserves_binary_ranges(monkeypatch):
    import importlib.util
    import io
    import sys
    from types import SimpleNamespace
    from urllib.parse import urlparse

    source = Path(__file__).resolve().parents[4] / 'jaeger_ai/features/webui/api/character_scenes.py'
    spec = importlib.util.spec_from_file_location('scene_proxy_under_test', source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setitem(sys.modules, 'api.jaeger_agents', SimpleNamespace(gateway_base=lambda: 'http://127.0.0.1:33418'))
    monkeypatch.setitem(sys.modules, 'api.helpers', SimpleNamespace(bad=lambda *a: None))
    from jaeger_ai.core.gateway import caller_auth
    monkeypatch.setattr(caller_auth, 'client_headers', lambda caller: {'X-Test-Caller':caller})
    sent = {}

    class Connection:
        def __init__(self, *args, **kwargs): pass
        def request(self, method, path, headers): sent.update(method=method, path=path, headers=headers)
        def getresponse(self):
            return SimpleNamespace(status=206, read=lambda:b'\x00\x01\xff', getheader=lambda key:{'Content-Type':'video/mp4','Content-Range':'bytes 2-4/9'}.get(key))
        def close(self): sent['closed'] = True

    monkeypatch.setattr(module.http.client, 'HTTPConnection', Connection)
    headers = {}
    handler = SimpleNamespace(headers={'Range':'bytes=2-4'}, wfile=io.BytesIO(),
        send_response=lambda status:sent.update(status=status), send_header=headers.__setitem__, end_headers=lambda:None)
    assert module.route(handler, urlparse('/v1/characters/mochi/scene/assets/type'))
    assert handler.wfile.getvalue() == b'\x00\x01\xff'
    assert sent['status'] == 206
    assert sent['headers'] == {'Accept':'*/*','X-Test-Caller':'webui','Range':'bytes=2-4'}
    assert headers['Content-Range'] == 'bytes 2-4/9'
    assert sent['closed']
    assert not module.route(handler, urlparse('/v1/characters/mochi/scene/assets/../../secret'))
