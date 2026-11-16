"""No web-app-local approval queue any more: every card lives in the Gateway."""
import threading
_lock = threading.Lock()
_pending: dict = {}
