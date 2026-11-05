"""Reject Python writes to operator state, rather than attributing unrelated changes."""
from __future__ import annotations

import os
from pathlib import Path
import sys


def install(roots: tuple[Path, ...]) -> None:
    protected = tuple(p.resolve() for p in roots)
    writing = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND

    def check(value):
        if not isinstance(value, (str, bytes, os.PathLike)):
            return
        path = Path(os.fsdecode(value)).resolve()
        if any(path == root or root in path.parents for root in protected):
            raise PermissionError(f'Test attempted to write protected operator state: {path}')

    def guard(event, args):
        if event == 'open':
            path, mode, flags = args
            if (flags or 0) & writing or (mode and any(c in mode for c in 'wax+')):
                check(path)
        elif event == 'sqlite3.connect':
            # SQLite can write through native code, beyond Python open hooks.
            check(args[0])
        elif event in {'os.mkdir', 'os.remove', 'os.rmdir', 'os.chmod', 'os.chown', 'os.truncate', 'os.utime'}:
            check(args[0])
        elif event in {'os.rename', 'os.link'}:
            check(args[0]); check(args[1])
        elif event == 'os.symlink':
            check(args[1])
    sys.addaudithook(guard)
