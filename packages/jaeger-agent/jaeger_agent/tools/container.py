"""Container management tool for Apple native containers.

Allows the agent to list, start, stop, inspect, create, and delete container tools
(ares-openclaw, hermes-webui-hermes-webui, ares-n8n, etc.) backed by Apple container.
"""

from __future__ import annotations

from typing import Any

from jaeger_ai.core.runtime import container_service as cs
from jaeger_os.core.safety.permissions import PermissionTier, requires_tier
from jaeger_os.core.tools.tool_registry import register_tool_from_function


def container(
    action: str,
    name: str = "",
    image: str = "",
    ports: str = "",
    force: bool = False,
) -> dict[str, Any]:
    """Manage Apple native container tools and services.

    ``action`` selects the operation:
      - ``list``    — list installed container tools and their live status
      - ``start``   — start a container tool (needs ``name``, e.g. "ares-openclaw")
      - ``stop``    — stop a running container tool (needs ``name``)
      - ``status``  — inspect container state, IP, ports, and recent logs (needs ``name``)
      - ``delete``  — delete a container tool from disk (needs ``name``)
      - ``create``  — create a new container tool (needs ``name`` + ``image``)
    """
    act = (action or "").strip().lower()
    if act in ("list", "ls", "ps"):
        containers = cs.list_containers(all=True)
        return {
            "ok": True,
            "count": len(containers),
            "system_running": cs.is_system_running(),
            "containers": containers,
        }

    if act == "start":
        if not name:
            return {"ok": False, "error": "name is required to start a container"}
        return cs.start_container(name)

    if act in ("stop", "kill"):
        if not name:
            return {"ok": False, "error": "name is required to stop a container"}
        return cs.stop_container(name)

    if act in ("status", "inspect", "info", "logs"):
        if not name:
            return {"ok": False, "error": "name is required to inspect a container"}
        return cs.container_status(name)

    if act in ("delete", "remove", "rm"):
        if not name:
            return {"ok": False, "error": "name is required to delete a container"}
        return cs.delete_container(name, force=force)

    if act in ("create", "run"):
        if not name or not image:
            return {"ok": False, "error": "name and image are required to create a container"}
        port_list = [p.strip() for p in ports.split(",") if p.strip()] if ports else None
        return cs.create_container(name=name, image=image, ports=port_list)

    return {"ok": False, "error": f"unknown container action {action!r}"}


@register_tool_from_function(name="container")
@requires_tier(PermissionTier.EXTERNAL_EFFECT, skill="container", operation="container",
               summary="manage Apple container tools and services")
def _t_container(
    action: str,
    name: str = "",
    image: str = "",
    ports: str = "",
    force: bool = False,
) -> dict[str, Any]:
    """Manage Apple native container tools and services.
    action in ('list', 'start', 'stop', 'status', 'delete', 'create').
    """
    return container(action=action, name=name, image=image, ports=ports, force=force)
