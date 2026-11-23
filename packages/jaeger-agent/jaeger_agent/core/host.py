"""Explicit lazy services supplied by a host application.

The reusable agent owns its loop, memory and tools. Product-only integrations
(authority, runtime events, configured backends and optional host features) are
factories injected by the application, never imports back into it. Missing
services raise ImportError at the feature boundary; the executor preserves its
existing fail-closed behavior when a product authority service is unavailable.
"""

from __future__ import annotations

from typing import Any

_services: dict[str, Any] = {}


def bind_services(services: dict[str, Any]) -> None:
    """Install lazy product-owned service factories; never import the host here."""
    _services.update(services)


def service(name: str, *, required: bool = True) -> Any:
    """Resolve an explicitly injected host service, or fail at the feature edge."""
    factory = _services.get(name)
    if factory is None:
        if not required:
            return None
        raise ImportError(f"Host service {name!r} is not bound")
    return factory()


def host_required(module: str, symbol: str = "") -> Any:
    """A stand-in that raises only if something actually calls it.

    Returned in place of a symbol a host application was supposed to
    provide. Importing stays free; using it names the missing module
    rather than raising an AttributeError on ``None`` three frames away.

    Nothing uses this today — see the module docstring. If you reach for
    it, first ask which direction the thing should move.
    """

    name = f"{module}.{symbol}" if symbol else module

    def _unavailable(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError(
            f"{name} is provided by a host application and is not "
            f"installed. Either install the host or inject an equivalent."
        )

    return _unavailable


def check_file_access(path: Any, *, write: bool = False) -> None:
    """Apply product-owned resource restrictions without importing the product."""
    authority = service("filesystem_authority", required=False)
    if authority is not None:
        authority.check_path(path, write=write)


def confine_process(command: Any, *, workspace: Any = None) -> list[str]:
    """Let the host install mandatory OS restrictions before a tool spawns."""
    authority = service("filesystem_authority", required=False)
    if authority is None:
        return list(command)
    if workspace is not None:
        try:
            return authority.confine_command(command, workspace=workspace)
        except TypeError:
            pass
    return authority.confine_command(command)


def file_access_guard() -> Any:
    """Snapshot host restrictions once for a bounded directory traversal."""
    authority = service("filesystem_authority", required=False)
    return (lambda path: None) if authority is None else authority.path_guard()


__all__ = ["bind_services", "service", "host_required", "check_file_access", "confine_process", "file_access_guard"]
