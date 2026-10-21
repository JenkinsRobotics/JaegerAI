"""Immutable-ID memory directories with non-destructive legacy selection."""
from __future__ import annotations
import hashlib
from pathlib import Path


def legacy_name(name):
    return ''.join(ch if ch.isalnum() or ch in '-_' else '_' for ch in name)[:48] or '_'


def directory(agent,root:Path,records) -> Path:
    agent_id=getattr(agent,'id',None)
    if not isinstance(agent_id,str) or not agent_id:raise ValueError('Immutable agent identity required for notes')
    base=root/'memory'/'agents'
    modern=base/'by-id'/hashlib.sha256(agent_id.encode()).hexdigest()[:32]
    legacy=base/legacy_name(str(getattr(agent,'name','')))
    legacy_exists = legacy.exists() and legacy.name != 'by-id'
    if legacy.name == 'by-id' and (legacy/'NOTES.md').exists():raise ValueError('Reserved legacy notes namespace; explicit ownership reconciliation required')
    if modern.exists() and legacy_exists and (legacy/'NOTES.md').exists():raise ValueError('Both immutable-ID and legacy notes exist; reconcile without overwriting either')
    if modern.exists():selected=modern
    elif legacy_exists:
        owners={record.id for record in records if legacy_name(record.name)==legacy.name}
        if owners!={agent_id}:raise ValueError('Legacy notes have ambiguous agent ownership; preserve and assign explicitly before use')
        selected=legacy
    else:selected=modern
    if not selected.resolve().is_relative_to(base.resolve()):raise ValueError('Agent notes directory escapes memory root')
    return selected
