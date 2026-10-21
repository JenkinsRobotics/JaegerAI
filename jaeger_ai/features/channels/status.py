"""Current Gateway channel registrations, never inferred external delivery health."""
from __future__ import annotations
from .catalog import bundled_catalog
from .registry import get_registry


def snapshot() -> dict:
    from jaeger_ai.plugins import get_bridge, list_bridges
    catalog = {row.id: row for row in bundled_catalog()}
    adapters = set(get_registry().list_ids())
    bridges = set(list_bridges())
    rows = []
    for channel_id in sorted(set(catalog) | adapters | bridges):
        declared = catalog.get(channel_id)
        bridge = get_bridge(channel_id)
        thread = getattr(bridge, '_thread', None) if bridge is not None else None
        rows.append({'id': channel_id, 'name': declared.label if declared else channel_id,
                     'catalog_maturity': declared.status if declared else 'unknown',
                     'adapter_registered': channel_id in adapters,
                     'bridge_registered': bridge is not None,
                     'thread_state': 'unknown' if thread is None else 'running' if thread.is_alive() else 'stopped',
                     'connection_health': 'not_probed', 'delivery_verified': False,
                     'actions': ['refresh']})
    return {'channels': rows, 'scope': 'current_gateway_process_only'}
