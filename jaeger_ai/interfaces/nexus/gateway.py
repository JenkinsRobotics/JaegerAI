"""The Gateway (127.0.0.1:33418) as the screen's agent.

Bridge has the same shape as Omni's host.Worker (listen / unlisten / send / ready / report / why), so the screen
copied from Omni keeps working. It follows the main chat's SSE stream and turns the Gateway's events into the
screen's chat events: run.started -> user, text.delta -> delta, tool.* -> tool, run.completed -> assistant + done.
"""
from __future__ import annotations

import json
import os
import queue
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT = 'http://127.0.0.1:33418'


def gateway_url() -> str:
    """The same lookup order as the Swift app's (JAEGER_SHELL_GATEWAY_URL, then JAEGER_GATEWAY_URL)."""
    return (os.environ.get('JAEGER_SHELL_GATEWAY_URL') or os.environ.get('JAEGER_GATEWAY_URL') or DEFAULT).rstrip('/')


def caller_token() -> str:
    """Swift's ShellEnvironment.callerToken(): env JAEGER_CALLER_TOKEN, else <state>/caller_tokens/menubar.token."""
    tok = (os.environ.get('JAEGER_CALLER_TOKEN') or '').strip()
    if tok:
        return tok
    state = Path(os.environ.get('JAEGER_STATE_DIR') or Path.home() / '.jaeger').expanduser()
    try:
        return (state / 'caller_tokens' / 'menubar.token').read_text().strip()
    except OSError:
        return ''


class Gateway:
    def __init__(self, url: str | None = None):
        self.url = (url or gateway_url()).rstrip('/')

    def _req(self, method: str, path: str, body: object = None) -> urllib.request.Request:
        r = urllib.request.Request(self.url + path, method=method,
                                   data=None if body is None else json.dumps(body).encode())
        r.add_header('Content-Type', 'application/json')
        tok = caller_token()
        if tok:
            r.add_header('Authorization', f'Bearer {tok}')
        return r

    def call(self, method: str, path: str, body: object = None, timeout: float = 5.0):
        """(status, json) — status 0 when the Gateway cannot be reached."""
        try:
            with urllib.request.urlopen(self._req(method, path, body), timeout=timeout) as r:  # noqa: S310 (loopback)
                return r.status, json.loads(r.read() or b'{}')
        except urllib.error.HTTPError as e:
            try:
                return e.code, json.loads(e.read() or b'{}')
            except ValueError:
                return e.code, {}
        except (OSError, ValueError):
            return 0, {}

    def events(self, sid: str, after: int, timeout: float = 30.0):
        """Yield (seq, event, payload) from the session's SSE stream; returns when the stream ends."""
        with urllib.request.urlopen(self._req('GET', f'/v1/sessions/{sid}/events?after_seq={after}'), timeout=timeout) as r:  # noqa: S310
            seq, ev, data = None, 'message', []
            for raw in r:
                line = raw.decode('utf-8', 'replace').rstrip('\r\n')
                if not line:
                    if data:
                        try:
                            yield seq, ev, json.loads('\n'.join(data))
                        except ValueError:
                            pass
                    seq, ev, data = None, 'message', []
                elif line.startswith(':'):
                    continue
                elif line.startswith('id:'):
                    seq = int(line[3:].strip() or 0)
                elif line.startswith('event:'):
                    ev = line[6:].strip()
                elif line.startswith('data:'):
                    data.append(line[5:].lstrip())


def translate(ev: str, p: dict) -> list[dict]:
    """One Gateway SSE event -> the screen's chat events (web/src/chat.ts)."""
    if ev == 'run.started':
        return [{'event': 'user', 'text': p.get('prompt', '')}, {'event': 'state', 'text': 'Thinking'}]
    if ev == 'text.delta':
        return [{'event': 'delta', 'text': p.get('delta', '')}]
    if ev == 'thinking.delta':
        return [{'event': 'state', 'text': 'Thinking'}]
    if ev == 'tool.started':
        return [{'event': 'tool', 'text': p.get('tool', 'tool'), 'data': p.get('arguments')},
                {'event': 'state', 'text': f"Using {p.get('tool', 'a tool')}"}]
    if ev == 'tool.failed':
        return [{'event': 'tool', 'text': f"{p.get('tool', 'tool')} failed", 'data': p.get('error')}]
    if ev == 'run.completed':
        text = p.get('content') or p.get('final_text') or ''
        return ([{'event': 'assistant', 'text': text}] if text else []) + [{'event': 'done'}]
    if ev == 'run.failed':
        return [{'event': 'status', 'text': f"error: {p.get('error') or 'the run failed'}"}, {'event': 'done'}]
    return []


