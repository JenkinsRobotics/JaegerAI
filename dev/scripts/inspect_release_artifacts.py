#!/usr/bin/env python3
"""Validate release archive contents and, optionally, the complete Python inventory."""
from __future__ import annotations

import argparse
from email.parser import Parser
import re
import tarfile
import zipfile
from pathlib import Path, PurePosixPath

FORBIDDEN = re.compile(
    r'(^|/)(?:__pycache__|\.pytest_cache|\.mypy_cache|\.ruff_cache|\.build|build|dist|node_modules)(/|$)'
    r'|\.(?:py[co]|db|sqlite(?:3)?|log)$|(^|/)\.DS_Store$'
)
PACKAGES = ('jaeger_ai', 'jaeger_agent', 'jaeger_os', 'jaeger_kokoro_tts', 'jaeger_whisper_stt')
REQUIRED_SUFFIXES = {
    'jaeger_ai-': (
        'jaeger_ai/core/instance/schemas.py', 'jaeger_ai/core/settings/catalog.py',
        'jaeger_ai/core/runtime/agent_controller.py', 'jaeger_ai/features/webui/service/service.py',
        'jaeger_ai/assets/shared-ui/index.html', 'jaeger_ai/assets/shared-ui/build.json',
    ),
    'jaeger_agent-': (
        'jaeger_agent/assets/silero/silero_vad_16k_op15.onnx',
        'jaeger_agent/assets/silero/LICENSE.txt', 'jaeger_agent/background/thinking_runner.yaml',
    ),
}


def members(path: Path) -> list[str]:
    if path.name.endswith(('.whl', '.vsix', '.zip')):
        with zipfile.ZipFile(path) as archive:
            if archive.testzip() is not None:
                raise ValueError('corrupt ZIP member')
            return archive.namelist()
    if path.name.endswith(('.tar.gz', '.tgz')):
        with tarfile.open(path) as archive:
            return archive.getnames()
    raise ValueError('unsupported release artifact type')


def read_member(path: Path, name: str) -> bytes:
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as archive:
            return archive.read(name)
    with tarfile.open(path) as archive:
        stream = archive.extractfile(name)
        if stream is None:
            raise ValueError(f'not a regular archive member: {name}')
        return stream.read()


def inspect(path: Path) -> list[str]:
    import json
    errors = []
    try:
        names = members(path)
        if not names:
            return ['empty release archive']
        for name in names:
            parts = PurePosixPath(name)
            if parts.is_absolute() or '..' in parts.parts or '\\' in name or FORBIDDEN.search(name):
                errors.append(f'unsafe member: {name}')
        for prefix, required in REQUIRED_SUFFIXES.items():
            if path.name.startswith(prefix):
                for suffix in required:
                    if not any(n.endswith(suffix) for n in names):
                        errors.append(f'missing runtime member: {suffix}')
        if path.name.startswith('jaeger_ai-'):
            metadata_name = next((n for n in names if n.endswith(('.dist-info/METADATA', '/PKG-INFO'))), None)
            if not metadata_name:
                errors.append('missing package metadata')
            else:
                metadata = Parser().parsestr(read_member(path, metadata_name).decode())
                required = {re.split(r'[\s<>=!~;\[]', v)[0].replace('_', '-').lower()
                            for v in metadata.get_all('Requires-Dist', [])}
                for package in PACKAGES[1:]:
                    if package.replace('_', '-') not in required:
                        errors.append(f'missing dependency: {package}')
            manifest = next((n for n in names if n.endswith('jaeger_ai/assets/shared-ui/build.json')), None)
            if manifest:
                info = json.loads(read_member(path, manifest))
                if info.get('mock') is not False or not re.fullmatch(r'[0-9a-f]{64}', info.get('sourceSha256', '')):
                    errors.append('UI build is mocked or has no source fingerprint')
            if not any('/assets/shared-ui/assets/' in n and n.endswith('.js') for n in names):
                errors.append('missing compiled shared UI JavaScript')
    except (OSError, ValueError, KeyError, zipfile.BadZipFile, tarfile.TarError) as exc:
        errors.append(str(exc))
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    parser.add_argument('--require-packages', action='store_true', help='require wheels and sdists for all five packages')
    args = parser.parse_args()
    artifacts = sorted(p for p in args.directory.iterdir() if p.is_file())
    if not artifacts:
        parser.error('no release artifacts found')
    failed = False
    for artifact in artifacts:
        errors = inspect(artifact)
        failed |= bool(errors)
        print(f'{artifact}: ' + ('INVALID' if errors else 'archive checks passed (not runtime qualification)'))
        for error in errors:
            print(f'  {error}')
    if args.require_packages:
        for name in PACKAGES:
            for suffix in ('.whl', '.tar.gz'):
                matches = [p for p in artifacts if p.name.startswith(name + '-') and p.name.endswith(suffix)]
                if len(matches) != 1:
                    failed = True
                    print(f'Expected exactly one {name} {suffix}, found {len(matches)}')
    return int(failed)


if __name__ == '__main__':
    raise SystemExit(main())
