"""Separate queue/idle/tool/approval budgets; heartbeats never reset progress."""
import math
import time

DEFAULTS = {'queue': 120., 'idle': 120., 'tool': 300., 'approval': 125., 'total': None}


def budgets(values=None):
    if values is not None and (not isinstance(values, dict) or set(values) - set(DEFAULTS)):
        raise ValueError('Unknown Roundtable wait budget')
    result = {**DEFAULTS, **(values or {})}
    for key, value in result.items():
        if key == 'total' and value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 < value <= 86400:
            raise ValueError('Wait budgets must be finite seconds in (0, 86400]')
    return result


class Progress:
    def __init__(self, policy=None, *, clock=time.monotonic):
        self.clock = clock
        self.policy = budgets(policy)
        self.started = self.changed = clock()
        self.state = 'queue'

    def observe(self, event):
        kind = event.get('event')
        state = None
        if kind == 'native.state':
            incoming = event.get('state')
            state = 'queue' if incoming == 'queued' else 'idle' if incoming == 'running' else None
            if state == self.state:
                return
        elif kind == 'approval.request':
            state = 'approval'
        elif kind == 'approval.resolved':
            state = 'idle'
        elif kind == 'tool.started':
            state = 'tool'
        elif kind == 'tool.completed':
            state = 'idle'
        elif kind == 'message.delta' and event.get('delta'):
            state = 'idle'
        elif kind == 'reasoning.available' and event.get('text'):
            state = 'idle'
        if state is not None:
            self.state, self.changed = state, self.clock()

    def expired(self):
        now = self.clock()
        total = self.policy['total']
        if total is not None and now - self.started >= total:
            return 'total_timeout'
        if now - self.changed >= self.policy[self.state]:
            return self.state + '_timeout'
        return None
