"""Ops health honesty helpers.

Adapter HTTP ``/health`` being green does **not** mean the Jaeger bridge
or MCP/A2A edge is up. Use :func:`check_plane_health` for dependency-aware
status instead of process-up alone.
"""

from .honesty import PlaneHealth, check_plane_health

__all__ = ["PlaneHealth", "check_plane_health"]
