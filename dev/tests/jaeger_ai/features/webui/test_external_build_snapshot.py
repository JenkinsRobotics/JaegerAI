"""Build provenance must describe the compiled snapshot, not later source edits."""
from __future__ import annotations
import hashlib
import importlib.util
import json
from pathlib import Path
import sys


SCRIPT = Path(__file__).resolve().parents[5] / 'jaeger_ai/interfaces/ui/scripts/build-external.py'


def test_build_fingerprint_uses_immutable_input_snapshot(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location('_external_ui_builder', SCRIPT)
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    source = tmp_path / 'repo/jaeger_ai/interfaces/ui'
    for folder in ('src', 'public', 'vendor', 'scripts'):
        (source / folder).mkdir(parents=True)
    for name in ('package.json', 'package-lock.json', 'vite.config.ts', 'index.html', 'tsconfig.json'):
        (source / name).write_text('{}')
    (source / 'scripts/build-external.py').write_text('fixture script')
    (source / 'src/app.ts').write_text('compiled input')
    sibling = source.parent / 'ide/media'
    sibling.mkdir(parents=True)
    for name in ('timeline.js', 'timeline.d.ts'):
        (sibling / name).write_text('shared input')
    monkeypatch.setattr(builder, '__file__', str(source / 'scripts/build-external.py'))
    monkeypatch.delenv('JAEGER_UI_DEPENDENCIES', raising=False)
    output = tmp_path / 'external-build'
    monkeypatch.setattr(sys, 'argv', ['build-external.py', '--output-root', str(output)])

    def build(command, *, cwd, **kwargs):
        if command == ['npm', 'run', 'build']:
            (cwd / 'dist').mkdir()
            (cwd / 'dist/index.html').write_text('compiled input')
            # Model a concurrent editor after the isolated snapshot was copied.
            (source / 'src/app.ts').write_text('newer unbuilt input')

    monkeypatch.setattr(builder.subprocess, 'run', build)
    assert builder.main() == 0
    snapshot = next(output.glob('build-*/ui'))
    inputs = {str(p.relative_to(snapshot)): hashlib.sha256(p.read_bytes()).hexdigest()
              for folder in ('src', 'public', 'vendor', 'scripts')
              for p in sorted((snapshot / folder).rglob('*')) if p.is_file()}
    for name in ('timeline.js', 'timeline.d.ts'):
        inputs['../ide/media/' + name] = hashlib.sha256((snapshot.parent / 'ide/media' / name).read_bytes()).hexdigest()
    for name in ('package.json', 'package-lock.json', 'vite.config.ts', 'index.html', 'tsconfig.json'):
        inputs[name] = hashlib.sha256((snapshot / name).read_bytes()).hexdigest()
    expected = hashlib.sha256(json.dumps(inputs, sort_keys=True).encode()).hexdigest()
    manifest = json.loads((output / 'dist/build.json').read_text())
    assert manifest['sourceSha256'] == expected
    assert (source / 'src/app.ts').read_text() == 'newer unbuilt input'
