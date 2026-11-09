"""Assemble Jaeger's native shell, owned Python environment, source and browser.

The dependency environment is an explicit build input. Its distributions are
recorded in the artifact; no operator state or credentials are copied.
"""
from __future__ import annotations

import argparse
import json
import hashlib
import re
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys


def run(*args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


def clone(source: Path, target: Path):
    target.parent.mkdir(parents=True, exist_ok=True)
    # APFS copy-on-write is a real independent copy, not an external symlink.
    run('/bin/cp', '-cR', str(source), str(target))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output-root', required=True, type=Path)
    parser.add_argument('--browser-bundle', required=True, type=Path)
    parser.add_argument('--provider-cli', action='append', default=[], help='Owner-supplied runtime NAME=/absolute/binary; kept out of source control')
    parser.add_argument('--dependency-python', default=sys.executable)
    parser.add_argument('--native-dependency-root', action='append', default=[], type=Path)
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    output = args.output_root.resolve()
    if repo == output or repo in output.parents:
        raise SystemExit('Build outside the repository')
    app = output / 'JaegerAI.app'
    if app.exists():
        raise SystemExit('Candidate already exists; use a new output directory')
    ui = repo / 'jaeger_ai/interfaces/ui/dist'
    if not (ui / 'index.html').is_file():
        raise SystemExit('Build the production UI first')
    browser = args.browser_bundle.resolve()
    json.loads((browser / 'manifest.json').read_text())
    raw = subprocess.check_output([args.dependency_python, '-B', '-c',
        'import sys,sysconfig,json,importlib.metadata as m; print(json.dumps(dict(base=sys.base_prefix,site=sysconfig.get_paths()["purelib"],version="%d.%d"%sys.version_info[:2],packages=sorted([[d.metadata["Name"],d.version] for d in m.distributions()]))))'], text=True)
    dependency = json.loads(raw)
    base = Path(dependency['base'])
    if not (base / 'PYTHON.json').is_file() and 'cpython-' not in base.name:
        raise SystemExit('A python-build-standalone interpreter is required; do not copy a Homebrew interpreter')
    shell_output = output / 'native-build'
    run('bash', str(repo / 'jaeger_ai/interfaces/macos-shell/Scripts/build-shell.sh'),
        env={**os.environ, 'JAEGER_MAC_BUILD': str(shell_output), 'JAEGER_MAC_CONFIGURATION': 'release'})
    app.parent.mkdir(parents=True, exist_ok=True)
    clone(shell_output / 'JaegerShell.app', app)
    runtime = app / 'Contents/Resources/runtime'
    runtime.mkdir(parents=True)
    clone(base, runtime / 'python')
    site = runtime / 'python/lib' / ('python' + dependency['version']) / 'site-packages'
    if site.exists():
        shutil.rmtree(site)
    clone(Path(dependency['site']), site)
    # Editable-path files would silently route back to the builder's checkout.
    for path in site.glob('*.pth'):
        if '__editable__' in path.name or any(line.startswith('/') for line in path.read_text().splitlines()):
            raise SystemExit(f'Nonportable dependency path file: {path.name}')
    # Jaeger does not use Qt SQL server drivers. They require external database
    # products (including proprietary Mimer); retain the self-contained SQLite driver.
    omitted = []
    for name in ('libqsqlmimer.dylib', 'libqsqlodbc.dylib', 'libqsqlpsql.dylib'):
        path = site / 'PySide6/Qt/plugins/sqldrivers' / name
        if path.exists():
            omitted.append(str(path.relative_to(runtime / 'python')))
            path.unlink()
    run(args.dependency_python, '-B', str(repo / 'scripts/bundle-macos-native.py'), str(runtime / 'python'), *[str(p.resolve()) for p in args.native_dependency_root])
    source = runtime / 'source'
    source.mkdir()
    files = subprocess.check_output(['git', 'ls-files', '-z', '--cached', '--others', '--exclude-standard'], cwd=repo).decode().split('\0')
    for name in dict.fromkeys(files):
        if not name:
            continue
        src, dst = repo / name, source / name
        if not src.exists():
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.is_symlink():
            dst.symlink_to(os.readlink(src))
        elif src.is_file():
            shutil.copy2(src, dst)
    bundled_ui = source / 'jaeger_ai/assets/shared-ui'
    if bundled_ui.exists():
        shutil.rmtree(bundled_ui)
    clone(ui, bundled_ui)
    clone(browser, runtime / 'browser')
    sha = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=repo, text=True).strip()
    dirty = bool(subprocess.check_output(['git', 'status', '--porcelain'], cwd=repo))
    (source / 'build-revision').write_text(sha + '\n')
    (runtime / 'dependency-manifest.json').write_text(json.dumps({'commit': sha, 'dirty': dirty, 'python': dependency['version'], 'distributions': dependency['packages'], 'omitted_unused_qt_sql_server_drivers': omitted}, indent=2) + '\n')
    launcher = runtime / 'bin/jaeger'
    launcher.parent.mkdir()
    providers = []
    for value in args.provider_cli:
        name, separator, filename = value.partition('=')
        if not separator or not re.fullmatch(r'[a-z][a-z0-9_-]{0,40}', name) or name == 'jaeger':
            raise SystemExit('Provider CLI must be NAME=/absolute/binary')
        binary = Path(filename).resolve()
        if not Path(filename).is_absolute() or not binary.is_file():
            raise SystemExit('Provider CLI must be an existing absolute binary path')
        shutil.copy2(binary, launcher.parent / name)
        (launcher.parent / name).chmod(0o755)
        providers.append({'name': name, 'sha256': hashlib.sha256(binary.read_bytes()).hexdigest(), 'source': str(binary), 'scope': 'owner-supplied local runtime; redistribution rights not asserted'})
    (runtime / 'provider-runtimes.json').write_text(json.dumps(providers, indent=2) + '\n')
    launcher.write_text('''#!/bin/sh
set -eu
runtime_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
export PYTHONDONTWRITEBYTECODE=1
export PYTHONNOUSERSITE=1
export JAEGER_INSTALL_ROOT="$runtime_dir/source"
export JAEGER_BUNDLED_BIN="$runtime_dir/bin"
export PATH="$JAEGER_BUNDLED_BIN:$runtime_dir/browser/node/bin:$PATH"
export JAEGER_RUNTIME_PYTHON="$runtime_dir/python/bin/python3"
export JAEGER_WEBUI_PYTHON="$JAEGER_RUNTIME_PYTHON"
export JAEGER_BROWSER_BUNDLE="$runtime_dir/browser"
export JAEGER_WEBUI_UI_DIST="$runtime_dir/source/jaeger_ai/assets/shared-ui"
export PYTHONPATH="$runtime_dir/source:$runtime_dir/source/packages/jaeger-agent:$runtime_dir/source/packages/jaeger-os:$runtime_dir/source/packages/jaeger-kokoro-tts:$runtime_dir/source/packages/jaeger-whisper-stt"
exec "$JAEGER_RUNTIME_PYTHON" -B -m jaeger_ai.cli.entry "$@"
''')
    launcher.chmod(0o755)
    info = app / 'Contents/Info.plist'
    with info.open('rb') as handle:
        plist = plistlib.load(handle)
    plist['JaegerLauncher'] = '@bundle/Contents/Resources/runtime/bin/jaeger'
    plist['CFBundleDisplayName'] = 'Jaeger'
    with info.open('wb') as handle:
        plistlib.dump(plist, handle)
    # Remove only Finder metadata; preserve quarantine and other security attributes.
    run('/usr/bin/xattr', '-dr', 'com.apple.FinderInfo', str(app))
    run('/usr/bin/xattr', '-dr', 'com.apple.ResourceFork', str(app))
    run('/usr/bin/codesign', '--force', '--sign', '-', str(app))
    run('/usr/bin/codesign', '--verify', '--deep', '--strict', str(app))
    print(app)


if __name__ == '__main__':
    main()
