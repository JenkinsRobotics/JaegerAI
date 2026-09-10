"""Installed-CLI service: list, catalog rows for the model picker."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .discovery import (
    KNOWN_BACKENDS,
    BackendSpec,
    probe_backend,
    resolve_backend,
)


@dataclass(frozen=True, slots=True)
class InstalledBackend:
    spec: BackendSpec
    executable: str | None
    installed: bool

    @property
    def id(self) -> str:
        return self.spec.id


def list_all() -> list[InstalledBackend]:
    """Every known backend, installed or missing."""
    out: list[InstalledBackend] = []
    for spec in KNOWN_BACKENDS:
        path = probe_backend(spec)
        out.append(InstalledBackend(spec=spec, executable=path, installed=path is not None))
    return out


def list_installed() -> list[InstalledBackend]:
    """Known backends whose binary is on PATH (or an extra dir)."""
    return [row for row in list_all() if row.installed]


def to_model_rows(*, installed_only: bool = True) -> list[dict[str, Any]]:
    """Selectable catalog rows for ``list_registered_models``.

    ``ollama`` is probed for ``jaeger backends`` but not catalogued as a
    brain — it already has an HTTP provider.
    """
    rows: list[dict[str, Any]] = []
    for item in list_all():
        if not item.spec.catalog:
            continue
        if installed_only and not item.installed:
            continue
        rows.append({
            "name": f"cli:{item.spec.id}",
            "model": item.spec.id,
            "source": item.spec.provider_slug,
            "serving": False,
            "kind": "external",
            "provider": item.spec.provider_slug,
            "route_provider": "cli",
            "location": "local-cli",
            "status": (
                "installed on PATH" if item.installed
                else "not installed — binary not on PATH"
            ),
            "description": item.spec.display_name or item.spec.id,
            "executable": item.executable,
            "context_length": None,
        })
    return rows


def installed_ids() -> list[str]:
    return [row.id for row in list_installed() if row.spec.catalog]


def normalize_cli_selection(provider: str, model: str) -> tuple[str, str] | None:
    """Map picker / catalog names onto ``(cli, backend_id)``.

    Accepts ``cli`` + ``claude``, ``claude-cli`` + anything, or a model
    named ``cli:claude``. Returns ``None`` when this is not a CLI pick.
    """
    prov = (provider or "").strip().lower()
    name = (model or "").strip()
    bare = name.lower()
    if bare.startswith("cli:"):
        bare = bare.split(":", 1)[1]
        prov = "cli"
    if prov.endswith("-cli"):
        bare = prov[: -len("-cli")] or bare
        prov = "cli"
    if prov != "cli":
        return None
    spec = resolve_backend(bare or name)
    if spec is None or not spec.catalog:
        return None
    return ("cli", spec.id)
