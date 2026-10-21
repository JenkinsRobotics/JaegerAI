"""Metadata-only notifications; the Gateway's durable events remain authoritative."""
from __future__ import annotations
import json
from contextlib import closing
from aiohttp import web

KEY='notifications:operator'
NOTIFICATION_EVENTS=('approval.request','task.updated','agent.handoff.finished','notification.proactive','turn.failed','turn.unknown')


def settings(conn):
    row=conn.execute('SELECT value FROM schema_meta WHERE key=?',(KEY,)).fetchone()
    value=json.loads(row[0]) if row else {'revision':0,'enabled':True,'muted_agent_ids':[],'read_through':0}
    if not isinstance(value,dict) or type(value.get('revision')) is not int or type(value.get('enabled')) is not bool or not isinstance(value.get('muted_agent_ids'),list) or type(value.get('read_through')) is not int:
        raise ValueError('Invalid saved notification preferences; original preserved')
    return value


def write(conn,value):
    conn.execute('INSERT INTO schema_meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(KEY,json.dumps(value)))


def feed(store):
    with closing(store._get_conn()) as conn:
        prefs=settings(conn)
        observed=conn.execute('SELECT COALESCE(MAX(event_id),0) FROM activity_history').fetchone()[0]
        rows=conn.execute("SELECT a.event_id,a.session_id,a.event,a.data_json,a.timestamp,s.metadata_json FROM activity_history a JOIN sessions s ON s.session_id=a.session_id WHERE a.event_id<=? AND a.event IN ('approval.request','task.updated','agent.handoff.finished','notification.proactive','turn.failed','turn.unknown') ORDER BY a.event_id DESC LIMIT 500",(observed,)).fetchall()
        result=[];seen=set()
        for row in rows:
            data=json.loads(row['data_json']);metadata=json.loads(row['metadata_json'] or '{}');agent_id=metadata.get('agent_id')
            if agent_id in prefs['muted_agent_ids']:continue
            event=row['event'];entity=data.get('task') if event=='task.updated' else data.get('handoff') if event=='agent.handoff.finished' else data
            entity=entity if isinstance(entity,dict) else {}
            status=entity.get('state') or entity.get('status')
            status=status if isinstance(status,str) and status in {'done','completed','completed_verified','failed','cancelled','denied','execution_unknown','needs_owner','blocked'} else None
            if event in {'task.updated','agent.handoff.finished'} and status not in {'done','completed','completed_verified','failed','cancelled','denied','execution_unknown','needs_owner','blocked'}:continue
            identity=(event,entity.get('task_id') or entity.get('id') or entity.get('approval_id') or entity.get('request_id') or row['event_id'],status)
            if identity in seen:continue
            seen.add(identity)
            title={'approval.request':'Approval requested','notification.proactive':'New proactive notification','turn.failed':'Conversation failed','turn.unknown':'Conversation outcome unknown','task.updated':'Task status changed','agent.handoff.finished':'Delegated work status changed'}[event]
            result.append({'event_id':row['event_id'],'session_id':row['session_id'],'agent_id':agent_id,'title':title,'status':status,'timestamp':row['timestamp'],'unread':row['event_id']>prefs['read_through']})
            if len(result)==50:break
        return {'preferences':prefs,'notifications':result,'privacy':'metadata_only_no_message_preview','scope':'local_operator','enabled':prefs['enabled'],'observed_through':observed}


def register(gateway):
    async def read(request):
        try:return web.json_response(feed(gateway.store))
        except (ValueError,TypeError):return web.json_response({'error':'Saved notification state unavailable; original preserved'},status=409)
    async def mutate(request):
        try:
            body=await request.json()
            if not isinstance(body,dict):raise ValueError('Object required')
            with gateway.store._immediate() as conn:
                current=settings(conn)
                if set(body)=={'read_through'}:
                    cursor=body['read_through'];maximum=conn.execute('SELECT COALESCE(MAX(event_id),0) FROM activity_history').fetchone()[0]
                    if type(cursor) is not int or not 0<=cursor<=maximum:raise ValueError('Read cursor must reference observed durable events')
                    current['read_through']=max(current['read_through'],cursor)
                else:
                    if set(body)!={'expected_revision','enabled','muted_agent_ids'} or type(body['enabled']) is not bool or not isinstance(body['muted_agent_ids'],list) or len(body['muted_agent_ids'])>512 or any(not isinstance(v,str) for v in body['muted_agent_ids']):raise ValueError('Invalid notification preferences')
                    if type(body['expected_revision']) is not int or body['expected_revision']!=current['revision']:return web.json_response({'error':'Notification preferences changed; reload before saving'},status=409)
                    registry=gateway._registry()
                    if any(registry.get_agent(v) is None for v in body['muted_agent_ids']):raise ValueError('Unknown muted agent identity')
                    current.update(enabled=body['enabled'],muted_agent_ids=sorted(set(body['muted_agent_ids'])),revision=current['revision']+1)
                write(conn,current)
            gateway.event_bus.publish('*','notifications.changed',{'revision':current['revision']})
            return web.json_response({'preferences':current})
        except (ValueError,TypeError):return web.json_response({'error':'Invalid or unavailable notification preferences; original preserved'},status=400)
    gateway.app.router.add_get('/v1/notifications',read)
    gateway.app.router.add_patch('/v1/notifications',mutate)
