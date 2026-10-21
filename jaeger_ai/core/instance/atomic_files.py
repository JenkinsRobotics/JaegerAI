"""Shared atomic document IO; existing schema/config owners retain authority.

Stable locks resolve through operator_state_root, never into a source tree.
No application/runtime initialization, credential lookup or access expansion.
"""
from pathlib import Path

from pydantic import BaseModel


def file_revision(path: Path) -> str:
    import hashlib
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_unlocked(path: Path, payload: str, *, expected_revision: str | None = None) -> None:
    import os
    import stat
    import tempfile
    path.parent.mkdir(parents=True,exist_ok=True)
    mode=stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o600
    descriptor,name=tempfile.mkstemp(prefix='.'+path.name+'-',suffix='.tmp',dir=path.parent)
    temporary=Path(name)
    try:
        with os.fdopen(descriptor,'w',encoding='utf-8') as handle:
            handle.write(payload);handle.flush();os.fchmod(handle.fileno(),mode);os.fsync(handle.fileno())
        if expected_revision is not None and file_revision(path)!=expected_revision:
            raise ValueError('Configuration changed before commit; current file retained')
        os.replace(temporary,path)
        parent=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY)
        try:os.fsync(parent)
        finally:os.close(parent)
    finally:temporary.unlink(missing_ok=True)


def _file_write_lock(path: Path):
    """Stable shared write lock, outside source trees; no config authority."""
    import fcntl
    import hashlib
    import os
    import stat
    from contextlib import contextmanager

    from jaeger_ai.core.instance.instance import operator_state_root
    @contextmanager
    def acquire():
        root=operator_state_root()/'run'/'schema-write-locks';root.mkdir(parents=True,exist_ok=True)
        key=hashlib.sha256(str(path.resolve()).encode()).hexdigest()
        descriptor=os.open(root/(key+'.lock'),os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW|os.O_NONBLOCK,0o600)
        with os.fdopen(descriptor,'r+') as handle:
            if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):raise OSError('Schema write lock unavailable')
            import time
            deadline=time.monotonic()+5
            while True:
                try:
                    fcntl.flock(handle.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic()>=deadline:raise ValueError('Document writer busy; no update started') from None
                    time.sleep(0.01)
            yield
    return acquire()


def atomic_write(path: Path, payload: str) -> None:
    with _file_write_lock(path):_write_unlocked(path,payload)


def read_yaml_versioned(path: Path, model_cls: type[BaseModel]):
    import hashlib

    import yaml
    with _file_write_lock(path):
        raw=path.read_bytes()
        return model_cls.model_validate(yaml.safe_load(raw) or {}),hashlib.sha256(raw).hexdigest()


def mutate_yaml(path: Path, model_cls: type[BaseModel], transform, *, expected_revision: str | None = None, before_commit=None):
    """Load/validate/patch/CAS/replace one existing document under its write lock.

    Normal setting owners supply a field transform, never a stale whole-file
    snapshot. Low-level dump_yaml remains an explicit full replacement writer.
    """
    import hashlib

    import yaml
    with _file_write_lock(path):
        raw=path.read_bytes();revision=hashlib.sha256(raw).hexdigest()
        if expected_revision is not None and revision!=expected_revision:raise ValueError('Configuration changed; review current settings')
        original=yaml.safe_load(raw) or {}
        current=model_cls.model_validate(original)
        changed=transform(current.model_copy(deep=True))
        result=model_cls.model_validate(changed.model_dump())
        different=result!=current
        # Apply only actual schema field changes to the original document.
        # Unrelated unknown/future fields (including nested ones) are retained.
        def patch(document,before,after):
            output=dict(document) if isinstance(document,dict) else {}
            for key,value in after.items():
                if key in before and before[key]==value:continue
                if isinstance(value,dict) and isinstance(before.get(key),dict):output[key]=patch(output.get(key,{}),before[key],value)
                else:output[key]=value
            return output
        data=patch(original,current.model_dump(mode='json'),result.model_dump(mode='json'))
        payload=yaml.safe_dump(data,sort_keys=False,allow_unicode=True)
        after=hashlib.sha256(payload.encode()).hexdigest() if different else revision
        if before_commit is not None:before_commit(result,after)
        if different:_write_unlocked(path,payload,expected_revision=revision)
        elif file_revision(path)!=revision:raise ValueError('Configuration changed before commit; current file retained')
        return result,different,after

