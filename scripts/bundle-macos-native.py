"""Close absolute Mach-O library dependencies inside a standalone app."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import hashlib
import json
import os
import shutil
import subprocess
import sys


def output(*args):
    return subprocess.check_output(args, text=True, stderr=subprocess.DEVNULL)


def bundle(root: Path, inputs: list[Path]):
    root = root.resolve()
    target = root / 'lib/jaeger-native'
    target.mkdir(parents=True, exist_ok=True)
    copied = {}
    patched = set()
    records = []
    def inspect(path):
        try:
            rows = output('/usr/bin/otool', '-L', str(path)).splitlines()[1:]
            return path, [row.strip().split(' (compatibility')[0] for row in rows if row.startswith('\t')]
        except subprocess.CalledProcessError:
            return path, []
    pending = list({p.resolve() for p in root.rglob('*') if p.is_file() and (p.suffix in ('.so', '.dylib') or p.parent.name == 'bin')})
    while pending:
        with ThreadPoolExecutor(8) as pool:
            results = list(pool.map(inspect, pending))
        pending = []
        for path, dependencies in results:
            absolute = [dep for dep in dependencies if dep.startswith('/') and not dep.startswith(('/System/', '/usr/lib/'))]
            if not absolute:
                continue
            ids = output('/usr/bin/otool', '-D', str(path)).splitlines()[1:]
            for dep in absolute:
                if dep in ids:
                    subprocess.run(['/usr/bin/install_name_tool', '-id', '@rpath/' + path.name, str(path)], check=True, capture_output=True)
                    patched.add(path)
                    continue
                source = Path(dep)
                if not source.is_file():
                    matches = [p for directory in inputs for p in directory.rglob(source.name) if p.is_file()]
                    if not matches:
                        raise RuntimeError(f'Missing native dependency: {dep} required by {path}')
                    source = matches[0]
                source = source.resolve()
                if root in source.parents:
                    destination = source
                elif source in copied:
                    destination = copied[source]
                else:
                    digest = hashlib.sha256(source.read_bytes()).hexdigest()
                    destination = target / (digest[:12] + '-' + source.name)
                    shutil.copy2(source, destination)
                    destination.chmod(0o755)
                    copied[source] = destination
                    pending.append(destination)
                    record = {'source': str(source), 'sha256': digest, 'bundled': str(destination.relative_to(root)), 'licenses': []}
                    # Homebrew formulas retain the upstream notices beside lib/.
                    for parent in list(source.parents)[:3]:
                        for pattern in ('LICENSE*', 'COPYING*', 'NOTICE*'):
                            for notice in parent.glob(pattern):
                                if notice.is_file():
                                    dest = target / 'licenses' / (digest[:12] + '-' + notice.name)
                                    dest.parent.mkdir(exist_ok=True)
                                    shutil.copy2(notice, dest)
                                    record['licenses'].append(str(dest.relative_to(root)))
                    if not record['licenses']:
                        raise RuntimeError(f'No distribution notice found for {source}')
                    records.append(record)
                relative = '@loader_path/' + os.path.relpath(destination, path.parent)
                path.chmod(path.stat().st_mode | 0o200)
                subprocess.run(['/usr/bin/install_name_tool', '-change', dep, relative, str(path)], check=True, capture_output=True)
                patched.add(path)
    for path in patched:
        subprocess.run(['/usr/bin/codesign', '--force', '--sign', '-', str(path)], check=True, capture_output=True)
    (target / 'manifest.json').write_text(json.dumps(records, indent=2) + '\n')
    print(f'Bundled {len(copied)} native libraries; relocated {len(patched)} files')


if __name__ == '__main__':
    bundle(Path(sys.argv[1]), [Path(p) for p in sys.argv[2:]])
