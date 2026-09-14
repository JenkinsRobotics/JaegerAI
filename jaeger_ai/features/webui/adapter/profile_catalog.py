"""Execution-owned profile identities and bounded native readiness checks."""
from concurrent.futures import ThreadPoolExecutor
import threading
import time
from urllib.request import Request, urlopen


PROFILES = (
    ('default', 'hermes', 'Hermes Agent'),
    ('jaeger', 'jaeger', 'Jaeger AI'),
    ('openclaw', 'openclaw', 'OpenClaw'),
    ('roundtable', 'roundtable', 'Roundtable'),
)


def native_ready(name, bridge):
    if name == 'jaeger':
        return bool(bridge.health().get('ok'))
    if name == 'hermes':
        from jaeger_ai.interfaces.hermes_profile_adapters.hermes_native import connection
        base, key = connection()
        with urlopen(Request(base + '/health', headers={'Authorization': 'Bearer ' + key}), timeout=3) as response:
            return response.status == 200
    from jaeger_ai.interfaces.hermes_profile_adapters.openclaw_native import NativeGateway
    from jaeger_ai.interfaces.hermes_profile_adapters.openclaw import OPENCLAW_BASE_URL, OPENCLAW_TOKEN_FILE
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
                members = ('hermes', 'jaeger', 'openclaw')
                with ThreadPoolExecutor(max_workers=3) as pool:
                    states = dict(zip(members, pool.map(self._ready, members)))
                missing = [label for _, owner, label in PROFILES if owner in states and not states[owner]]
                states['roundtable'] = not missing
                self.cached = [dict(name=name, runtime=owner, display_name=label,
                    gateway_running=states[owner],
                    runtime_status=('Ready' if states[owner] else
                        'Unavailable: ' + ', '.join(missing) if owner == 'roundtable' else 'Unavailable'),
                    skill_count=None, enabled_skills=None, total_skills=None,
                    visible=True, is_default=name == 'default') for name, owner, label in PROFILES]
                self.expires = time.monotonic() + self.ttl
            return [dict(row) for row in self.cached]
