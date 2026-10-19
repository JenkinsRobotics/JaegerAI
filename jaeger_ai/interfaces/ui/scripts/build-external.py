"""Build the canonical shared UI outside source, preserving previous output."""
from pathlib import Path
import argparse
import hashlib
import os
import shutil
import subprocess
import tempfile
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mock', action='store_true')
    args = parser.parse_args()
    source = Path(__file__).resolve().parents[1]
    cache = Path.home() / '.cache/jaeger/ui-rebuild-mainscreen'
    cache.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix='build-', dir=cache))
    shutil.copytree(source, work, dirs_exist_ok=True, ignore=shutil.ignore_patterns('node_modules', 'dist', '.git'))
    dependencies = Path(os.environ.get('JAEGER_UI_DEPENDENCIES', str(Path.home() / '.cache/jaeger/reconcile-ui'))).expanduser()
    lock = lambda root: hashlib.sha256((root / 'package-lock.json').read_bytes()).hexdigest()
    if not (dependencies / 'node_modules/vite/bin/vite.js').is_file() or lock(dependencies) != lock(source):
        raise SystemExit('Matching external UI dependencies missing. Run npm ci in an external source snapshot; set JAEGER_UI_DEPENDENCIES to that folder.')
    (work / 'node_modules').symlink_to(dependencies / 'node_modules', target_is_directory=True)
    env = dict(os.environ)
    if args.mock:
        env['VITE_JAEGER_MOCK'] = '1'
    else:
        env.pop('VITE_JAEGER_MOCK', None)
    subprocess.run(['npm', 'run', 'build'], cwd=work, env=env, check=True)
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
