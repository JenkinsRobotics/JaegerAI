"""Deterministic handoff request correlation, shared by current and retained reads."""
import hashlib


def request_digest(request_id: str) -> str:
    """Full digest used by retained native receipt records; never an execution call."""
    return hashlib.sha256(('handoff:'+request_id).encode()).hexdigest()


def child_request_id(request_id: str) -> str:
    """Current Gateway child admission ID; immutable across reconnect/restart."""
    return request_digest(request_id)[:32]
