"""Installed agent CLIs as first-class Jaeger models.

OpenClaw practice: PATH-probe known CLIs, then they appear in the model
catalog and can be selected as the brain. Delegates remain workers
(``delegate_task`` goes do a whole job in that agent). CLI backends are
models: Jaeger keeps the loop, tools, memory, and permissions.
"""

from .discovery import (
    EXTRA_PATH_DIRS,
    KNOWN_BACKENDS,
    BackendSpec,
    which_cli,
    probe_backend,
    resolve_backend,
)
from .service import InstalledBackend, list_all, list_installed, to_model_rows

__all__ = [
    "EXTRA_PATH_DIRS",
    "KNOWN_BACKENDS",
    "BackendSpec",
    "InstalledBackend",
    "list_all",
    "list_installed",
    "probe_backend",
    "resolve_backend",
    "to_model_rows",
    "which_cli",
]
