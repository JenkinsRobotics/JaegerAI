"""The avatar's voice and hearing: voice_worker.py (Jaeger Agent's SpeechRuntime) in its own process.

JAEGER_VOICE_PYTHON names the Python that has Jaeger Agent 1.2.0 with jaeger-kokoro-tts 0.14.0 and jaeger-whisper-stt.
Unset or unable to load: the avatar stays silent and says why; chat still works.
"""
from __future__ import annotations

import itertools
import json
import os
import subprocess
import sys
import threading
from pathlib import Path

WORKER = Path(__file__).with_name('voice_worker.py')


class Voice:
    def __init__(self, python: str | None = None, log: Path | None = None):
        self.python = python or os.environ.get('JAEGER_VOICE_PYTHON') or ''
        self.log = log
        self.ready, self.why, self.report = False, 'starting', {}
        self._ids, self._lock, self._waiting = itertools.count(1), threading.Lock(), {}
        self.proc = None

    def start(self):
        if not self.python:
            self.why = 'no voice: set JAEGER_VOICE_PYTHON to a Python with Jaeger Agent 1.2.0 and its voice modules'
            return self
        threading.Thread(target=self._run, daemon=True).start()
        return self

    def _run(self):
        try:
            err = open(self.log, 'a') if self.log else subprocess.DEVNULL
            self.proc = subprocess.Popen([self.python, '-B', str(WORKER)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                         stderr=err, text=True, cwd=str(WORKER.parent), env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'})
        except OSError as exc:
            self.why = f'voice worker did not start: {exc}'
            return
        first = json.loads(self.proc.stdout.readline() or '{"ready": false, "why": "the voice worker exited"}')
        self.ready, self.why, self.report = bool(first.get('ready')), first.get('why', ''), first.get('report') or {}
        for line in self.proc.stdout:
            try:
                r = json.loads(line)
            except ValueError:
                continue
            slot = self._waiting.pop(r.get('id'), None)
            if slot:
                slot[1].update(r); slot[0].set()
        self.ready, self.why = False, 'the voice worker stopped'
        for ev, _ in list(self._waiting.values()):
            ev.set()

    def _ask(self, msg: dict, timeout: float = 120) -> dict:
        if not self.ready:
            raise RuntimeError(self.why)
        rid, ev, out = next(self._ids), threading.Event(), {}
        self._waiting[rid] = (ev, out)
        with self._lock:
            self.proc.stdin.write(json.dumps({**msg, 'id': rid}) + '\n'); self.proc.stdin.flush()
        if not ev.wait(timeout) or 'error' in out or not out:
            self._waiting.pop(rid, None)
            raise RuntimeError(out.get('error') or 'the voice did not answer')
        return out

    def say(self, text: str) -> dict:
        """{rate, pcm (b64 int16), marks, ms} for one reply."""
        return self._ask({'op': 'say', 'text': text})

    def hear(self, pcm_b64: str) -> str:
        return str(self._ask({'op': 'hear', 'pcm': pcm_b64}).get('text') or '')

    def close(self):
        if self.proc and self.proc.poll() is None:
            self.proc.stdin.close()
            try: self.proc.wait(5)
            except subprocess.TimeoutExpired: self.proc.kill()


if __name__ == '__main__':   # self-check without a worker: says why it is silent
    v = Voice(python='').start()
    assert not v.ready and 'JAEGER_VOICE_PYTHON' in v.why
    try: v.say('hi'); raise SystemExit('should refuse')
    except RuntimeError: pass
    print('voice self-check ok', file=sys.stderr)
