"""One admitted CLI invocation. Persists output/exit receipt independently of its client.

This process owns no task queue, model selection or retry policy. The Gateway
admits work; this wrapper only observes one child and records its actual outcome.
"""
from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path
import selectors
import signal
import subprocess
import sys
import threading
import time

LIMIT = 2 * 1024 * 1024


def write_json(path, value):
    temp = path.with_suffix('.tmp')
    with temp.open('w') as stream:
        json.dump(value, stream)
        stream.flush()
        os.fsync(stream.fileno())
    temp.replace(path)


def _children_by_parent():
    children = {}
    proc = Path('/proc')
    if proc.is_dir():
        for entry in proc.iterdir():
            if not entry.name.isdigit():
                continue
            try:
                stat = (entry / 'stat').read_bytes()
            except OSError:
                continue
            end = stat.rfind(b')')
            if end < 0:
                continue
            fields = stat[end + 2:].split()
            if len(fields) < 2:
                continue
            try:
                children.setdefault(int(fields[1]), []).append(int(entry.name))
            except ValueError:
                continue
        return children
    try:
        completed = subprocess.run(['ps', '-ax', '-o', 'pid=,ppid='], capture_output=True, text=True, timeout=2, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return children
    for line in completed.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
            children.setdefault(int(parts[1]), []).append(int(parts[0]))
    return children


def _alive(pid):
    if not isinstance(pid, int) or pid <= 1 or pid == os.getpid():
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _descendants(pid):
    children = _children_by_parent()
    found = set()
    stack = list(children.get(pid, ()))
    while stack:
        current = stack.pop()
        if current in found or current <= 1 or current == os.getpid():
            continue
        found.add(current)
        stack.extend(children.get(current, ()))
    return found


def _snapshot_owned(pid):
    owned = set()
    if _alive(pid):
        owned.add(pid)
        owned |= _descendants(pid)
    return owned


def _survivors(pids):
    return sorted(pid for pid in pids if _alive(pid))


def _signal_owned(pids, sig):
    for pid in pids:
        try:
            os.kill(pid, sig)
        except OSError:
            pass


def main(root):
    os.umask(0o077)
    with (root/'worker.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        request = json.load(sys.stdin)
        if (root/'result.json').exists():
            return
        process = None
        try:
            process = subprocess.Popen(request['argv'], cwd=request.get('cwd'),
                stdin=subprocess.PIPE if request.get('prompt') is not None else subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
            write_json(root/'running.json', {'pid':process.pid, 'worker_pid':os.getpid(), 'started_at':time.time()})
            if process.stdin:
                def send_prompt():
                    try:
                        process.stdin.write(request['prompt'].encode())
                        process.stdin.close()
                    except (BrokenPipeError, OSError):
                        pass
                threading.Thread(target=send_prompt, daemon=True).start()
            selector = selectors.DefaultSelector()
            for source, stream in [('stdout',process.stdout), ('stderr',process.stderr)]:
                os.set_blocking(stream.fileno(), False)
                selector.register(stream, selectors.EVENT_READ, source)
            output = {'stdout':[], 'stderr':[]}
            pending = {'stdout':b'', 'stderr':b''}
            size = sequence = 0
            deadline = time.monotonic() + request['timeout']
            stopping = None
            kill_at = None
            owned = set()
            with (root/'events.jsonl').open('a') as events:
                while selector.get_map() or process.poll() is None:
                    if not stopping and ((root/'cancel').exists() or time.monotonic() >= deadline):
                        stopping = 'cancelled' if (root/'cancel').exists() else 'timeout'
                        kill_at = time.monotonic() + 2
                        owned = _snapshot_owned(process.pid)
                        try:
                            os.killpg(process.pid, signal.SIGTERM)
                        except OSError:  # gone, or macOS EPERM on a group whose leader already exited
                            pass
                        _signal_owned(owned, signal.SIGTERM)
                    if kill_at and time.monotonic() >= kill_at:
                        still = _survivors(owned | _descendants(process.pid) | {process.pid})
                        owned |= set(still)
                        try:
                            os.killpg(process.pid, signal.SIGKILL)
                        except OSError:  # gone, or macOS EPERM on a group whose leader already exited
                            pass
                        _signal_owned(still, signal.SIGKILL)
                        kill_at = None
                    for key, _ in selector.select(timeout=0.1):
                        chunk = os.read(key.fileobj.fileno(), 65536)
                        source = key.data
                        if not chunk:
                            selector.unregister(key.fileobj)
                            key.fileobj.close()
                            if pending[source]:
                                pending[source] += b'\n'
                            else:
                                continue
                        remaining = max(0, LIMIT-size)
                        if remaining:
                            output[source].append(chunk[:remaining].decode('utf-8', errors='replace'))
                            size += min(len(chunk),remaining)
                            pending[source] += chunk[:remaining]
                        while b'\n' in pending[source]:
                            line, pending[source] = pending[source].split(b'\n',1)
                            sequence += 1
                            events.write(json.dumps({'sequence':sequence,'event_type':'output',
                                'payload':{'source':source,'text':line.decode('utf-8',errors='replace').rstrip('\r')}})+'\n')
                            events.flush()
                selector.close()
            code = process.wait()
            alive = _survivors(owned | _descendants(process.pid))
            if alive:
                _signal_owned(alive, signal.SIGKILL)
                time.sleep(0.2)
                alive = _survivors(owned | set(alive) | _descendants(process.pid))
            confirmed = not alive
            if stopping == 'cancelled' and confirmed:
                status = 'cancelled'
            elif stopping or code or not confirmed:
                status = 'failed' if confirmed else 'unknown'
            else:
                status = 'completed'
            write_json(root/'result.json', {'status': status,
                'stdout':''.join(output['stdout']), 'stderr':''.join(output['stderr']),
                'exit_code':code, 'timed_out':stopping == 'timeout', 'timeout':request['timeout'],
                'output_truncated':size >= LIMIT,
                'cancellation_unconfirmed': bool(alive),
                'surviving_pids': alive})
        except Exception as exc:
            owned = _snapshot_owned(process.pid) if process is not None else set()
            if process is not None and process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except OSError:
                    pass
                _signal_owned(owned, signal.SIGKILL)
                process.wait()
            alive = _survivors(owned)
            write_json(root/'result.json', {'status':'unknown' if alive else 'failed', 'stderr':str(exc), 'stdout':'',
                'exit_code':process.returncode if process else None,
                'cancellation_unconfirmed': bool(alive), 'surviving_pids': alive})


if __name__ == '__main__':
    main(Path(sys.argv[1]))
