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
            with (root/'events.jsonl').open('a') as events:
                while selector.get_map() or process.poll() is None:
                    if not stopping and ((root/'cancel').exists() or time.monotonic() >= deadline):
                        stopping = 'cancelled' if (root/'cancel').exists() else 'timeout'
                        kill_at = time.monotonic() + 2
                        try:
                            os.killpg(process.pid, signal.SIGTERM)
                        except ProcessLookupError:
                            pass
                    if kill_at and time.monotonic() >= kill_at:
                        try:
                            os.killpg(process.pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
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
            write_json(root/'result.json', {'status':'cancelled' if stopping == 'cancelled' else 'failed' if stopping or code else 'completed',
                'stdout':''.join(output['stdout']), 'stderr':''.join(output['stderr']),
                'exit_code':code, 'timed_out':stopping == 'timeout', 'timeout':request['timeout'],
                'output_truncated':size >= LIMIT})
        except Exception as exc:
            if process is not None and process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait()
            write_json(root/'result.json', {'status':'failed', 'stderr':str(exc), 'stdout':'',
                'exit_code':process.returncode if process else None})


if __name__ == '__main__':
    main(Path(sys.argv[1]))
