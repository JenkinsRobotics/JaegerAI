"""Authenticated Tailscale-oriented remote access feature."""

from .policy import AccessDecision, RemoteAccessPolicy

__all__ = ["AccessDecision", "RemoteAccessPolicy"]
