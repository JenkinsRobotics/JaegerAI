"""Canonical handoff relationships from retained requests, never message authority."""
from __future__ import annotations

from jaeger_ai.contract.handoffs import child_request_id
from jaeger_ai.core.agent_registry.specialist_runtime import specialist_session
from jaeger_ai.core.gateway.session_store import _session_agent


def child_receipt(gateway, record):
    session_id=specialist_session(record['to_agent_id'],record.get('request_id') or record['id'])
    rid=child_request_id(record.get('request_id') or record['id'])
    row=gateway.store.get_request(rid)
    if row is None:return session_id,rid,None,False
    session=gateway.store.get_session(row['session_id']) or {}
    meta=session.get('metadata') or {}
    execution=row.get('execution') or {}
    bound=(row['session_id']==session_id and meta.get('handoff_id')==record['id']
           and meta.get('agent_id')==record['to_agent_id']
           and meta.get('parent_session_id')==record.get('session_id')
           and execution.get('is_subordinate') is True
           and execution.get('caller')==(record.get('metadata') or {}).get('caller_actor'))
    return session_id,rid,row,bound


def parent_context(gateway, reference, session_id, actor):
    """Qualify existing root IDs; historical/foreign ambiguity remains unbound.

    No migration or guessed links. The inherited actor is a fixed authenticated
    context. Internal turns may delegate through jaegerd's existing own actor.
    """
    if not reference:return None
    with gateway.store._get_conn() as conn:
        rows=conn.execute('SELECT * FROM client_requests WHERE request_id=? OR turn_id=? OR native_run_id=? LIMIT 2',(reference,reference,reference)).fetchall()
    if len(rows)!=1:return None
    root=gateway.store._request_row(rows[0])
    caller=(root.get('execution') or {}).get('caller')
    if caller!=actor and not (caller is None and actor=='agent:jaeger'):return None
    if session_id and root['session_id']!=session_id:return None
    session=gateway.store.get_session(root['session_id']) or {}
    agent=_session_agent(root['session_id'],session.get('metadata') or {}) or 'native:jaeger'
    record=gateway._registry().get_agent(agent)
    if record is None:return None
    binding={'request_id':root['request_id'],'session_id':root['session_id'],'root_actor':caller,'child_actor':actor,'source_agent_id':record.id}
    handoff_id=(session.get('metadata') or {}).get('handoff_id')
    parent_handoff=gateway.store.get_handoff(handoff_id) if handoff_id else None
    chain=[]
    if parent_handoff:
        _,rid,_,bound=child_receipt(gateway,parent_handoff)
        if not bound or rid!=root['request_id']:return None
        chain=list((parent_handoff.get('metadata') or {}).get('parent_chain') or [])
    return {'binding':binding,'root':root,'parent_chain':chain}


def owned_children(gateway, root):
    """Only producer-qualified relationships; never infer from editable labels."""
    result=[]
    for row in gateway.store.list_handoffs():
        binding=(row.get('metadata') or {}).get('parent_binding')
        if not isinstance(binding,dict):continue
        if (binding.get('request_id')==root['request_id'] and binding.get('session_id')==root['session_id']
            and binding.get('root_actor')==(root.get('execution') or {}).get('caller')
            and binding.get('child_actor')==(row.get('metadata') or {}).get('caller_actor')
            and row.get('session_id')==root['session_id'] and row.get('from_agent_id')==binding.get('source_agent_id')):
            result.append(row)
    return result
