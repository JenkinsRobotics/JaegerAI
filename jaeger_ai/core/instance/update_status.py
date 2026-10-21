"""Read-only plan for the existing Jaeger installer/CLI, never the legacy WebUI updater.

No fetch, dependency installation, migration, executable candidate or service action.
A release tag alone is not a signed/trusted application-update manifest.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from jaeger_ai import __version__
from jaeger_ai.contract.updates import DEFAULT_UPDATE_CHANNEL, UPDATE_CHANNELS
from jaeger_ai.core.instance import instance
from jaeger_ai.core.instance.schemas import SCHEMA_VERSION


def snapshot(gateway, *, channel=DEFAULT_UPDATE_CHANNEL):
    if channel not in UPDATE_CHANNELS:
        raise ValueError('Unsupported canonical update channel')
    root = instance.install_root()
    method = instance.detect_install_method()
    method = method if method in {'dev-checkout', 'product-checkout', 'pip', 'pipx', 'unknown'} else 'unknown'
    revision, dirty = None, None
    if (root / '.git').exists():
        try:
            result = subprocess.run(['git', '-C', str(root), 'rev-parse', 'HEAD'], capture_output=True, text=True, timeout=2, check=False)
            if result.returncode == 0 and re.fullmatch('[a-f0-9]{40,64}', result.stdout.strip()):
                revision = result.stdout.strip()
            result = subprocess.run(['git', '-C', str(root), 'status', '--porcelain', '--untracked-files=normal'], capture_output=True, text=True, timeout=2, check=False)
            if result.returncode == 0:
                dirty = bool(result.stdout.strip())
        except (OSError, subprocess.TimeoutExpired):
            pass  # unknown is not a clean checkout or an available update
    schema = None
    manifest = Path(gateway._instance_root()) / 'manifest.json'
    try:
        # Existing manifest metadata only; no initialization, migration or credential files.
        with manifest.open('rb') as stream:
            raw = stream.read(16385)
        if len(raw) <= 16384:
            value = json.loads(raw)
            if isinstance(value, dict) and isinstance(value.get('schema_version'), str) and re.fullmatch(r'[0-9]{1,4}(?:\.[0-9]{1,4}){1,3}', value['schema_version']):
                schema = value['schema_version']
    except (OSError, ValueError):
        pass
    facts = gateway.store.diagnostics_snapshot()
    unknown = facts['requests'].get('execution_unknown', 0)
    active = sum(n for state, n in facts['requests'].items() if state not in {'completed', 'failed', 'cancelled', 'execution_unknown'})
    pending_approvals = facts['approvals'].get('pending', 0)
    nonterminal_handoffs = sum(n for state, n in facts['handoffs'].items() if state not in {'completed', 'failed', 'cancelled', 'rejected'})
    tasks = gateway.task_owner.store.list_tasks()
    pending_tasks = sum(not task.is_terminal for task in tasks)
    blockers = []
    if active: blockers.append('active_requests')
    if unknown: blockers.append('execution_unknown_requires_reconciliation')
    if pending_approvals: blockers.append('pending_approvals')
    if nonterminal_handoffs: blockers.append('nonterminal_or_unknown_handoffs')
    if pending_tasks: blockers.append('nonterminal_background_tasks')
    if dirty is True: blockers.append('source_checkout_has_local_changes')
    if method in {'dev-checkout', 'product-checkout'} and dirty is None: blockers.append('source_checkout_state_unknown')
    return {'component': 'jaeger-update-plan', 'reported_package_version': __version__,
            'install_method': method, 'channel': channel, 'channels': list(UPDATE_CHANNELS),
            'source_checkout_revision': revision, 'source_checkout_dirty': dirty,
            'identity_scope': 'checkout_metadata_not_loaded_runtime_or_signed_bundle_proof',
            'active_instance_schema': schema, 'installed_schema': SCHEMA_VERSION,
            'migration_state': 'unknown' if schema is None else 'current' if schema == SCHEMA_VERSION else 'review_required',
            'work': {'active_requests': active, 'unknown_requests': unknown, 'nonterminal_tasks': pending_tasks},
            'restart_blockers': blockers, 'restart_policy': 'manual_no_service_action',
            'release_state': 'not_probed', 'signature_state': 'no_verified_candidate',
            'automatic_install_supported': False, 'automatic_restart_supported': False,
            'check_command': ['jaeger', 'update', '--check', '--channel', channel],
            'manual_update_command': ['jaeger', 'update', '--channel', channel],
            'rollback': {'supported_by': 'existing_cli_product_backup_only',
                         'available': (root / '.update-prev').is_dir(),
                         'command': ['jaeger', 'update', '--rollback'],
                         'requires_explicit_operator_review': True},
            'limits': ['No remote release checked or candidate signature verified.',
                       'No upgrade, rollback, migration, install or restart is executed by this plan.',
                       'Observed blockers are not a complete process inventory or authorization to restart.',
                       'Signed application update/idle apply requires a trusted release manifest and separate deployment scope.']}
