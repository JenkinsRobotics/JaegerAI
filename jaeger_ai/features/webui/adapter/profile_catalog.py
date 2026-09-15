"""Bounded native readiness checks for each framework.

The identities themselves are NOT defined here — they come from
:mod:`jaeger_ai.contract.frameworks`, which is the one table. This module only
answers "is it up right now".
"""
from concurrent.futures import ThreadPoolExecutor
import threading
import time
from urllib.request import Request, urlopen

from jaeger_ai.contract.frameworks import DEBATE_MEMBERS, FRAMEWORKS, SOLO_RUNTIMES

#: (profile, runtime, display_name) per framework, in contract order.
#: Kept as a tuple-of-tuples for the call sites that unpack it positionally.
PROFILES = tuple((f.profile, f.runtime, f.display_name) for f in FRAMEWORKS)


def native_ready(name, bridge):
    if name == 'jaeger':
        return bool(bridge.health().get('ok'))
    if name == 'hermes':
        from jaeger_ai.core.frameworks.hermes_native import connection
        base, key = connection()
        with urlopen(Request(base + '/health', headers={'Authorization': 'Bearer ' + key}), timeout=3) as response:
            return response.status == 200
    from jaeger_ai.core.frameworks.openclaw_native import NativeGateway
    from jaeger_ai.core.frameworks.openclaw import OPENCLAW_BASE_URL, OPENCLAW_TOKEN_FILE
    with NativeGateway(OPENCLAW_BASE_URL, OPENCLAW_TOKEN_FILE):
        return True


class ProfileCatalog:
    def __init__(self, probe, ttl=5):
        self.probe = probe
        self.ttl = ttl
        self.lock = threading.Lock()
        self.cached = None
        self.expires = 0

    def _ready(self, name):
        try:
            return bool(self.probe(name))
        except Exception:
            return False

    def list(self):
        with self.lock:
            if self.cached is None or time.monotonic() >= self.expires:
                # Probe only the frameworks that answer for themselves; a debate
                # is ready exactly when everyone it composes is.
                with ThreadPoolExecutor(max_workers=len(SOLO_RUNTIMES)) as pool:
                    states = dict(zip(SOLO_RUNTIMES, pool.map(self._ready, SOLO_RUNTIMES)))
                missing = [f.display_name for f in FRAMEWORKS
                           if f.runtime in DEBATE_MEMBERS and not states[f.runtime]]
                for f in FRAMEWORKS:
                    if f.composes:
                        states[f.runtime] = not missing
                # agent_id ships to the browser so the Agents roster can join a
                # row to its profile directly. It used to rebuild the id by
                # splitting on ":" — a rule re-implemented in JavaScript, which
                # is the same duplication this contract exists to end.
                self.cached = [dict(name=f.profile, runtime=f.runtime,
                    display_name=f.display_name, agent_id=f.agent_id,
                    gateway_running=states[f.runtime],
                    runtime_status=('Ready' if states[f.runtime] else
                        'Unavailable: ' + ', '.join(missing) if f.composes else 'Unavailable'),
                    skill_count=None, enabled_skills=None, total_skills=None,
                    visible=True, is_default=f.profile == 'default') for f in FRAMEWORKS]
                self.expires = time.monotonic() + self.ttl
            return [dict(row) for row in self.cached]
