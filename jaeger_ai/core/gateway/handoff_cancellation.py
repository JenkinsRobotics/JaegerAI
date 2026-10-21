"""Cancel only durably qualified handoffs through existing request scopes."""
from __future__ import annotations

import asyncio
import json

from jaeger_ai.core.agent_registry.projects import HARD_MAX_DEPTH, HARD_MAX_FANOUT
from jaeger_ai.core.gateway.handoff_ownership import child_receipt, owned_children

TERMINAL={'completed','failed','cancelled','denied','rejected'}
MAX_DESCENDANTS=sum(HARD_MAX_FANOUT**depth for depth in range(1,HARD_MAX_DEPTH+1))


def status(gateway,record):
    _,rid,child,bound=child_receipt(gateway,record)
    if child is not None and not bound:
        return {'handoff_id':record['id'],'outcome':'blocked','cancellation_confirmed':False,'reason':'Child ownership is not qualified; no foreign scope signalled'}
    if child is not None and child['status'] in {'completed','failed','cancelled'}:
        return {'handoff_id':record['id'],'child_request_id':rid,'child_status':child['status'],'outcome':'terminal','cancellation_confirmed':child['status']=='cancelled','confirmation_scope':'canonical_child_request'}
    if child is not None:
        return {'handoff_id':record['id'],'child_request_id':rid,'child_status':child['status'],'outcome':'unknown' if child['status']=='execution_unknown' else 'requested','cancellation_confirmed':False,'confirmation_scope':'canonical_child_request_unconfirmed'}
    if record['status'] in TERMINAL:
        before=(record.get('metadata') or {}).get('cancelled_before_admission') is True
        return {'handoff_id':record['id'],'outcome':'terminal','handoff_status':record['status'],'cancellation_confirmed':before,'confirmation_scope':'pre_admission' if before else 'handoff_record'}
    return {'handoff_id':record['id'],'child_request_id':rid if child else None,'child_status':child['status'] if child else None,'outcome':'unknown' if record['status']=='execution_unknown' or (child or {}).get('status')=='execution_unknown' else 'requested','cancellation_confirmed':False,'confirmation_scope':'unconfirmed'}


def unconfirmed_ids(results):
    ids=[]
    for row in results:
        if row['outcome'] in {'requested','unknown','blocked'}:ids.append(row.get('child_request_id') or row['handoff_id'])
        ids.extend(unconfirmed_ids(row.get('descendants') or []))
    return list(dict.fromkeys(ids))


async def cancel_one(gateway,handoff_id,*,operation_id,request_context=None,origin_request_id=None):
    context=request_context if request_context is not None else {}
    seen=context.setdefault('_handoff_cancel_seen',set())
    if handoff_id in seen:return {'handoff_id':handoff_id,'outcome':'blocked','cancellation_confirmed':False,'reason':'Repeated relationship suppressed'}
    if len(seen)>=MAX_DESCENDANTS:return {'handoff_id':handoff_id,'outcome':'blocked','cancellation_confirmed':False,'reason':'Owned tree exceeds supported relationship bound; remaining work unconfirmed'}
    seen.add(handoff_id)
    record=gateway.store.get_handoff(handoff_id)
    if record is None:raise KeyError(handoff_id)
    _,_,child,bound=child_receipt(gateway,record)
    if child is not None and not bound:return status(gateway,record)
    record=gateway.store.request_handoff_cancellation(handoff_id,operation_id,origin_request_id=origin_request_id)
    gateway._close_pending_approvals(record['request_id'])
    descendants=[]
    if child is not None and bound:
        class CancelRequest(dict):
            can_read_body=True
            def __init__(self):
                super().__init__(context)
                self.match_info={'id':child['session_id']}
            async def json(self):return {'request_id':child['request_id']}
        response=await gateway.handle_cancel_turn(CancelRequest())
        if response.status==200:descendants=json.loads(response.text).get('owned_handoff_cancellations') or []
    current=gateway.store.get_handoff(handoff_id) or record
    # A historical terminal label must not emit another completed/cancelled
    # result while its qualified child remains active or unknown. The child's
    # turn.cancel event and this command receipt carry authoritative progress.
    if record['status'] not in TERMINAL:
        gateway._publish_handoff('agent.handoff.finished' if current['status'] in TERMINAL else 'agent.handoff',current)
    return {**status(gateway,current),'descendants':descendants}


async def cancel_descendants(gateway,root,request_context):
    results=[]
    for index,record in enumerate(owned_children(gateway,root)):
        result=await cancel_one(gateway,record['id'],operation_id='parent-stop:'+root['request_id'],request_context=request_context,origin_request_id=root['request_id'])
        results.append(result)
        if index%16==15:await asyncio.sleep(0) # Existing HTTP task; no worker/service spawned.
    qualified={row['handoff_id'] for row in results}
    references={root.get(key) for key in ('request_id','turn_id','native_run_id') if root.get(key)}
    root_actor=(root.get('execution') or {}).get('caller')
    for row in gateway.store.list_handoffs():
        caller=(row.get('metadata') or {}).get('caller_actor')
        same_actor=caller==root_actor or (root_actor is None and caller=='agent:jaeger')
        if row['id'] not in qualified and row['status'] not in TERMINAL and same_actor and row.get('parent_run_id') in references and row.get('session_id')==root['session_id']:
            results.append({'handoff_id':row['id'],'outcome':'blocked','cancellation_confirmed':False,'reason':'Historical parent relationship is unqualified; retained without signalling'})
    return results
