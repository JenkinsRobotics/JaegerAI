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
    if not isinstance(body, dict) or not body or set(body) - {'display_name', 'archived', 'pinned', 'icon_preset'}:
        raise ValueError('Only display_name, archived, pinned and icon_preset presentation fields are accepted')
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
    for key in ('archived', 'pinned'):
        if key in out and not isinstance(out[key], bool):
            raise ValueError(f'{key} must be a boolean')
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
            and not row.get('hidden') and not row.get('archived') and not row.get('disabled'))


def project(row: dict[str, Any], saved: dict[str, dict[str, Any]], *, writable: bool = False, primary_id: str | None = None) -> dict[str, Any]:
    prefs = saved.get(row['id'], {})
    from jaeger_ai.core.agent_registry.specialists import LEAD_AGENT_ID
    primary_id = primary_id or LEAD_AGENT_ID
    guarded = protected(row)
    archived = prefs.get('archived') is True and not guarded
    out = {**row, 'primary': row['id'] == primary_id, 'archived': archived, 'hidden': bool(row.get('hidden')) or archived,
           'pinned': prefs.get('pinned') is True and not guarded,
           'icon_preset': prefs.get('icon_preset'), 'icon_choices': list(ICON_PRESETS),
           'pin_order': prefs.get('pin_order'), 'presentation': {k: prefs[k] for k in ('display_name', 'archived', 'pinned', 'pin_order', 'icon_preset') if k in prefs},
           'ui_actions': {'icon': writable and can_rename(row), 'read': writable, 'rename': writable and can_rename(row), 'hide': writable and not guarded, 'pin': writable and not guarded, 'unread': writable and not guarded, 'primary': writable and primary_eligible({**row, 'archived': archived})}}
    if isinstance(prefs.get('display_name'), str):
        out['display_name'] = prefs['display_name']
    return out
