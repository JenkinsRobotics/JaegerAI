"""Pure, conservative defaults for a new foreground admission.

These are execution facts, not client choices or additional tool authority.
No model discovery, credential access, client construction or runtime boot.
"""
import hashlib
import json
from pathlib import Path
from typing import Any


def configured_execution_defaults(layout: Any, config: Any) -> dict[str, Any]:
    from jaeger_ai.core.models.configuration import _BASE_URLS
    from jaeger_ai.core.models.router import normalize_ollama_provider

    result = {}
    workspace = getattr(layout, 'workspace_dir', None)
    if isinstance(workspace, (str, Path)) and str(workspace) and Path(workspace).is_absolute():
        result['workspace'] = str(Path(workspace).resolve())
    ext = getattr(config, 'external_model', None)
    model = str(getattr(ext, 'model', '') or '').strip()
    provider = str(getattr(ext, 'provider', '') or '').strip()
    # A pinned route must round-trip through select_client unchanged. Aliases,
    # CLI/local defaults and routed model strings are deliberately not guessed.
    if (getattr(ext, 'enabled', False) and model
            and model.lower() not in {'default', 'jaeger', 'local', 'none'}
            and not model.startswith('@') and provider in _BASE_URLS
            and provider != 'cli' and normalize_ollama_provider(provider) == provider):
        result.update(model=model, provider=provider, route_fingerprint=default_route_fingerprint(config))
    return result


def default_route_fingerprint(config: Any) -> str:
    """Route drift detector. Hash configuration selectors, never secret values."""
    ext = config.external_model
    fields = ('enabled', 'model', 'provider', 'base_url', 'api_key_env', 'api_key_credential')
    values = {key: getattr(ext, key, None) for key in fields}
    return hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()


def validate_default_route(config: Any, expected: str | None) -> None:
    if expected and default_route_fingerprint(config) != expected:
        raise ValueError('Admitted default model route changed; no model dispatch')


def execution_project_root(execution: dict[str, Any], layout: Any) -> str | None:
    workspace = str(execution.get('workspace') or '')
    marker = execution.get('_instance_defaults') or {}
    if marker.get('workspace'):
        actual = getattr(layout, 'workspace_dir', None)
        if (not isinstance(actual, (str, Path)) or not Path(actual).is_absolute()
                or str(Path(actual).resolve()) != marker['workspace']
                or workspace != marker['workspace']):
            raise ValueError('Admitted default workspace changed; no tool dispatch')
        # A pinned effective root is not an explicitly selected project.
        # Preserve instance-mode bare paths and workspace+skills write roots.
        return None
    return workspace or None


class InstanceDefaultsConflict(ValueError):
    """A derived request cannot prove the instance mode it proposes to retain."""


def inherit_instance_defaults(source: dict[str, Any] | None, target: dict[str, Any], *,
                              session_id: str, claimed: dict[str, Any] | None = None,
                              expected: dict[str, Any] | None = None, authority: dict[str, Any] | None = None,
                              allow_overrides: bool = False) -> dict[str, Any]:
    """Derive mode only from canonical request truth, never a task's assertion.

    The store calls this while holding its admission transaction. A task also
    checks it before recovering an already-admitted slice. Explicit retries
    may change route/project, but cannot silently retain incompatible defaults
    or widen tools/caller/tier. No configuration lookup or authority synthesis.
    """
    if not source or source.get('session_id') != session_id:
        raise InstanceDefaultsConflict('Instance defaults source request/session is unavailable; no dispatch')
    original = source.get('execution') or {}
    if expected is not None and original != expected:
        raise InstanceDefaultsConflict('Instance defaults source changed before admission; no dispatch')
    marker = original.get('_instance_defaults') or {}
    if claimed is not None and (not marker or claimed != marker):
        raise InstanceDefaultsConflict('Instance defaults differ from canonical source; no dispatch')
    if not marker:
        return {}
    if source.get('digest_version', 1) < 2:
        raise InstanceDefaultsConflict('Historical request cannot establish instance defaults; no dispatch')
    for limit in (original, authority if authority is not None else original):
        if (target.get('caller') != limit.get('caller')
                or target.get('interaction_tier') != limit.get('interaction_tier')):
            raise InstanceDefaultsConflict('Inherited caller or interaction tier changed; no dispatch')
        grant, requested = limit.get('allowed_tools'), target.get('allowed_tools')
        if grant is not None and (requested is None or not set(requested).issubset(grant)):
            raise InstanceDefaultsConflict('Inherited tool authority widened; no dispatch')
    route_same = all(target.get(key) == original.get(key) for key in ('model', 'provider'))
    workspace_same = target.get('workspace') == original.get('workspace')
    if not allow_overrides and (not route_same or not workspace_same):
        raise InstanceDefaultsConflict('Inherited execution differs from canonical source; no dispatch')
    retained = {}
    if route_same and marker.get('route_fingerprint'):
        retained['route_fingerprint'] = marker['route_fingerprint']
    if workspace_same and marker.get('workspace'):
        retained['workspace'] = marker['workspace']
    return retained
