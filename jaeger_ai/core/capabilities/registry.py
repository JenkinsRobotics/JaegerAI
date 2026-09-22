"""Dynamic Capability Registry (Workstream 10).

Manages discovery, installation, sandboxed execution, verification,
and uninstallation of programmable capabilities without requiring core
modifications to EntityRuntime.
"""
from __future__ import annotations

import importlib.util
import logging
from pathlib import Path
import shutil
import sys
from typing import Any, Callable

from .manifest import CapabilityManifest

logger = logging.getLogger("jaeger.core.capabilities.registry")


class CapabilityError(RuntimeError):
    pass


class CapabilityRegistry:
    """Registry and runner for dynamic programmable capabilities."""

    def __init__(self, root_dir: Path | str) -> None:
        self.root_dir = Path(root_dir)
        self.root_dir.mkdir(parents=True, exist_ok=True)
        self._cache: dict[str, tuple[CapabilityManifest, Path]] = {}
        self.reload()

    def reload(self) -> None:
        """Scan root directory for installed capabilities."""
        self._cache.clear()
        if not self.root_dir.is_dir():
            return
        for child in self.root_dir.iterdir():
            if child.is_dir():
                manifest_path = child / "manifest.yaml"
                if not manifest_path.is_file():
                    manifest_path = child / "manifest.json"
                if manifest_path.is_file():
                    try:
                        manifest = CapabilityManifest.load(manifest_path)
                        self._cache[manifest.capability_id] = (manifest, child)
                    except Exception as exc:
                        logger.warning("Failed loading capability manifest from %s: %s", child, exc)

    def list_all(self) -> list[CapabilityManifest]:
        return [m for m, _ in self._cache.values()]

    def get(self, capability_id: str) -> CapabilityManifest | None:
        item = self._cache.get(capability_id)
        return item[0] if item else None

    def get_package_dir(self, capability_id: str) -> Path | None:
        item = self._cache.get(capability_id)
        return item[1] if item else None

    def install(self, package_dir: Path | str) -> CapabilityManifest:
        """Install a capability package into the registry."""
        src = Path(package_dir).resolve()
        if not src.is_dir():
            raise CapabilityError(f"Package directory not found: {src}")

        manifest_path = src / "manifest.yaml"
        if not manifest_path.is_file():
            manifest_path = src / "manifest.json"
        if not manifest_path.is_file():
            raise CapabilityError(f"No manifest found in package: {src}")

        manifest = CapabilityManifest.load(manifest_path)
        dest = self.root_dir / manifest.capability_id

        if dest.exists():
            shutil.rmtree(dest)

        shutil.copytree(src, dest)
        self._cache[manifest.capability_id] = (manifest, dest)
        logger.info("Installed capability %s (%s) to %s", manifest.capability_id, manifest.version, dest)
        return manifest

    def uninstall(self, capability_id: str) -> bool:
        """Remove an installed capability."""
        item = self._cache.pop(capability_id, None)
        if item is None:
            dest = self.root_dir / capability_id
            if dest.is_dir():
                shutil.rmtree(dest)
                return True
            return False

        _, path = item
        if path.is_dir():
            shutil.rmtree(path)
        logger.info("Uninstalled capability %s", capability_id)
        return True

    def _load_entrypoint(self, capability_id: str, entrypoint: str) -> Callable[..., Any]:
        pkg_dir = self.get_package_dir(capability_id)
        if pkg_dir is None:
            raise CapabilityError(f"Capability {capability_id} is not installed")

        if ":" not in entrypoint:
            raise CapabilityError(f"Invalid entrypoint format (expected file.py:func): {entrypoint}")

        filename, func_name = entrypoint.split(":", 1)
        file_path = pkg_dir / filename
        if not file_path.is_file():
            raise CapabilityError(f"Entrypoint file {file_path} not found in {capability_id}")

        mod_name = f"capability_pkg_{capability_id}_{filename.replace('.', '_')}"
        spec = importlib.util.spec_from_file_location(mod_name, file_path)
        if spec is None or spec.loader is None:
            raise CapabilityError(f"Could not load module spec for {file_path}")

        module = importlib.util.module_from_spec(spec)
        sys.modules[mod_name] = module
        try:
            spec.loader.exec_module(module)
        except Exception as exc:
            raise CapabilityError(f"Failed loading entrypoint module {file_path}: {exc}") from exc

        func = getattr(module, func_name, None)
        if not callable(func):
            raise CapabilityError(f"Entrypoint function {func_name} in {file_path} is not callable")

        return func

    def execute(self, capability_id: str, arguments: dict[str, Any], context: dict[str, Any] | None = None) -> Any:
        """Execute the capability's execution entrypoint."""
        manifest = self.get(capability_id)
        if manifest is None:
            raise CapabilityError(f"Capability {capability_id} is not installed")

        if not manifest.is_executable:
            raise CapabilityError(f"Capability {capability_id} is a procedural skill and cannot be directly executed")

        func = self._load_entrypoint(capability_id, manifest.execution_entrypoint)
        return func(arguments, context=context or {})

    def verify(self, capability_id: str, execution_result: Any, context: dict[str, Any] | None = None) -> tuple[bool, str]:
        """Run independent verification for the capability's outcome."""
        manifest = self.get(capability_id)
        if manifest is None:
            raise CapabilityError(f"Capability {capability_id} is not installed")

        if not manifest.verification_entrypoint:
            return True, "No custom verification entrypoint defined; default ok"

        func = self._load_entrypoint(capability_id, manifest.verification_entrypoint)
        try:
            res = func(execution_result, context=context or {})
            if isinstance(res, tuple) and len(res) == 2:
                return bool(res[0]), str(res[1])
            return bool(res), "Verification succeeded" if res else "Verification returned false"
        except Exception as exc:
            return False, f"Verification failed with exception: {exc}"

    def rollback(self, capability_id: str, execution_result: Any, context: dict[str, Any] | None = None) -> bool:
        """Revert side effects using capability's rollback entrypoint."""
        manifest = self.get(capability_id)
        if manifest is None or not manifest.rollback_entrypoint:
            return False

        func = self._load_entrypoint(capability_id, manifest.rollback_entrypoint)
        try:
            return bool(func(execution_result, context=context or {}))
        except Exception as exc:
            logger.error("Rollback failed for capability %s: %s", capability_id, exc)
            return False
