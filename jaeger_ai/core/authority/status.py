"""Read-only policy-source projection; never an action authorization or preview run.

Uses the same commissioning/autonomy/grants owners as the execution gate. Reading
status must not initialize an EntityRuntime, run operator hooks or issue grants.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from jaeger_ai.core.instance.commissioning import load_authority_policy_checked
from jaeger_ai.core.runtime.autonomy import configured_autonomy, effective_autonomy


def snapshot(layout):
    base = {'scope': 'bound_instance_policy_sources', 'action_authorized': False,
            'mutation_supported': False, 'hook_execution_performed': False,
            'per_request_grants': 'not_inferred', 'os_permissions': 'not_inferred',
            'limits': ['Source settings are not the effective decision for a proposed tool call.',
                       'Global Stop, lifecycle ownership, caller trust, specialist ceilings, protected targets, destructive-action approval and operator hooks still apply.',
                       'A primary-bot badge or a saved skill grant never grants a different execution role.',
                       'No policy, standing grant, OS permission or credential is changed here.']}
    if layout is None:
        return {**base, 'state': 'runtime_not_bound', 'sources': [], 'revision': None}
    root = Path(layout.root)
    try:
        policy = load_authority_policy_checked(root)
        rows = []
        for section, keys in {'filesystem': ('read', 'write'), 'git': ('local_commit', 'push'),
                              'email': ('read', 'send'), 'calendar': ('read', 'modify')}.items():
            values = policy.get(section, {})
            for key in keys:
                value = values.get(key) if isinstance(values, dict) else None
                rows.append({'id': section+'.'+key, 'value': value if type(value) is bool else 'unspecified_or_invalid', 'source': 'commissioning_authority'})
        shell = policy.get('shell', {})
        mode = shell.get('risk_mode') if isinstance(shell, dict) else None
        rows.append({'id': 'shell.risk_mode', 'value': mode if mode in ('deny', 'confirm', 'allow') else 'unspecified_or_invalid', 'source': 'commissioning_authority'})
        for key in ('screen', 'microphone', 'camera', 'protected_merge_deployment'):
            value = policy.get(key)
            rows.append({'id': key, 'value': value if type(value) is bool else 'unspecified_or_invalid', 'source': 'commissioning_authority'})
        files = policy.get('filesystem', {})
        roots = files.get('approved_roots') if isinstance(files, dict) else None
        roots_count = len(roots) if isinstance(roots, list) and all(isinstance(r, str) for r in roots) else None
        rows.append({'id': 'filesystem.approved_root_count', 'value': roots_count if roots_count is not None else 'unspecified_or_invalid', 'source': 'commissioning_authority'})
        config_path = layout.config_path
        rows.extend([{'id': 'autonomy.configured', 'value': configured_autonomy(config_path), 'source': 'instance_config'},
                     {'id': 'autonomy.current', 'value': effective_autonomy(config_path), 'source': 'existing_autonomy_owner'}])
        commissioning_state = 'configured' if policy else 'not_configured'
    except (OSError, ValueError, TypeError, RuntimeError):
        # No parse exceptions, paths, root labels or policy contents cross the UI.
        rows = []; commissioning_state = 'unavailable'
    grants_path = root/'permissions.json'
    grants_state, grant_count = 'not_configured', 0
    try:
        if grants_path.exists():
            data = json.loads(grants_path.read_text(encoding='utf-8'))
            names = data.get('granted_skills') if isinstance(data, dict) else None
            if not isinstance(names, list) or not all(isinstance(n, str) and n for n in names):
                raise ValueError('Invalid stored skill grants')
            from jaeger_os.core.safety.permissions import PermissionGrants
            grant_count = len(PermissionGrants.load(root).persistent)
            grants_state = 'configured'
    except (OSError, ValueError, TypeError):
        grants_state, grant_count = 'unavailable', None
    body = {**base, 'state': 'observed', 'commissioning_state': commissioning_state,
            'sources': rows, 'persistent_skill_grants': {'state': grants_state, 'count': grant_count,
            'scope': 'configured_skill_names_only_not_per_call_authority', 'names_disclosed': False}}
    # Stable revision is display freshness only; never a policy-write token.
    return {**body, 'revision': hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()}
