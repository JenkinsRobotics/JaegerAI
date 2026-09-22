"""Public platform extension verbs (Workstream 23).

  jaeger capability validate [path]
  jaeger provider doctor
  jaeger device inspect [device_id]

These commands use public contracts only. They do not patch EntityRuntime.
Missing credentials are reported as unavailable, not as a crash.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def _cmd_capability_argv(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        print(
            "usage: jaeger capability <verb> [args...]\n"
            "\n"
            "verbs:\n"
            "  validate [path]   validate a capability package manifest\n",
            file=sys.stderr,
        )
        return 0 if argv else 2
    verb = argv[0]
    if verb == "validate":
        return _capability_validate(argv[1:])
    print(f"[jaeger capability] unknown verb {verb!r}", file=sys.stderr)
    return 2


def _capability_validate(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="jaeger capability validate")
    parser.add_argument("path", nargs="?", default=".")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    root = Path(args.path).expanduser().resolve()
    report = validate_capability_package(root)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        status = "VALID" if report["ok"] else "INVALID"
        print(f"{status}  {report['path']}")
        if report.get("capability_id"):
            print(f"  id: {report['capability_id']}")
            print(f"  name: {report.get('name')}")
            print(f"  version: {report.get('version')}")
            print(f"  category: {report.get('category')}")
            print(f"  executable: {report.get('is_executable')}")
        for err in report.get("errors") or []:
            print(f"  error: {err}")
        for warn in report.get("warnings") or []:
            print(f"  warning: {warn}")
    return 0 if report["ok"] else 1


def validate_capability_package(path: Path | str) -> dict[str, Any]:
    """Validate a capability package using public manifest contracts only."""
    from jaeger_ai.core.capabilities.manifest import CapabilityManifest

    root = Path(path)
    errors: list[str] = []
    warnings: list[str] = []
    manifest_path = root if root.is_file() else None
    if manifest_path is None:
        for name in ("manifest.yaml", "manifest.yml", "manifest.json"):
            candidate = root / name
            if candidate.is_file():
                manifest_path = candidate
                break
    if manifest_path is None:
        return {
            "ok": False,
            "path": str(root),
            "errors": ["no manifest.yaml or manifest.json found"],
            "warnings": [],
        }

    try:
        manifest = CapabilityManifest.load(manifest_path)
    except Exception as exc:
        return {
            "ok": False,
            "path": str(manifest_path),
            "errors": [f"manifest failed to load: {exc}"],
            "warnings": [],
        }

    if not manifest.capability_id.strip():
        errors.append("capability_id is empty")
    if not manifest.name.strip():
        errors.append("name is empty")
    if not manifest.version.strip():
        errors.append("version is empty")
    if manifest.is_executable:
        if ":" not in (manifest.execution_entrypoint or ""):
            errors.append("execution_entrypoint must be file.py:function")
        else:
            filename, _fn = manifest.execution_entrypoint.split(":", 1)
            pkg_dir = manifest_path.parent
            if not (pkg_dir / filename).is_file():
                errors.append(f"execution entrypoint file missing: {filename}")
        if manifest.verification_entrypoint:
            filename = manifest.verification_entrypoint.split(":", 1)[0]
            if not (manifest_path.parent / filename).is_file():
                warnings.append(f"verification entrypoint file missing: {filename}")
    else:
        warnings.append("procedural skill: not executable")

    return {
        "ok": not errors,
        "path": str(manifest_path),
        "capability_id": manifest.capability_id,
        "name": manifest.name,
        "version": manifest.version,
        "category": manifest.category,
        "is_executable": manifest.is_executable,
        "errors": errors,
        "warnings": warnings,
    }


def _cmd_provider_argv(argv: list[str]) -> int:
    if argv and argv[0] in ("-h", "--help"):
        print(
            "usage: jaeger provider doctor\n"
            "\n"
            "Report supported / configured / reachable / certified / active\n"
            "providers from the canonical runtime inventory.\n"
            "Missing credentials are unavailable, not a failure of this command.\n",
            file=sys.stderr,
        )
        return 0
    verb = argv[0] if argv else "doctor"
    if verb != "doctor":
        print(f"[jaeger provider] unknown verb {verb!r}", file=sys.stderr)
        return 2
    return _provider_doctor(argv[1:])


def _provider_doctor(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="jaeger provider doctor")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--cached-only", action="store_true")
    args = parser.parse_args(argv)
    report = provider_doctor_report(cached_only=args.cached_only)
    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        print("Jaeger provider doctor")
        print(f"  source: {report['source']}")
        print(f"  active_provider: {report.get('active_provider') or '(none)'}")
        print(f"  default_model: {report.get('default_model') or '(none)'}")
        for group in report.get("groups") or []:
            status = group.get("lifecycle") or group.get("status") or "unknown"
            n = len(group.get("models") or [])
            err = group.get("error")
            line = f"  - {group.get('provider')}: {status}  models={n}"
            if err:
                line += f"  ({err})"
            print(line)
        print("  code_supported_not_in_inventory:")
        for name in report.get("supported_not_live") or []:
            print(f"    - {name}: SUPPORTED — NOT LIVE TESTED")
    return 0


def provider_doctor_report(*, cached_only: bool = False) -> dict[str, Any]:
    """Canonical inventory plus explicit not-live-tested providers."""
    from jaeger_ai.core.models.discovery import canonical_runtime_inventory

    try:
        inventory = canonical_runtime_inventory(refresh=not cached_only, cached_only=cached_only)
    except Exception as exc:
        return {
            "ok": False,
            "source": "jaeger.runtime.truth",
            "error": str(exc),
            "groups": [],
            "supported_not_live": list(_CODE_SUPPORTED_PROVIDERS),
        }

    groups = []
    seen: set[str] = set()
    for group in inventory.get("groups") or []:
        provider = str(group.get("provider") or group.get("name") or "unknown")
        seen.add(provider.lower())
        models = list(group.get("models") or [])
        reachable = bool(models) or str(group.get("status") or "").lower() in {"ok", "online", "reachable"}
        groups.append({
            "provider": provider,
            "status": group.get("status"),
            "lifecycle": _lifecycle_label(group, reachable=reachable),
            "models": [
                {
                    "id": m.get("id") or m.get("name"),
                    "certified_roles": m.get("certified_roles") or [],
                    "failed_roles": m.get("failed_roles") or [],
                }
                for m in models
            ],
            "error": group.get("error"),
        })

    supported_not_live = [
        name for name in _CODE_SUPPORTED_PROVIDERS
        if not any(name.lower() in s for s in seen)
    ]
    return {
        "ok": True,
        "source": "jaeger.runtime.truth",
        "active_provider": inventory.get("active_provider"),
        "default_model": inventory.get("default_model") or inventory.get("active_model"),
        "groups": groups,
        "supported_not_live": supported_not_live,
    }


_CODE_SUPPORTED_PROVIDERS = (
    "openai",
    "anthropic",
    "gemini",
    "xai",
    "openrouter",
    "groq",
    "deepseek",
    "together",
    "lmstudio",
    "vllm",
    "llamacpp",
    "mlx",
)


def _lifecycle_label(group: dict[str, Any], *, reachable: bool) -> str:
    status = str(group.get("status") or "").lower()
    if status in {"error", "offline", "unavailable"}:
        return "SUPPORTED / UNAVAILABLE"
    if reachable:
        return "DISCOVERED"
    return "SUPPORTED / NOT LIVE TESTED"


def _cmd_device_argv(argv: list[str]) -> int:
    if argv and argv[0] in ("-h", "--help"):
        print(
            "usage: jaeger device inspect [device_id]\n"
            "\n"
            "Inspect the generic device/node contract and known client surfaces.\n"
            "The DeviceRegistry is experimental and in-memory; Mac/Web/phone\n"
            "are control-plane clients today.\n",
            file=sys.stderr,
        )
        return 0
    verb = argv[0] if argv else "inspect"
    rest = argv[1:] if argv else []
    if verb != "inspect":
        # allow `jaeger device <id>` as inspect
        rest = argv
    return _device_inspect(rest)


def _device_inspect(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="jaeger device inspect")
    parser.add_argument("device_id", nargs="?")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    report = device_inspect_report(args.device_id)
    if args.json:
        print(json.dumps(report, indent=2, default=str))
        return 0 if report.get("ok") else 1
    print("Jaeger device inspect")
    print(f"  registry: {report['registry_status']}")
    print("  known client surfaces (not Device records):")
    for surface in report["client_surfaces"]:
        print(f"    - {surface['name']}: {surface['role']} via {surface['transport']}")
    if args.device_id:
        match = report.get("device")
        if not match:
            print(f"  device {args.device_id!r} is not in the in-memory registry")
            return 1
        print(f"  device_id: {match['device_id']}")
        print(f"  type: {match.get('device_type')}")
        print(f"  state: {match.get('connection_state')}")
        print(f"  capabilities: {', '.join(match.get('capabilities') or [])}")
    elif report.get("registered"):
        print("  registered (in-memory, this process):")
        for dev in report["registered"]:
            print(f"    - {dev['device_id']} ({dev.get('device_type')}) {dev.get('connection_state')}")
    else:
        print("  registered: (none — DeviceRegistry is process-local and experimental)")
    return 0


def device_inspect_report(device_id: str | None = None) -> dict[str, Any]:
    from jaeger_ai.core.devices.registry import DeviceRegistry

    # Process-local experimental registry. Production Mac/Web/phone are clients.
    registry = DeviceRegistry()
    registered = [
        {
            "device_id": d.device_id,
            "name": d.name,
            "device_type": d.device_type,
            "connection_state": d.connection_state,
            "capabilities": list(d.capabilities),
            "transport": d.transport,
            "owner_entity": d.owner_entity,
        }
        for d in registry.list_devices()
    ]
    match = next((d for d in registered if d["device_id"] == device_id), None) if device_id else None
    return {
        "ok": device_id is None or match is not None,
        "registry_status": "EXPERIMENTAL in-memory DeviceRegistry (not production persistence)",
        "client_surfaces": [
            {"name": "Mac SwiftUI", "role": "ATTACHED_CLIENT", "transport": "REST+SSE :8810 / AF_UNIX bridge"},
            {"name": "WebUI", "role": "ATTACHED_CLIENT", "transport": "HTTP :8790 → Gateway :8810"},
            {"name": "CLI", "role": "ATTACHED_CLIENT", "transport": "in-process / Gateway"},
            {"name": "Phone PWA", "role": "ATTACHED_CLIENT", "transport": "Tailscale HTTPS :8443 → WebUI"},
        ],
        "registered": registered,
        "device": match,
    }
