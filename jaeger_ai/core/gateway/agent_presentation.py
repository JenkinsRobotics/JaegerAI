"""Validated operator presentation, never agent identity/execution configuration.

One Gateway state root represents one local operator. Caller tokens identify
surfaces of that operator, not separate WebUI users. Existing admin scope guards
writes; no caller-supplied owner/profile selector is accepted.
"""
from __future__ import annotations
import unicodedata
from typing import Any

MAX_AGENT_PINS = 8
ICON_PRESETS = ("robot", "robot-square", "robot-shield")


def validate_patch(body: Any) -> dict[str, Any]:
    if not isinstance(body, dict) or not body or set(body) - {'display_name', 'archived', 'pinned', 'icon_preset', 'section_id', 'deleted'}:
        raise ValueError('Only supported presentation fields are accepted')
    out = dict(body)
    if 'display_name' in out and out['display_name'] is not None:
        if not isinstance(out['display_name'], str):
            raise ValueError('display_name must be text or null to restore its default')
        name = unicodedata.normalize('NFC', out['display_name'].strip())
        if not 1 <= len(name) <= 80 or any(unicodedata.category(c).startswith('C') or unicodedata.category(c) in {'Zl', 'Zp'} for c in name):
            raise ValueError('display_name must have 1–80 visible characters on one line')
        out['display_name'] = name
    if 'icon_preset' in out and out['icon_preset'] is not None and out['icon_preset'] not in ICON_PRESETS:
        raise ValueError('Unsupported icon preset')
    for key in ('archived', 'pinned', 'deleted'):
        if key in out and not isinstance(out[key], bool):
            raise ValueError(f'{key} must be a boolean')
    if 'section_id' in out and out['section_id'] is not None:
        import re
        if not isinstance(out['section_id'], str) or not re.fullmatch(r'section_[a-f0-9]{32}', out['section_id']):
            raise ValueError('Invalid section ID')
    return out


def can_rename(row: dict[str, Any]) -> bool:
    return row.get('role') in {'lead', 'specialist'} and not (row.get('metadata') or {}).get('internal') and row.get('id') not in {'native:gateway', 'native:surfaces', 'gateway', 'surfaces'}


class PresentationConflict(ValueError):
    """A concurrent client changed ordered pins; retry from the fresh roster."""


def protected(row: dict[str, Any]) -> bool:
    # Presentation protection is independent of execution lead/system grants.
    return not can_rename(row)


def primary_eligible(row: dict[str, Any]) -> bool:
    return (can_rename(row) and row.get('kind') == 'jaeger_native'
            and not row.get('deleted') and not row.get('hidden') and not row.get('archived') and not row.get('disabled'))


def project(row: dict[str, Any], saved: dict[str, dict[str, Any]], *, writable: bool = False, primary_id: str | None = None) -> dict[str, Any]:
    prefs = saved.get(row['id'], {})
    from jaeger_ai.core.agent_registry.specialists import LEAD_AGENT_ID
    primary_id = primary_id or LEAD_AGENT_ID
    guarded = protected(row)
    deleted = prefs.get('deleted') is True and not guarded
    archived = prefs.get('archived') is True and not guarded
    out = {**row, 'primary': row['id'] == primary_id, 'archived': archived, 'hidden': bool(row.get('hidden')) or archived or deleted, 'deleted': deleted, 'section_id': prefs.get('section_id'),
           'pinned': prefs.get('pinned') is True and not guarded,
           'icon_preset': prefs.get('icon_preset'), 'icon_choices': list(ICON_PRESETS),
           'pin_order': prefs.get('pin_order'), 'presentation': {k: prefs[k] for k in ('display_name', 'archived', 'pinned', 'pin_order', 'icon_preset', 'section_id', 'deleted') if k in prefs},
           'ui_actions': {'icon': writable and can_rename(row), 'read': writable, 'rename': writable and can_rename(row), 'hide': writable and not guarded, 'pin': writable and not guarded, 'unread': writable and not guarded, 'sections': writable and not guarded, 'remove': writable and not guarded and row['id'] != primary_id, 'primary': writable and primary_eligible({**row, 'archived': archived, 'deleted': deleted})}}
    # This is the existing local authority boundary, not a team-membership
    # system inferred from execution roles, primary pointers or sidebar groups.
    out['access'] = {'scope': 'local_operator', 'sharing_supported': False,
                     'membership_management_supported': False, 'grouping_grants_access': False,
                     'reason': 'No cross-account membership authority is configured'}
    if isinstance(prefs.get('display_name'), str):
        out['display_name'] = prefs['display_name']
    return out
