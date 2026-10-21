"""Metadata-only notifications; the Gateway's durable events remain authoritative."""
from __future__ import annotations
import json
from contextlib import closing
from aiohttp import web

KEY='notifications:operator'
NOTIFICATION_EVENTS=('approval.request','task.updated','agent.handoff.finished','notification.proactive','turn.failed','turn.unknown')
CATEGORIES={'all':('All activity',NOTIFICATION_EVENTS),'approvals':('Approvals',('approval.request',)),'tasks':('Tasks',('task.updated',)),'delegates':('Delegated work',('agent.handoff.finished',)),'errors':('Conversation failures and unknowns',('turn.failed','turn.unknown')),'proactive':('Proactive notifications',('notification.proactive',))}


def settings(conn):
    row=conn.execute('SELECT value FROM schema_meta WHERE key=?',(KEY,)).fetchone()
    value=json.loads(row[0]) if row else {'revision':0,'enabled':True,'muted_agent_ids':[],'read_through':0}
    if not isinstance(value,dict) or type(value.get('revision')) is not int or type(value.get('enabled')) is not bool or not isinstance(value.get('muted_agent_ids'),list) or type(value.get('read_through')) is not int:
        raise ValueError('Invalid saved notification preferences; original preserved')
    return value


def write(conn,value):
    conn.execute('INSERT INTO schema_meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(KEY,json.dumps(value)))


def feed(store,*,before=None,category='all'):
    if category not in CATEGORIES:raise ValueError('Unknown notification category')
    if before is not None and (type(before) is not int or not 0<before<2**63):raise ValueError('Invalid notification cursor')
    with closing(store._get_conn()) as conn:
        prefs=settings(conn)
        observed=conn.execute('SELECT COALESCE(MAX(event_id),0) FROM activity_history').fetchone()[0]
        events=CATEGORIES[category][1]
        cursor=min(observed,before-1) if before is not None else observed
        rows=conn.execute("SELECT a.event_id,a.session_id,a.event,a.data_json,a.timestamp,s.metadata_json FROM activity_history a JOIN sessions s ON s.session_id=a.session_id WHERE a.event_id<=? AND a.event IN ("+','.join('?' for _ in events)+") ORDER BY a.event_id DESC LIMIT 500",(cursor,*events)).fetchall()

        result=[];seen=set();scanned=0;last=None
        for row in rows:
            scanned+=1;last=row['event_id']
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
        # Presence over retained activity, never a total unread count. Older or
        # category pages cannot establish the current global presence. A full
        # filtered scan with no visible row stays unknown when capped at500.
        presence = 'unknown'
        if before is None and category == 'all':
            if not prefs['enabled']:
                presence = 'absent'
            elif any(row['unread'] for row in result):
                presence = 'present'
            elif result or scanned < 500:
                presence = 'absent'  # newest visible row is at/below read watermark
        return {'retained_unread_presence':presence,'preferences':prefs,'notifications':result,'privacy':'metadata_only_no_message_preview','scope':'local_operator','enabled':prefs['enabled'],'observed_through':observed,'next_before':last if last and (len(result)==50 or scanned==500) else None,'category':category,'categories':[{'id':key,'label':value[0]} for key,value in CATEGORIES.items()],'pagination_scope':'retained_activity_per_page_entity_dedupe'}


def register(gateway):
    async def read(request):
        try:
            raw=request.query.get('before');cursor=int(raw) if raw else None;category=request.query.get('category','all')
            if category not in CATEGORIES or cursor is not None and not 0<cursor<2**63:raise ValueError('Invalid notification filter/cursor')
        except (ValueError,TypeError):return web.json_response({'error':'Invalid notification filter/cursor'},status=400)
        try:return web.json_response(feed(gateway.store,before=cursor,category=category))
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
