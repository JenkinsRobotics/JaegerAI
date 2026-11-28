"""The faces the avatar can wear, each from its own frozen files (the character owns its look; the app never makes one).

- `jaeger`: Jaeger AI's flat face (look.json), drawn by web/src/face.
- Each pack under avatars/ (avatar/v1, copied from Jaeger Avatar): an artist-made VRM drawn by web/src/vrm, with the
  pack's own character sheet (its persona rides on each turn; the Gateway's system prompt is never changed) and voice.

`python -m jaeger_ai.interfaces.nexus.faces` checks that the packs read and that a persona never shows in the chat.
"""
from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).parent
AVATARS = HERE / 'avatars'
LOOK = HERE / 'look.json'


def persona(ch: dict) -> str:
    """The pack's character sheet as a few lines the model reads before each message while this face is worn."""
    ident, lore = ch.get('identity') or {}, ch.get('lore') or {}
    parts = [(ch.get('prompt') or {}).get('custom_instructions') or f"You are {ch['name']}.",
             f"Role: {ident['role']}." if ident.get('role') else '',
             f"Voice: {ident['voice_tone']}." if ident.get('voice_tone') else '',
             f"Mannerisms: {'; '.join(lore['mannerisms'])}." if lore.get('mannerisms') else '']
    return ' '.join(p.strip() for p in parts if p and p.strip())


def pack(folder: Path) -> dict:
    import yaml   # PyYAML: a Jaeger AI dependency
    y = yaml.safe_load((folder / 'avatar.yaml').read_text())
    prof = y['profiles'][y['default_profile']]
    rep = y['representations'][y['default_representation']]
    render, ch = rep['presentation']['render'], prof['character']
    if render.get('adapter') != 'nori-vrm':
        raise ValueError(f"{folder.name}: only VRM packs are drawn here, not {render.get('adapter')!r}")
    base = f"/avatars/{folder.name}"
    return {'id': folder.name, 'name': y['name'], 'kind': 'vrm', 'version': y.get('version'),
            'model': f"{base}/{rep['root']}/{render['asset']}", 'card': f"{base}/{prof['card']}" if prof.get('card') else None,
            'voice': (ch.get('identity') or {}).get('voice_id'), 'persona': persona(ch), 'license': ch.get('license')}


def faces() -> list[dict]:
    flat = json.loads(LOOK.read_text())
    out = [{'id': 'jaeger', 'kind': 'flat', **flat}]
    for d in sorted(AVATARS.iterdir()) if AVATARS.is_dir() else []:
        if (d / 'avatar.yaml').is_file():
            out.append(pack(d))
    return out


def file(path: str) -> Path | None:
    """A pack file for GET /avatars/<pack>/...: only inside avatars/, never outside it."""
    p = (HERE / path.lstrip('/')).resolve()
    return p if p.is_file() and AVATARS.resolve() in p.parents else None


if __name__ == '__main__':
    fs = {f['id']: f for f in faces()}
    assert fs['jaeger']['kind'] == 'flat' and fs['jaeger']['style']
    v = fs['vita']
    assert v['kind'] == 'vrm' and file(v['model']) and file(v['card']), v
    assert v['voice'] == 'af_heart' and v['persona'].startswith('You are Vita'), v['persona']
    assert file('/avatars/../look.json') is None and file('/avatars/vita/../../faces.py') is None
    from .gateway import translate, unwrap, wrap   # the persona rides on the message and never shows in the chat
    w = wrap('hello', v['persona'])
    assert unwrap(w) == 'hello' and unwrap('hi') == 'hi' and wrap('x', None) == 'x'
    assert translate('run.started', {'prompt': w})[0]['text'] == 'hello'
    print('ok:', ', '.join(fs), '·', v['persona'][:80], '…')
