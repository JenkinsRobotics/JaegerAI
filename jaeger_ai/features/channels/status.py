"""Current Gateway channel registrations, never inferred external delivery health."""
from __future__ import annotations
from .catalog import bundled_catalog
from .registry import get_registry


def snapshot(store=None) -> dict:
    from jaeger_ai.plugins import get_bridge, list_bridges
    catalog = {row.id: row for row in bundled_catalog()}
    adapters = set(get_registry().list_ids())
    bridges = set(list_bridges())
    rows = []
    for channel_id in sorted(set(catalog) | adapters | bridges):
        declared = catalog.get(channel_id)
        bridge = get_bridge(channel_id)
        thread = getattr(bridge, '_thread', None) if bridge is not None else None
        from .bindings import SUPPORTED, read
        binding = read(store, channel_id) if store is not None and channel_id in SUPPORTED else None
        from jaeger_ai.plugins._messaging import bridge_activity
        activity = bridge_activity(bridge) if bridge is not None else {'active_handlers':0,'stopping':False}
        actions = ['refresh']
        if channel_id in SUPPORTED:
            actions += ['disconnect'] if bridge is not None and not activity['active_handlers'] else ['bind','connect'] if bridge is None and channel_id not in adapters else []
        rows.append({'binding':binding,'active_binding':getattr(bridge,'_jaeger_gateway_binding',None), **activity, 'id': channel_id, 'name': declared.label if declared else channel_id,
                     'catalog_maturity': declared.status if declared else 'unknown',
                     'adapter_registered': channel_id in adapters,
                     'bridge_registered': bridge is not None,
                     'thread_state': 'unknown' if thread is None else 'running' if thread.is_alive() else 'stopped',
                     'connection_health': 'not_probed', 'delivery_verified': False,
                     'actions': actions})
    return {'channels': rows, 'scope': 'current_gateway_process_only'}
