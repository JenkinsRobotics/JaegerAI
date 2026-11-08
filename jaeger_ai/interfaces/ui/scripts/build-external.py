"""Build and optionally test the shared UI outside source, preserving previous output."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mock', action='store_true')
    parser.add_argument('--test', action='store_true', help='run component tests before building')
    parser.add_argument('--output-root', type=Path,
                        default=Path.home() / '.cache/jaeger/ui-rebuild-mainscreen')
    args = parser.parse_args()
    source = Path(__file__).resolve().parents[1]
    repo = source.parents[2]
    cache = args.output_root.expanduser().resolve()
    if cache == repo or repo in cache.parents:
        parser.error('output-root must be outside the repository')
    cache.mkdir(parents=True, exist_ok=True)
    snapshot = Path(tempfile.mkdtemp(prefix='build-', dir=cache))
    work = snapshot / 'ui'
    # Preserve the canonical sibling layout for the shared IDE/browser reducer.
    shared = source.parent / 'ide' / 'media'
    shared_files = ('timeline.js', 'timeline.d.ts')
    (snapshot / 'ide' / 'media').mkdir(parents=True)
    for name in shared_files:
        shutil.copy2(shared / name, snapshot / 'ide' / 'media' / name)
    shutil.copytree(source, work, dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns('node_modules', 'dist', '.git',
                                                 'test-results', 'playwright-report'))
    dependencies = os.environ.get('JAEGER_UI_DEPENDENCIES')
    if dependencies:
        dependencies = Path(dependencies).expanduser().resolve()
        lock = lambda root: hashlib.sha256((root / 'package-lock.json').read_bytes()).hexdigest()
        if not (dependencies / 'node_modules/vite/bin/vite.js').is_file() or lock(dependencies) != lock(source):
            parser.error('JAEGER_UI_DEPENDENCIES must contain matching lockfile and installed dependencies')
        (work / 'node_modules').symlink_to(dependencies / 'node_modules', target_is_directory=True)
    else:
        # A fresh install must work without a developer-prepared dependency cache.
        subprocess.run(['npm', 'ci'], cwd=work, check=True)
    env = dict(os.environ)
    env.pop('VITE_JAEGER_MOCK', None)
    if args.mock:
        env['VITE_JAEGER_MOCK'] = '1'
    if args.test:
        subprocess.run(['npm', 'test', '--', '--cache=false'], cwd=work, env=env, check=True)
    subprocess.run(['npm', 'run', 'build'], cwd=work, env=env, check=True)
    if not (work / 'dist/index.html').is_file():
        raise RuntimeError('UI build produced no index.html')
    inputs = {str(p.relative_to(source)): hashlib.sha256(p.read_bytes()).hexdigest()
              for folder in ('src', 'public', 'vendor', 'scripts')
              for p in sorted((source / folder).rglob('*')) if p.is_file()}
    for name in shared_files:
        inputs['../ide/media/' + name] = hashlib.sha256((shared / name).read_bytes()).hexdigest()
    for name in ('package.json', 'package-lock.json', 'vite.config.ts', 'index.html', 'tsconfig.json'):
        inputs[name] = hashlib.sha256((source / name).read_bytes()).hexdigest()
    (work / 'dist/build.json').write_text(json.dumps({
        'mock': args.mock, 'sourceSha256': hashlib.sha256(
            json.dumps(inputs, sort_keys=True).encode()).hexdigest(),
        'lockSha256': inputs['package-lock.json'],
    }, sort_keys=True, indent=2) + '\n')
    output = cache / ('dist-mock' if args.mock else 'dist')
    if output.exists():
        previous = cache / 'previous' / (time.strftime('%Y%m%d-%H%M%S') + '-' + str(os.getpid()))
        previous.mkdir(parents=True)
        shutil.move(str(output), str(previous / output.name))
    shutil.move(str(work / 'dist'), str(output))
    print('Canonical shared UI built:', output)
    print('External source snapshot:', work)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
