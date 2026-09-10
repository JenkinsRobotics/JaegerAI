"""Pin controls to the gateway that accepted the run, not the currently open tab."""
import threading

_lock = threading.Lock()
_routes = {}


def remember(run_id, base_url, api_key):
    with _lock:
        _routes[run_id] = (base_url, api_key)


def lookup(run_id):
    with _lock:
        return _routes.get(run_id)
