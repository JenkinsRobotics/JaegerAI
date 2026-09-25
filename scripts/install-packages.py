#!/usr/bin/env python3
"""Build the monorepo's packages outside the checkout, then install their wheels.

Setuptools writes metadata beside its source even for a non-editable install.
Staging source in a temporary directory keeps installs and CI reproducible without
leaving build/, egg-info or caches in the developer's checkout.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

IGNORED = shutil.ignore_patterns(
    '.git', '.venv', '__pycache__', '.pytest_cache', '.ruff_cache',
    '*.egg-info', 'build', 'dist', '.build', '.swiftpm',
    '.jaeger*',
)


def install_package(spec: str, *, python: str, wheel_dir: Path | None = None,
                    install: bool = True, sdist: bool = False) -> Path | None:
    path_text, separator, extra_text = spec.partition('[')
    extras = ''
    if separator:
        if not extra_text.endswith(']'):
            raise ValueError(f'Invalid package extras: {spec}')
        extras = '[' + extra_text
    source = Path(path_text).resolve()
    if not (source / 'pyproject.toml').is_file():
        raise ValueError(f'No pyproject.toml in {source}')
    with tempfile.TemporaryDirectory(prefix='jaeger-package-') as temporary:
        scratch = Path(temporary)
        staged = scratch / 'source'
        shutil.copytree(source, staged, symlinks=True, ignore=IGNORED)
        wheels = scratch / 'wheels'
        subprocess.run([python, '-m', 'pip', 'wheel', '--no-deps',
                        '--wheel-dir', str(wheels), str(staged)], check=True)
        artifacts = list(wheels.glob('*.whl'))
        if len(artifacts) != 1:
            raise RuntimeError(f'Expected one wheel for {source}, found {len(artifacts)}')
        wheel = artifacts[0]
        exported = None
        if wheel_dir is not None:
            wheel_dir.mkdir(parents=True, exist_ok=True)
            exported = Path(shutil.copy2(wheel, wheel_dir / wheel.name))
        if sdist:
            if wheel_dir is None:
                raise ValueError('sdist requires a wheel directory')
            subprocess.run([python, '-m', 'build', '--sdist', '--outdir',
                            str(wheel_dir.resolve()), str(staged)], check=True)
        if install:
            subprocess.run([python, '-m', 'pip', 'install', str(wheel) + extras], check=True)
            # A new checkout can keep the same version; refresh its code after
            # dependency resolution without reinstalling every third-party wheel.
            subprocess.run([python, '-m', 'pip', 'install', '--force-reinstall',
                            '--no-deps', str(wheel)], check=True)
        return exported


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--python', default=sys.executable)
    parser.add_argument('--wheel-dir', type=Path)
    parser.add_argument('--no-install', action='store_true')
    parser.add_argument('--sdist', action='store_true', help='also export a source distribution')
    parser.add_argument('packages', nargs='+')
    args = parser.parse_args()
    if (args.no_install or args.sdist) and args.wheel_dir is None:
        parser.error('--no-install and --sdist require --wheel-dir')
    for spec in args.packages:
        install_package(spec, python=args.python, wheel_dir=args.wheel_dir,
                        install=not args.no_install, sdist=args.sdist)


if __name__ == '__main__':
    main()