class Bridge:
    """Follows one Gateway session; the screen's POSTs become runs on it."""

    def __init__(self, gw: Gateway):
        self.gw, self.subs, self.lock = gw, set(), threading.Lock()
        self.session, self.seq, self.ready, self.why = None, 0, False, ''
        self.history: list[dict] = []
        self.report = {'agent': {'model': None}}
        self.voice = None   # voice.Voice: each finished reply is spoken (the avatar's mouth follows the sound)
        self._stop = threading.Event()

    def start(self):
        threading.Thread(target=self._follow, daemon=True).start()
        return self

    def close(self):
        self._stop.set()
        self._emit(None)

    def listen(self):
        q = queue.Queue()
        with self.lock:
            self.subs.add(q)
        if self.session:   # a screen that opens now starts from the session's history as it is now
            for e in self._history(self.session)[0]:
                q.put(e)
        return q

    def unlisten(self, q):
        with self.lock:
            self.subs.discard(q)

    def _emit(self, e):
        with self.lock:
            for q in list(self.subs):
                q.put(e)

    def _history(self, sid: str) -> tuple[list[dict], int]:
        """The session's latest messages as chat events, and the event cursor they reach."""
        st, j = self.gw.call('GET', f'/v1/sessions/{sid}/messages?page=latest')
        hist = []
        for m in j.get('messages', []) if st == 200 else []:
            role, text = m.get('role'), m.get('content') or m.get('text') or ''
            if role == 'user' and text:
                hist.append({'event': 'user', 'text': text})
            elif role == 'assistant' and text:
                hist += [{'event': 'assistant', 'text': text}, {'event': 'done'}]
        return hist, int(j.get('after_seq') or 0)

    def _open(self, sid: str | None):
        """Point at a session (None: the main chat)."""
        if sid is None:
            st, j = self.gw.call('GET', '/v1/chat/session')
            sid = (j.get('session') or {}).get('session_id') if st == 200 else None
        if not sid:
            raise OSError('no chat session')
        self.session, (self.history, self.seq) = sid, self._history(sid)

    def new_session(self):
        st, j = self.gw.call('POST', '/v1/sessions', {'title': 'NexusUI chat'})
        if st not in (200, 201):
            raise RuntimeError('the Gateway did not open a new chat')
        self._open((j.get('session') or {}).get('session_id'))
        self._emit({'event': 'reset'})

    def _follow(self):
        while not self._stop.is_set():
            try:
                if self.session is None:
                    self._open(None)
                    self._emit({'event': 'reset'})
                    for e in self.history:
                        self._emit(e)
                st, h = self.gw.call('GET', '/health')
                self.report = {'agent': {'model': h.get('model') or h.get('active_model')}}
                self.ready, self.why = True, ''
                sid = self.session
                for seq, ev, p in self.gw.events(sid, self.seq):
                    if self._stop.is_set() or sid != self.session:
                        break
                    self.seq = max(self.seq, seq or 0)
                    for e in translate(ev, p if isinstance(p, dict) else {}):
                        self._emit(e)
                        if e['event'] == 'assistant' and self.voice is not None:
                            threading.Thread(target=self._speak, args=(e['text'],), daemon=True).start()
            except (OSError, ValueError) as exc:
                self.ready, self.why = False, f'Gateway not reachable at {self.gw.url} ({type(exc).__name__})'
                self.session = None   # reopen (and reload history) once it is back
                self._stop.wait(2.0)

    def _speak(self, text: str):
        """The whole reply in her voice, once the Gateway's model is done (one GPU job at a time on this Mac).
        ponytail: the whole reply, not sentence by sentence; stream sentences when first-sound time matters."""
        try:
            self._emit({'event': 'state', 'text': 'speaking'})
            v = self.voice.say(text)
            self._emit({'event': 'voice', 'text': text, 'pcm': v['pcm'], 'rate': v['rate'], 'marks': v.get('marks', []), 'ms': v.get('ms')})
        except RuntimeError as exc:
            self._emit({'event': 'status', 'text': f'voice: {exc}'})

    def send(self, msg: dict):
        if not self.ready or not self.session:
            raise RuntimeError(self.why or 'the Gateway is not ready yet')
        op = msg.get('op')
        if op == 'text':
            # interrupt: a new message replaces a running one, as the WebUI does when you send while it works
            st, j = self.gw.call('POST', f'/v1/sessions/{self.session}/runs',
                                 {'prompt': msg['text'], 'multitask_strategy': 'interrupt'})
            if st not in (200, 202):
                raise RuntimeError(j.get('error') or f'Gateway refused the message ({st})')
        elif op == 'interrupt':
            # ponytail: the Gateway has no cancel route; Stop ends the wait on this screen only
            self._emit({'event': 'done'})
        elif op == 'new':
            self.new_session()
        else:
            raise ValueError(f'unknown op {op!r}')
